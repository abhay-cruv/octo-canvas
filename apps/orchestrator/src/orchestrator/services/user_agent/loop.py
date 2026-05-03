"""User-agent loop — slice 8 Phase 8b.

Per-orchestrator-instance background subscriber on `chat:*:ua`. For each
"important" event the chat's user has user-agent enabled for:

- on `assistant.message` (final dev-agent block at end-of-turn): ask
  Haiku to `suggest_reply`. If `decision="suggest"`, emit a
  `UserAgentSuggestion` event onto the chat's transcript with a 10s
  override deadline; schedule a one-shot timer to send the suggested
  reply as a `UserMessage` after the deadline.
- on `result` / `error`: no-op for v1 (reserved for budget warnings,
  failure-mode reasoning).

The user can override during the window via:
- `POST /api/chats/{id}/messages` (their own reply replaces the
  pending suggestion — `cancel_pending_suggestion(chat_id)`)
- accept-now (FE button) → orchestrator sends the reply immediately
  + cancels the timer.

State is in-memory per instance — fine for v1 (the user agent is
stateless across events; per-chat memory lives in Mongo). Cross-
instance failover: if the owning instance dies mid-window, the user
just types their own reply.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from beanie import PydanticObjectId
from db.models import Chat, Sandbox, User
from shared_models.wire_protocol import (
    BridgeToOrchestratorAdapter,
    OrchestratorToBridgeAdapter,
    UserAgentSuggestion,
    UserMessage,
)

from orchestrator.services.bridge_owner import BridgeOwner
from orchestrator.services.bridge_session import BridgeSessionFleet
from orchestrator.services.event_store import (
    append_chat_event,
    chat_user_agent_channel_for,
)
from orchestrator.services.user_agent.providers.anthropic import AnthropicProvider
from orchestrator.services.user_agent.suggest import suggest_reply

if TYPE_CHECKING:
    from redis.asyncio.client import PubSub, Redis

_logger = structlog.get_logger("user_agent.loop")

OVERRIDE_WINDOW_S = 10.0


@dataclass
class _PendingSuggestion:
    """Tracks a scheduled auto-reply so the user can override (typing
    their own message OR accepting via the FE button) before it sends."""

    suggestion_id: str
    chat_id: PydanticObjectId
    suggested_reply: str
    timer: asyncio.Task[None]


class UserAgentLoop:
    def __init__(
        self,
        *,
        redis: "Redis | None",
        bridge_owner: BridgeOwner | BridgeSessionFleet,
        anthropic_api_key: str,
    ) -> None:
        self._redis = redis
        self._bridge_owner = bridge_owner
        self._anthropic_api_key = anthropic_api_key
        self._pubsub: PubSub | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stopped = False
        # chat_id (str) -> pending suggestion (most recent only; if a
        # newer one fires, the old timer is cancelled).
        self._pending: dict[str, _PendingSuggestion] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._redis is None:
            return
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await self._pubsub.psubscribe("chat:*:ua")  # type: ignore[misc]
        self._reader = asyncio.create_task(self._reader_loop(), name="user-agent-loop")
        _logger.info("user_agent_loop.started")

    async def stop(self) -> None:
        self._stopped = True
        if self._reader is not None:
            self._reader.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader
            self._reader = None
        if self._pubsub is not None:
            with suppress(Exception):
                await self._pubsub.aclose()  # type: ignore[misc]
            self._pubsub = None
        async with self._lock:
            for p in self._pending.values():
                p.timer.cancel()
            self._pending.clear()
        _logger.info("user_agent_loop.stopped")

    async def cancel_pending_suggestion(self, chat_id: PydanticObjectId) -> None:
        """Called when the user posts their own message — cancels any
        pending auto-reply timer for that chat."""
        cid = str(chat_id)
        async with self._lock:
            entry = self._pending.pop(cid, None)
        if entry is not None:
            entry.timer.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await entry.timer

    async def accept_pending_suggestion(
        self, chat_id: PydanticObjectId, suggestion_id: str
    ) -> str | None:
        """FE accept-now button: cancel the timer, return the reply
        text the timer would have sent. Caller forwards it as a normal
        UserMessage."""
        cid = str(chat_id)
        async with self._lock:
            entry = self._pending.get(cid)
            if entry is None or entry.suggestion_id != suggestion_id:
                return None
            self._pending.pop(cid, None)
        entry.timer.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await entry.timer
        return entry.suggested_reply

    async def _reader_loop(self) -> None:
        if self._pubsub is None:
            return
        try:
            while not self._stopped:
                msg = await self._pubsub.get_message(  # type: ignore[misc]
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg is None:
                    continue
                channel = msg["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8")
                if not isinstance(channel, str) or not channel.endswith(":ua"):
                    continue
                chat_id_str = channel.removeprefix("chat:").removesuffix(":ua")
                try:
                    chat_id = PydanticObjectId(chat_id_str)
                except Exception:  # noqa: BLE001
                    continue
                data = msg["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    payload = BridgeToOrchestratorAdapter.validate_json(data)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "user_agent_loop.bad_payload",
                        chat_id=chat_id_str,
                        error=str(exc),
                    )
                    continue
                payload_type = getattr(payload, "type", None)
                if payload_type != "assistant.message":
                    # `result` / `error` are reserved hooks for v1+;
                    # we only act on finalized assistant blocks.
                    continue
                text = getattr(payload, "text", "") or ""
                asyncio.create_task(self._handle_assistant(chat_id, text))
        except asyncio.CancelledError:
            return

    async def _handle_assistant(
        self, chat_id: PydanticObjectId, last_assistant_text: str
    ) -> None:
        """Called when a chat's user agent should review a finalized
        assistant block."""
        chat = await Chat.get(chat_id)
        if chat is None:
            return
        user = await User.get(chat.user_id)
        if user is None or not user.user_agent_enabled:
            return
        if user.user_agent_provider != "anthropic":
            # OpenAI / Gemini land later. Skip for now.
            return
        if not self._anthropic_api_key:
            return
        provider = AnthropicProvider(api_key=self._anthropic_api_key)
        try:
            decision = await suggest_reply(
                user.id if user.id is not None else PydanticObjectId(),
                last_assistant_text=last_assistant_text,
                provider=provider,
                model=user.user_agent_model,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("user_agent_loop.suggest_failed", error=str(exc)[:200])
            return
        if decision.decision != "suggest" or not decision.reply:
            return
        # Cancel any prior pending suggestion for this chat — only one
        # in flight at a time.
        await self.cancel_pending_suggestion(chat_id)
        suggestion_id = secrets.token_urlsafe(8)
        deadline = datetime.now(UTC) + timedelta(seconds=OVERRIDE_WINDOW_S)
        # Emit the UserAgentSuggestion event onto the chat's transcript.
        suggestion = UserAgentSuggestion(
            chat_id=str(chat_id),
            seq=0,  # rewritten by event_store
            suggestion_id=suggestion_id,
            suggested_reply=decision.reply,
            reason=decision.reason,
            override_deadline_at=deadline.isoformat(),
        )
        try:
            await append_chat_event(
                chat_id,
                suggestion,
                claude_session_id=chat.claude_session_id,
                redis=self._redis,
                user_agent_enabled=False,  # don't loop back into ourselves
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "user_agent_loop.emit_failed",
                chat_id=str(chat_id),
                error=str(exc)[:200],
            )
            return
        # Schedule the auto-send.
        timer = asyncio.create_task(
            self._auto_send_after_window(
                chat_id=chat_id,
                suggestion_id=suggestion_id,
                reply=decision.reply,
            )
        )
        async with self._lock:
            self._pending[str(chat_id)] = _PendingSuggestion(
                suggestion_id=suggestion_id,
                chat_id=chat_id,
                suggested_reply=decision.reply,
                timer=timer,
            )

    async def _auto_send_after_window(
        self, *, chat_id: PydanticObjectId, suggestion_id: str, reply: str
    ) -> None:
        try:
            await asyncio.sleep(OVERRIDE_WINDOW_S)
        except asyncio.CancelledError:
            return
        # Take ownership of this entry; bail if it's been replaced /
        # cancelled (we may have raced cancel_pending_suggestion).
        cid = str(chat_id)
        async with self._lock:
            entry = self._pending.get(cid)
            if entry is None or entry.suggestion_id != suggestion_id:
                return
            self._pending.pop(cid, None)
        # Locate the sandbox + send the auto-reply as a normal UserMessage.
        chat = await Chat.get(chat_id)
        if chat is None:
            return
        sandbox = await Sandbox.find_one(
            Sandbox.user_id == chat.user_id,
            {"status": {"$ne": "destroyed"}},
        )
        if sandbox is None or sandbox.id is None:
            return
        msg = UserMessage(
            chat_id=str(chat_id),
            frame_id=str(uuid.uuid4()),
            text=reply,
            claude_session_id=chat.claude_session_id,
        )
        raw = OrchestratorToBridgeAdapter.dump_python(msg, mode="json")
        if isinstance(raw, dict):
            await self._bridge_owner.send(str(sandbox.id), raw)
        _logger.info(
            "user_agent_loop.auto_sent",
            chat_id=cid,
            suggestion_id=suggestion_id,
        )
