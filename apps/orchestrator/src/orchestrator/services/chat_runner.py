"""Chat lifecycle service — slice 8 §7 + Phase 8d.

`create_chat`, `add_follow_up`, `cancel_chat`. Bridges the HTTP route
layer (slice 8 §8) to the bridge↔WSS leg via `BridgeOwner.send`.

Phase 8d "fire and forget" model: the bridge daemon may be idle-exited
and the sprite hibernated when a user sends a message. We ALWAYS:
  1. Persist a `ChatTurn(status="queued")` so it's recoverable.
  2. Best-effort send via BridgeOwner (instant if bridge happens to
     still be connected).
  3. If `Sandbox.bridge_connected_at` looks stale (>90s) AND an
     `ensure_bridge_running` callback was provided, fire it — bridge
     dials home → on Hello, ws/bridge replays queued turns.
The chat creation never fails on "bridge_unavailable" anymore; the
queued turn + Hello replay path is canonical.

v1: chats run at `cwd=/work/`; no per-chat branch / worktree (slice 9
owns branching). Concurrency cap = `MAX_LIVE_CHATS_PER_SANDBOX` is
enforced bridge-side.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from agent_config.llm_provider import LLMProvider
from beanie import PydanticObjectId
from db.models import Chat, ChatTurn, Sandbox, User
from shared_models.wire_protocol import (
    CancelChat,
    OrchestratorToBridgeAdapter,
    UserMessage,
)

from orchestrator.services.bridge_owner import BridgeOwner
from orchestrator.services.bridge_session import BridgeSessionFleet
from orchestrator.services.user_agent.enhance import (
    EnhancedPrompt,
    enhance_prompt,
)

# Window beyond which we assume the bridge has idle-exited / the sprite
# has hibernated (matches the WSS rx-deadline + a small margin).
_BRIDGE_LIVE_WINDOW_S = 90

EnsureBridgeRunning = Callable[[Sandbox], Awaitable[None]]
"""Reconciler callback that mints a fresh BRIDGE_TOKEN and re-launches
the daemon. Idempotent if the bridge is already running."""

_logger = structlog.get_logger("chat_runner")


class ChatRunnerError(Exception):
    """Raised on user-visible failures (no live sandbox, etc.). Routes
    catch and translate to the appropriate HTTP status."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def _user_sandbox(user: User) -> Sandbox:
    if user.id is None:
        raise ChatRunnerError("invalid_user", "user id missing")
    sandbox = await Sandbox.find_one(
        Sandbox.user_id == user.id,
        {"status": {"$ne": "destroyed"}},
    )
    if sandbox is None:
        raise ChatRunnerError(
            "no_sandbox", "no live sandbox — provision one first"
        )
    if sandbox.status not in ("warm", "running"):
        raise ChatRunnerError(
            "sandbox_not_ready", f"sandbox is {sandbox.status}"
        )
    return sandbox


def _bridge_recently_connected(sandbox: Sandbox) -> bool:
    """Heuristic for "bridge daemon is alive and dialed in." Driven by
    `Sandbox.bridge_connected_at` which the WSS handler refreshes on
    every Hello. Stale → bridge has idle-exited (Phase 8d) or the
    sprite hibernated; we should kick a relaunch."""
    if sandbox.bridge_connected_at is None:
        return False
    connected_at = sandbox.bridge_connected_at
    if connected_at.tzinfo is None:
        connected_at = connected_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - connected_at < timedelta(
        seconds=_BRIDGE_LIVE_WINDOW_S
    )


async def _send_user_message_to_bridge(
    *,
    bridge_owner: BridgeOwner | BridgeSessionFleet,
    sandbox: Sandbox,
    chat: Chat,
    text: str,
    ensure_bridge_running: EnsureBridgeRunning | None,
    permission_mode: "str | None" = None,
) -> None:
    """Serialize + send a `UserMessage`. Best effort — never raises
    `bridge_unavailable`; the bridge's Hello-replay path picks up
    queued turns when it (re)dials."""
    if sandbox.id is None or chat.id is None:
        raise ChatRunnerError("invalid_state", "missing sandbox or chat id")
    # Pydantic Literal type narrows; Mongo / route layer pass the
    # validated value through.
    pm: Any = permission_mode if permission_mode in ("all_granted", "ask") else None
    msg = UserMessage(
        chat_id=str(chat.id),
        frame_id="",  # populated by BridgeOwner.send
        text=text,
        claude_session_id=chat.claude_session_id,
        permission_mode=pm,
    )
    raw = OrchestratorToBridgeAdapter.dump_python(msg, mode="json")
    if not isinstance(raw, dict):
        raise ChatRunnerError("invalid_state", "frame serialization failed")
    # Best-effort live delivery (works if bridge happens to be
    # connected). Outcome is informational; queued ChatTurn + Hello
    # replay is the canonical recovery path.
    await bridge_owner.send(str(sandbox.id), raw)
    if ensure_bridge_running is not None and not _bridge_recently_connected(sandbox):
        # Bridge looks idle — kick a relaunch. The reconciler call is
        # idempotent + cheap when the daemon is already running.
        try:
            await ensure_bridge_running(sandbox)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "chat_runner.ensure_bridge_running_failed",
                sandbox_id=str(sandbox.id),
                error=str(exc)[:200],
            )


async def create_chat(
    user: User,
    *,
    prompt: str,
    title: str | None = None,
    bridge_owner: BridgeOwner | BridgeSessionFleet,
    user_agent_provider: LLMProvider | None,
    ensure_bridge_running: EnsureBridgeRunning | None = None,
) -> tuple[Chat, ChatTurn, EnhancedPrompt | None]:
    """Create a chat, run optional user-agent enhancement, send the
    first `UserMessage` to the bridge. Phase 8d: never fails on
    bridge-unavailable — queued turn + Hello replay is the recovery
    path."""
    if user.id is None:
        raise ChatRunnerError("invalid_user", "user id missing")
    sandbox = await _user_sandbox(user)

    enhanced: EnhancedPrompt | None = None
    text_to_send = prompt
    if user.user_agent_enabled and user_agent_provider is not None:
        enhanced = await enhance_prompt(
            user.id,
            prompt,
            provider=user_agent_provider,
            model=user.user_agent_model,
        )
        text_to_send = enhanced.enhanced_text

    chat = Chat(
        user_id=user.id,
        sandbox_id=sandbox.id,
        title=title or _default_title(prompt),
        status="running",
        initial_prompt=prompt,
    )
    await chat.insert()
    assert chat.id is not None

    # Phase 8d: keep `status="queued"` until the bridge actually
    # processes it (transitioned by the ws/bridge handler on first
    # event for the chat). The Hello-replay scan picks up queued
    # turns to re-send if the bridge cycled before processing them.
    turn = ChatTurn(
        chat_id=chat.id,
        is_follow_up=False,
        prompt=prompt,
        enhanced_prompt=enhanced.enhanced_text if enhanced else None,
        status="queued",
    )
    await turn.insert()

    await _send_user_message_to_bridge(
        bridge_owner=bridge_owner,
        sandbox=sandbox,
        chat=chat,
        text=text_to_send,
        ensure_bridge_running=ensure_bridge_running,
        permission_mode=getattr(user, "chat_permission_mode", None),
    )

    return chat, turn, enhanced


async def add_follow_up(
    user: User,
    chat: Chat,
    *,
    prompt: str,
    bridge_owner: BridgeOwner | BridgeSessionFleet,
    user_agent_provider: LLMProvider | None,
    user_agent_loop: object | None = None,
    ensure_bridge_running: EnsureBridgeRunning | None = None,
) -> tuple[ChatTurn, EnhancedPrompt | None]:
    if user.id is None or chat.user_id != user.id:
        raise ChatRunnerError("not_owner", "not your chat")
    if chat.status in ("completed", "failed", "cancelled", "archived"):
        raise ChatRunnerError(
            "chat_closed", f"chat is {chat.status} — start a new one"
        )
    # User typing their own message cancels any pending user-agent
    # auto-reply timer for this chat (slice 8 Phase 8b override path).
    if user_agent_loop is not None and chat.id is not None:
        cancel = getattr(user_agent_loop, "cancel_pending_suggestion", None)
        if cancel is not None:
            try:
                result = cancel(chat.id)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "chat_runner.cancel_pending_suggestion_failed",
                    error=str(exc)[:200],
                )
    sandbox = await _user_sandbox(user)

    enhanced: EnhancedPrompt | None = None
    text_to_send = prompt
    if user.user_agent_enabled and user_agent_provider is not None:
        enhanced = await enhance_prompt(
            user.id,
            prompt,
            provider=user_agent_provider,
            model=user.user_agent_model,
        )
        text_to_send = enhanced.enhanced_text

    turn = ChatTurn(
        chat_id=chat.id if chat.id is not None else PydanticObjectId(),
        is_follow_up=True,
        prompt=prompt,
        enhanced_prompt=enhanced.enhanced_text if enhanced else None,
        status="queued",
    )
    await turn.insert()

    chat.status = "running"
    if chat.sandbox_id is None and sandbox.id is not None:
        # Backfill for chats created before Phase 8d — keeps the
        # Hello-replay scan correct.
        chat.sandbox_id = sandbox.id
    await chat.save()

    await _send_user_message_to_bridge(
        bridge_owner=bridge_owner,
        sandbox=sandbox,
        chat=chat,
        text=text_to_send,
        ensure_bridge_running=ensure_bridge_running,
        permission_mode=getattr(user, "chat_permission_mode", None),
    )
    return turn, enhanced


async def cancel_chat(
    user: User,
    chat: Chat,
    *,
    bridge_owner: BridgeOwner | BridgeSessionFleet,
) -> None:
    if chat.user_id != user.id:
        raise ChatRunnerError("not_owner", "not your chat")
    sandbox = await _user_sandbox(user)
    if chat.id is None or sandbox.id is None:
        return
    msg = CancelChat(chat_id=str(chat.id), frame_id="")
    raw = OrchestratorToBridgeAdapter.dump_python(msg, mode="json")
    if isinstance(raw, dict):
        await bridge_owner.send(str(sandbox.id), raw)
    chat.status = "cancelled"
    await chat.save()


def _default_title(prompt: str) -> str:
    """First line, truncated to 80 chars. The user-agent could rename
    this later via `Chat.save()` — out of scope for v1."""
    first = prompt.strip().split("\n", 1)[0].strip()
    if len(first) <= 80:
        return first or "New chat"
    return first[:77] + "..."
