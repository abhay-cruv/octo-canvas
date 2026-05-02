"""Bridge ↔ orchestrator WSS handler — slice 8 §5.

`/ws/bridge/{sandbox_id}` accepts the bridge's outgoing connection.
Auth = `Authorization: Bearer <BRIDGE_TOKEN>` matched (sha256 +
`hmac.compare_digest`) against `Sandbox.bridge_token_hash`. After
handshake:

- claim cross-instance ownership via `BridgeOwner` (close 4009 if
  another instance already holds it);
- spawn three concurrent loops in a `TaskGroup`:
  - `read_inbound`: parse `BridgeToOrchestrator` frames, persist via
    `event_store.append_chat_event`, ack periodically.
  - `pump_outbound`: read commands from a queue (filled by
    `BridgeOwner.send` on direct in-process appends + Redis pub/sub
    deliveries from non-owner instances), serialize, send.
  - `heartbeat`: 30s ping, 90s rx-deadline.

Mongo is canonical; Redis ring buffer + Sandbox.bridge_last_acked_seq_per_chat
let the bridge replay if a frame in flight gets dropped.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import structlog
from beanie import PydanticObjectId
from db.models import Chat, Sandbox
from fastapi import APIRouter, WebSocket
from pydantic import ValidationError
from shared_models.wire_protocol import (
    Ack,
    BridgeToOrchestrator,
    BridgeToOrchestratorAdapter,
    Goodbye,
    Hello,
    OrchestratorToBridge,
    OrchestratorToBridgeAdapter,
    Pong,
)
from starlette.websockets import WebSocketDisconnect, WebSocketState

from orchestrator.services.bridge_owner import BridgeOwner
from orchestrator.services.event_store import (
    ack_bridge_chat,
    append_chat_event,
)

router = APIRouter()
_logger = structlog.get_logger("ws_bridge")

_HEARTBEAT_PERIOD_S = 30.0
_RX_DEADLINE_S = 90.0
_ACK_BATCH_PERIOD_S = 1.0


def _now() -> datetime:
    return datetime.now(UTC)


def _bearer_token(authorization: str) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def _validate_bearer(sandbox_id_str: str, token: str | None) -> Sandbox | None:
    if not token:
        return None
    try:
        sb_id = PydanticObjectId(sandbox_id_str)
    except Exception:  # noqa: BLE001
        return None
    sandbox = await Sandbox.get(sb_id)
    if sandbox is None:
        return None
    if sandbox.status == "destroyed":
        return None
    if sandbox.bridge_token_hash is None:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(digest, sandbox.bridge_token_hash):
        return None
    return sandbox


class BridgeSession:
    """Per-bridge-connection state holder. Owns the outbound queue + the
    last-rx timestamp + per-chat ack tracking."""

    def __init__(self, sandbox: Sandbox, websocket: WebSocket) -> None:
        self.sandbox = sandbox
        self.websocket = websocket
        # Outbound: queue of pre-serialized JSON strings ready to send.
        self.outbound: asyncio.Queue[str] = asyncio.Queue(maxsize=1024)
        # Pending acks: chat_id -> highest seq we've persisted but not
        # yet acked. The ack pump drains this every second.
        self.pending_acks: dict[str, int] = {}
        self.last_rx_at = asyncio.get_event_loop().time()
        self.closed = asyncio.Event()
        self.stopped = False

    async def deliver(self, sandbox_id: str, frame: dict[str, Any]) -> None:
        """Called by `BridgeOwner` for any outbound command (direct
        in-process or Redis-routed). Serializes through the union
        adapter so we reject malformed commands before they hit the
        wire."""
        try:
            validated = OrchestratorToBridgeAdapter.validate_python(frame)
        except ValidationError as exc:
            _logger.warning(
                "ws_bridge.bad_outbound_frame",
                sandbox_id=sandbox_id,
                error=str(exc)[:200],
            )
            return
        payload = OrchestratorToBridgeAdapter.dump_json(validated).decode()
        try:
            self.outbound.put_nowait(payload)
        except asyncio.QueueFull:
            _logger.warning(
                "ws_bridge.outbound_overflow",
                sandbox_id=sandbox_id,
                frame_type=frame.get("type"),
            )


@router.websocket("/ws/bridge/{sandbox_id}")
async def bridge_ws(websocket: WebSocket, sandbox_id: str) -> None:
    # Accept first; close codes 4xxx are only meaningful post-accept
    # (lesson from slice 5a — the `websockets` lib otherwise sees a
    # bare 403 with no diagnostic).
    await websocket.accept()

    token = _bearer_token(websocket.headers.get("authorization", ""))
    sandbox = await _validate_bearer(sandbox_id, token)
    if sandbox is None:
        await websocket.close(code=4001, reason="unauthenticated")
        return

    # Cross-instance ownership claim.
    owner: BridgeOwner | None = getattr(websocket.app.state, "bridge_owner", None)
    if owner is None:
        # Without an owner singleton (i.e. lifespan didn't wire one)
        # we can still serve a single-instance dev orchestrator. Build
        # a transient one tied to the lifetime of this connection.
        owner = BridgeOwner(redis=None)
        await owner.start()
    session = BridgeSession(sandbox, websocket)
    claimed = await owner.claim(sandbox_id, session.deliver)
    if not claimed:
        await websocket.close(code=4009, reason="another instance owns this bridge")
        return

    # Persist connect-time fields on the sandbox doc.
    if sandbox.id is not None:
        await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
            {
                "$set": {
                    "bridge_connected_at": _now(),
                }
            }
        )

    _logger.info(
        "ws_bridge.connected",
        sandbox_id=sandbox_id,
        owner_instance=owner.instance_id,
    )

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_read_inbound(session))
            tg.create_task(_pump_outbound(session))
            tg.create_task(_heartbeat(session))
            tg.create_task(_ack_pump(session))
    except* WebSocketDisconnect:
        pass
    except* Exception as exc_group:  # noqa: BLE001
        _logger.warning(
            "ws_bridge.task_group_failed",
            sandbox_id=sandbox_id,
            error=str(exc_group)[:200],
        )
    finally:
        session.stopped = True
        session.closed.set()
        await owner.release(sandbox_id)
        if websocket.application_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except Exception:  # noqa: BLE001
                pass
        _logger.info("ws_bridge.disconnected", sandbox_id=sandbox_id)


async def _read_inbound(session: BridgeSession) -> None:
    """Receive bridge frames, validate, persist (event-class) or process
    (Hello/Goodbye/Pong)."""
    redis = getattr(session.websocket.app.state, "redis_handle", None)
    while not session.stopped:
        raw = await session.websocket.receive_text()
        session.last_rx_at = asyncio.get_event_loop().time()
        try:
            frame: BridgeToOrchestrator = BridgeToOrchestratorAdapter.validate_json(raw)
        except ValidationError as exc:
            _logger.warning(
                "ws_bridge.bad_inbound_frame",
                sandbox_id=str(session.sandbox.id),
                error=str(exc)[:200],
            )
            continue

        # Connection-class frames: don't persist; handle in-line.
        if isinstance(frame, Hello):
            if session.sandbox.id is not None:
                await Sandbox.find_one(Sandbox.id == session.sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
                    {"$set": {"bridge_version": frame.bridge_version}}
                )
            # ChatState replay convergence: for every chat in the
            # bridge's `last_acked_seq_per_chat`, tell the bridge our
            # current high-water mark. Bridge resends anything beyond.
            for chat_id_str, _bridge_seq in frame.last_acked_seq_per_chat.items():
                try:
                    chat_id = PydanticObjectId(chat_id_str)
                except Exception:  # noqa: BLE001
                    continue
                chat = await Chat.get(chat_id)
                if chat is None:
                    continue
                # Find our last persisted seq for this chat.
                last = await _last_seq_for_chat(chat_id)
                state_msg = {
                    "type": "bridge.chat_state",
                    "chat_id": chat_id_str,
                    "last_seen_seq": last,
                    "claude_session_id": chat.claude_session_id,
                }
                # Send via the same outbound queue so it serializes
                # cleanly behind any pending commands.
                await session.deliver(str(session.sandbox.id), state_msg)
            continue
        if isinstance(frame, Goodbye):
            session.stopped = True
            return
        if isinstance(frame, Pong):
            continue

        # Event-class: persist via event_store.
        chat_id_str = getattr(frame, "chat_id", None)
        if chat_id_str is None:
            continue
        try:
            chat_id = PydanticObjectId(chat_id_str)
        except Exception:  # noqa: BLE001
            continue
        chat = await Chat.get(chat_id)
        if chat is None:
            _logger.warning(
                "ws_bridge.frame_unknown_chat",
                sandbox_id=str(session.sandbox.id),
                chat_id=chat_id_str,
            )
            continue

        # Resolve user-agent enabled flag for the user (drives the
        # filtered fan-out).
        user_agent_enabled = await _user_agent_enabled(chat.user_id)
        claude_session_id = getattr(frame, "claude_session_id", None) or chat.claude_session_id

        event = await append_chat_event(
            chat_id,
            frame,
            claude_session_id=claude_session_id,
            redis=redis,
            user_agent_enabled=user_agent_enabled,
        )

        # Track for batched ack.
        if event.seq is not None:
            prev = session.pending_acks.get(chat_id_str, 0)
            if event.seq > prev:
                session.pending_acks[chat_id_str] = event.seq


async def _last_seq_for_chat(chat_id: PydanticObjectId) -> int:
    """High-water-mark for a chat's persisted events. 0 if none yet."""
    from db.models import AgentEvent

    cursor = (
        AgentEvent.find(AgentEvent.chat_id == chat_id)
        .sort(-AgentEvent.seq)  # type: ignore[arg-type]
        .limit(1)
    )
    rows = await cursor.to_list()
    if not rows:
        return 0
    return rows[0].seq


async def _user_agent_enabled(user_id: PydanticObjectId) -> bool:
    """Read `User.user_agent_enabled` for the routing decision in
    `append_chat_event`. Cached query is fine for v1; if this becomes
    hot we can cache locally with TTL."""
    from db.models import User

    user = await User.get(user_id)
    if user is None:
        return False
    return user.user_agent_enabled


async def _pump_outbound(session: BridgeSession) -> None:
    while not session.stopped:
        payload = await session.outbound.get()
        await session.websocket.send_text(payload)


async def _heartbeat(session: BridgeSession) -> None:
    """30s ping; 90s rx-deadline → close."""
    while not session.stopped:
        await asyncio.sleep(_HEARTBEAT_PERIOD_S)
        if asyncio.get_event_loop().time() - session.last_rx_at > _RX_DEADLINE_S:
            try:
                await session.websocket.close(code=4000, reason="rx_deadline")
            except Exception:  # noqa: BLE001
                pass
            return
        # Send a Ping.
        try:
            from shared_models.wire_protocol import BridgePing

            payload = OrchestratorToBridgeAdapter.dump_json(BridgePing()).decode()
            session.outbound.put_nowait(payload)
        except (ImportError, asyncio.QueueFull):
            pass


async def _ack_pump(session: BridgeSession) -> None:
    """Drain `pending_acks` every second. Sends one `Ack` frame per
    chat that accumulated events; updates `Sandbox.bridge_last_acked_seq_per_chat`."""
    while not session.stopped:
        await asyncio.sleep(_ACK_BATCH_PERIOD_S)
        if not session.pending_acks:
            continue
        snapshot = dict(session.pending_acks)
        session.pending_acks.clear()
        for chat_id_str, seq in snapshot.items():
            ack = Ack(chat_id=chat_id_str, ack_seq=seq)
            try:
                payload = OrchestratorToBridgeAdapter.dump_json(ack).decode()
                session.outbound.put_nowait(payload)
            except asyncio.QueueFull:
                # Re-queue this and bail out of the batch.
                session.pending_acks[chat_id_str] = max(
                    session.pending_acks.get(chat_id_str, 0), seq
                )
                break
            try:
                chat_id = PydanticObjectId(chat_id_str)
            except Exception:  # noqa: BLE001
                continue
            if session.sandbox.id is None:
                continue
            await ack_bridge_chat(session.sandbox.id, chat_id, seq)
