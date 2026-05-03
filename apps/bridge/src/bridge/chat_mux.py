"""Per-chat `ClaudeSDKClient` orchestration — slice 8 §9.

Owns:
- one `ClaudeSDKClient` per live chat (cap = MAX_LIVE_CHATS_PER_SANDBOX)
- LRU eviction when a new chat would exceed the cap
- SDK-message → wire-frame translation
- `claude_session_id` capture from `ResultMessage` (first time only)

The mux does NOT own the WSS transport. It hands wire frames to a
callback the `WsClient` provides; the `WsClient` does seq allocation
+ ring-buffer + send.

**No custom MCP tool.** The dev agent uses Claude Code's built-in
tools only (Read/Write/Edit/Bash/Glob/Grep). Clarifications are just
assistant text questions — the next `UserMessage` answers them, same
as any chat turn. The orchestrator-side user agent watches the
filtered stream (final `assistant.message` + `result`) and decides
whether to auto-reply or defer to the human.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog
from agent_config import ClaudeCredentials
from claude_agent_sdk import (
    AssistantMessage as SDKAssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage as SDKResultMessage,
    StreamEvent as SDKStreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock as SDKThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage as SDKUserMessage,
)

_logger = structlog.get_logger("bridge.chat_mux")


# Wire-frame emit signature — the WsClient supplies this. The mux
# passes (chat_id, frame_type, kwargs); the WsClient handles seq
# allocation, JSON serialization, and ring-buffer insertion.
EmitFrame = Callable[[str, str, dict[str, Any]], Awaitable[None]]


@dataclass
class _LiveChat:
    chat_id: str
    client: ClaudeSDKClient
    last_active: float
    claude_session_id: str | None = None
    started_emitted: bool = False
    receive_task: asyncio.Task[None] | None = None
    # Tracks the SDK-level permission mode currently active for this
    # chat. Spawn locks the value; subsequent UserMessages can request
    # a different mode via the per-frame `permission_mode` field, in
    # which case we call `client.set_permission_mode(...)` before the
    # query. Without this, follow-ups would ignore the user's toggle.
    sdk_permission_mode: str = "acceptEdits"
    # Latest assistant text accumulator — flushed as `assistant.message`
    # at end-of-turn. SDK's streaming text comes in `AssistantMessage`
    # blocks; we emit deltas in real time AND a final `assistant.message`
    # for the user-agent filter.
    pending_assistant_text: list[str] = field(default_factory=list)
    # Per-StreamEvent index → in-flight tool_use accumulator. Lets us
    # emit `tool.started` in real time (between text deltas) instead of
    # waiting for the final `AssistantMessage` (which lands AFTER the
    # entire response, making tool calls appear at the bottom of the
    # bubble out of order with the surrounding text).
    inflight_tools: dict[int, dict[str, Any]] = field(default_factory=dict)
    # `tool_use_id`s already emitted via the StreamEvent path so the
    # AssistantMessage finalizer doesn't double-emit.
    streamed_tool_use_ids: set[str] = field(default_factory=set)


class ChatMux:
    def __init__(
        self,
        *,
        cwd: str,
        credentials: ClaudeCredentials,
        emit: EmitFrame,
        max_live_chats: int = 5,
    ) -> None:
        self._cwd = cwd
        self._credentials = credentials
        self._emit = emit
        self._max_live = max_live_chats
        self._chats: dict[str, _LiveChat] = {}
        self._lock = asyncio.Lock()

    async def handle_user_message(
        self,
        *,
        chat_id: str,
        text: str,
        claude_session_id: str | None,
        permission_mode: str | None = None,
    ) -> None:
        """Entry point for inbound `UserMessage` from the orchestrator.
        Spawns or reuses a `ClaudeSDKClient`, sends the text.

        `permission_mode` is honored only on FIRST spawn — once a
        ClaudeSDKClient is alive the SDK's spawn-time permission_mode
        is locked. Follow-ups in the same chat keep the original mode.
        """
        async with self._lock:
            chat = self._chats.get(chat_id)
            if chat is None:
                if len(self._chats) >= self._max_live:
                    await self._evict_lru_locked()
                chat = await self._spawn_locked(
                    chat_id=chat_id,
                    resume=claude_session_id,
                    permission_mode=permission_mode,
                )
                self._chats[chat_id] = chat
            chat.last_active = time.monotonic()
        # Runtime mode flip: if the user toggled permissions between
        # turns, push the new mode to the live SDK client BEFORE the
        # query. Cheap roundtrip via the SDK's control protocol.
        desired_sdk_mode = _map_permission_mode(permission_mode)
        if (
            desired_sdk_mode is not None
            and desired_sdk_mode != chat.sdk_permission_mode
        ):
            try:
                await chat.client.set_permission_mode(desired_sdk_mode)  # type: ignore[arg-type]
                chat.sdk_permission_mode = desired_sdk_mode
                _logger.info(
                    "bridge.chat_mux.permission_mode_changed",
                    chat_id=chat_id,
                    new_mode=desired_sdk_mode,
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "bridge.chat_mux.permission_mode_change_failed",
                    chat_id=chat_id,
                    error=str(exc)[:200],
                )
        try:
            await chat.client.query(text)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "bridge.chat_mux.query_failed",
                chat_id=chat_id,
                error=str(exc)[:200],
            )
            await self._emit(
                chat_id,
                "error",
                {
                    "kind": "sdk_query_failed",
                    "message": str(exc)[:500],
                },
            )

    async def cancel(self, chat_id: str) -> None:
        async with self._lock:
            chat = self._chats.pop(chat_id, None)
        if chat is None:
            return
        try:
            await chat.client.interrupt()
        except Exception:  # noqa: BLE001
            pass
        await self._close_chat(chat)

    async def shutdown(self) -> None:
        async with self._lock:
            chats = list(self._chats.values())
            self._chats.clear()
        for chat in chats:
            await self._close_chat(chat)

    def has_live_chats(self) -> bool:
        """Phase 8d idle gate: True iff at least one chat has a live
        `ClaudeSDKClient` open. The bridge's main loop polls this; when
        it stays False for 15 min, the bridge exits cleanly so Sprites
        can hibernate the sandbox. Lock-free read — single-element
        atomic on CPython."""
        return len(self._chats) > 0

    # ── internals ────────────────────────────────────────────────────

    async def _spawn_locked(
        self,
        *,
        chat_id: str,
        resume: str | None,
        permission_mode: str | None = None,
    ) -> _LiveChat:
        """Build options, instantiate a `ClaudeSDKClient`, kick off the
        receive loop. Caller holds `self._lock`.

        `permission_mode` mapping (per `User.chat_permission_mode`):
          - "all_granted" → SDK `bypassPermissions` (no prompts; agent
            runs every tool unattended).
          - "ask"         → SDK `acceptEdits` (Edits auto-accept; Bash
            and similar trigger an in-line ask).
          - None / unknown → bridge default `acceptEdits`.
        """
        sdk_mode = _map_permission_mode(permission_mode) or "acceptEdits"
        env = self._credentials.env()
        prompt = _render_root_prompt(work_root=self._cwd)
        options = ClaudeAgentOptions(
            cwd=self._cwd,
            system_prompt=prompt,
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            permission_mode=sdk_mode,  # type: ignore[arg-type]
            resume=resume,
            env=env,
            include_partial_messages=True,
        )

        client = ClaudeSDKClient(options=options)
        await client.connect()
        chat = _LiveChat(
            chat_id=chat_id,
            client=client,
            last_active=time.monotonic(),
            sdk_permission_mode=sdk_mode,
        )
        chat.receive_task = asyncio.create_task(self._pump_messages(chat))
        return chat

    async def _pump_messages(self, chat: _LiveChat) -> None:
        """Drain the SDK's message stream, translate each into wire
        frames via `self._emit`."""
        try:
            async for message in chat.client.receive_messages():
                await self._handle_sdk_message(chat, message)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "bridge.chat_mux.pump_error",
                chat_id=chat.chat_id,
                error=str(exc)[:200],
            )
            await self._emit(
                chat.chat_id,
                "error",
                {"kind": "sdk_pump_failed", "message": str(exc)[:500]},
            )

    async def _handle_sdk_message(
        self, chat: _LiveChat, message: Any
    ) -> None:
        """SDK message → wire frame(s)."""
        # Live-streaming text deltas. With `include_partial_messages=True`
        # the SDK emits `StreamEvent`s containing the raw Anthropic API
        # stream events ahead of the final `AssistantMessage`. We forward
        # text/thinking deltas as live `assistant.delta` / `thinking`
        # frames so the FE can render them character-by-character.
        if isinstance(message, SDKStreamEvent):
            event = message.event or {}
            etype = event.get("type")
            if etype == "content_block_start":
                idx = event.get("index")
                cb = event.get("content_block") or {}
                if isinstance(idx, int) and cb.get("type") == "tool_use":
                    chat.inflight_tools[idx] = {
                        "id": cb.get("id") or "",
                        "name": cb.get("name") or "tool",
                        "input_json": "",
                        "input": cb.get("input") if isinstance(cb.get("input"), dict) else {},
                    }
            elif etype == "content_block_delta":
                idx = event.get("index")
                delta = event.get("delta") or {}
                dtype = delta.get("type")
                if dtype == "text_delta":
                    text = delta.get("text") or ""
                    if text:
                        await self._emit(
                            chat.chat_id, "assistant.delta", {"text": text}
                        )
                elif dtype == "input_json_delta" and isinstance(idx, int):
                    tool = chat.inflight_tools.get(idx)
                    if tool is not None:
                        partial = delta.get("partial_json") or ""
                        tool["input_json"] += partial
                # `thinking_delta` is intentionally NOT streamed: the
                # FE renders thinking as a single collapsible block,
                # not a live-typing element. Emit one consolidated
                # `thinking` frame from the AssistantMessage path
                # below instead.
            elif etype == "content_block_stop":
                idx = event.get("index")
                if isinstance(idx, int):
                    tool = chat.inflight_tools.pop(idx, None)
                    if tool is not None and tool.get("id"):
                        # Parse the accumulated input JSON. Fall back to
                        # whatever `input` came on `content_block_start`
                        # (SDK pre-populates the dict-shape for some
                        # tools).
                        import json as _json
                        try:
                            args = (
                                _json.loads(tool["input_json"])
                                if tool["input_json"]
                                else tool.get("input") or {}
                            )
                        except _json.JSONDecodeError:
                            args = tool.get("input") or {}
                        if not isinstance(args, dict):
                            args = {"value": args}
                        chat.streamed_tool_use_ids.add(tool["id"])
                        await self._emit(
                            chat.chat_id,
                            "tool.started",
                            {
                                "tool_use_id": tool["id"],
                                "tool_name": tool["name"],
                                "args": args,
                            },
                        )
            return
        if isinstance(message, SDKAssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    # Accumulate for the canonical `assistant.message`
                    # frame at turn close. We deliberately DON'T emit a
                    # delta here — the StreamEvent path above already
                    # streamed the same text incrementally. Emitting
                    # again would double-render in the FE.
                    chat.pending_assistant_text.append(block.text)
                elif isinstance(block, SDKThinkingBlock):
                    await self._emit(
                        chat.chat_id, "thinking", {"text": block.thinking}
                    )
                elif isinstance(block, ToolUseBlock):
                    # Skip if already streamed via the StreamEvent path
                    # (real-time, in-order with surrounding text). Falls
                    # through only when partial messages weren't enabled
                    # — defensive backstop.
                    if block.id in chat.streamed_tool_use_ids:
                        continue
                    await self._emit(
                        chat.chat_id,
                        "tool.started",
                        {
                            "tool_use_id": block.id,
                            "tool_name": block.name,
                            "args": dict(block.input)
                            if isinstance(block.input, dict)
                            else {"value": str(block.input)},
                        },
                    )
        elif isinstance(message, SDKUserMessage):
            # Tool results stream back as user-role messages from the
            # SDK's perspective (the agent's view of the world).
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    preview = ""
                    if isinstance(block.content, str):
                        preview = block.content
                    elif isinstance(block.content, list):
                        for sub in block.content:
                            if isinstance(sub, dict) and sub.get("type") == "text":
                                preview += str(sub.get("text", ""))
                    await self._emit(
                        chat.chat_id,
                        "tool.finished",
                        {
                            "tool_use_id": block.tool_use_id,
                            "is_error": bool(block.is_error),
                            "result_preview": preview[:10_000],
                        },
                    )
        elif isinstance(message, SDKResultMessage):
            # End-of-turn. Flush the accumulated assistant text as a
            # single `assistant.message` (the user-agent filter wants
            # the final block, not the deltas).
            if chat.pending_assistant_text:
                full_text = "".join(chat.pending_assistant_text)
                chat.pending_assistant_text.clear()
                await self._emit(
                    chat.chat_id, "assistant.message", {"text": full_text}
                )
            session_id = getattr(message, "session_id", None)
            if session_id:
                if not chat.started_emitted:
                    chat.claude_session_id = session_id
                    chat.started_emitted = True
                    await self._emit(
                        chat.chat_id,
                        "chat.started",
                        {"claude_session_id": session_id},
                    )
            usage = getattr(message, "usage", None)
            if usage is not None:
                await self._emit(
                    chat.chat_id,
                    "token.usage",
                    {
                        "input_delta": getattr(usage, "input_tokens", 0) or 0,
                        "output_delta": getattr(usage, "output_tokens", 0) or 0,
                        "cache_creation_delta": getattr(
                            usage, "cache_creation_input_tokens", 0
                        )
                        or 0,
                        "cache_read_delta": getattr(
                            usage, "cache_read_input_tokens", 0
                        )
                        or 0,
                    },
                )
            duration_ms = int(getattr(message, "duration_ms", 0) or 0)
            await self._emit(
                chat.chat_id,
                "result",
                {
                    "claude_session_id": session_id or chat.claude_session_id or "",
                    "duration_ms": duration_ms,
                    "is_error": bool(getattr(message, "is_error", False)),
                    "error": getattr(message, "result", None)
                    if getattr(message, "is_error", False)
                    else None,
                },
            )
        elif isinstance(message, SystemMessage):
            # SDK ack messages — not user-visible.
            return

    async def _evict_lru_locked(self) -> None:
        if not self._chats:
            return
        # LRU = lowest last_active.
        victim_id = min(
            self._chats.keys(), key=lambda cid: self._chats[cid].last_active
        )
        victim = self._chats.pop(victim_id)
        await self._emit(
            victim_id,
            "chat.evicted",
            {"reason": "lru_cap"},
        )
        await self._close_chat(victim)

    async def _close_chat(self, chat: _LiveChat) -> None:
        if chat.receive_task is not None:
            chat.receive_task.cancel()
            try:
                await chat.receive_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        try:
            await chat.client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def _map_permission_mode(mode: str | None) -> str | None:
    """User-facing → SDK PermissionMode mapping.
    `all_granted` → SDK `bypassPermissions` (no prompts).
    `ask`         → SDK `acceptEdits` (Edits auto-accept; Bash + similar
                    risky tools trigger an in-line ask).
    Any other value (or None) returns None — caller falls back to its
    spawn-time default."""
    if mode == "all_granted":
        return "bypassPermissions"
    if mode == "ask":
        return "acceptEdits"
    return None


def _render_root_prompt(*, work_root: str) -> str:
    """Slice 8 v1 system prompt — chats run at the repo root, can edit
    across any repo under `work_root`. Per-repo `RepoIntrospection` +
    in-repo `CLAUDE.md` rendering lands later (the existing
    `render_dev_agent_prompt` in agent_config is per-repo and doesn't
    fit the multi-repo cwd model)."""
    return (
        f"You are the dev agent inside a sandboxed Linux box. The user's repos are\n"
        f"checked out under `{work_root}/<owner>/<repo>/`. Use `Glob` / `Bash`\n"
        f"(`ls {work_root}`) to discover them.\n\n"
        f"## Working conventions\n"
        f"- Prefer the repo's own scripts (test / build / dev) over ad-hoc commands.\n"
        f"- Make small, reviewable diffs. Don't refactor unrelated code.\n"
        f"- When uncertain about user intent, ask in plain text and end your turn —\n"
        f"  the user (or their agent) will reply with the next message.\n"
        f"- Never `git push` or open a PR — that's a separate user-driven step.\n"
        f"- Never reach outside `{work_root}/` (no `cd /etc`, no `rm -rf /`).\n"
    )
