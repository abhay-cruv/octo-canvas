"""WebSocket handler for `/ws/web/tasks/{task_id}` — slice 5a.

Auth via session cookie (same `Session` lookup as REST). On accept:

  1. Receive `Resume{after_seq}` as the first frame.
  2. Stream every persisted event with `seq > after_seq` from Mongo.
  3. Subscribe to the local `TaskFanout` for live frames; pump them outbound.
  4. 30s `ping` / 90s rx-deadline heartbeat.
  5. Per-subscriber 1000-event queue; on overflow emit `BackpressureWarning`.

Close codes:

  4001 — auth (no/expired session)
  4003 — forbidden (user does not own this task)
  4004 — task not found
  4400 — protocol violation (bad first frame, schema mismatch)
  1011 — heartbeat timeout / internal error
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import structlog
from beanie import PydanticObjectId
from db.models import Session, Task, User
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from shared_models.wire_protocol import (
    BackpressureWarning,
    ClientPing,
    ClientPong,
    OrchestratorToWeb,
    OrchestratorToWebAdapter,
    Pong,
    Resume,
    ServerPing,
    WebToOrchestratorAdapter,
)

from ..middleware.auth import SESSION_COOKIE_NAME
from ..services.event_store import replay
from .task_fanout import Subscription

if TYPE_CHECKING:
    from .task_fanout import TaskFanout

_logger = structlog.get_logger("ws.web")

router = APIRouter()

QUEUE_SIZE = 1000
HEARTBEAT_INTERVAL_S = 30.0
HEARTBEAT_TIMEOUT_S = 90.0


async def _resolve_user_for_ws(websocket: WebSocket) -> User | None:
    """Cookie-based auth on the WS handshake. Returns None on any failure
    (caller closes 4001). Mirrors `middleware.auth._resolve_user`."""
    session_id = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    session = await Session.find_one(Session.session_id == session_id)
    if session is None:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        return None
    user = await User.get(session.user_id)
    return user


def _get_fanout(websocket: WebSocket) -> TaskFanout:
    fanout = getattr(websocket.app.state, "task_fanout", None)
    if fanout is None:
        raise RuntimeError("task_fanout not initialized on app.state")
    return cast("TaskFanout", fanout)


@router.websocket("/ws/web/tasks/{task_id}")
async def task_stream(websocket: WebSocket, task_id: str) -> None:
    # Per the WS protocol, application-level close codes (4xxx) only have
    # meaning AFTER accept(). If we close pre-accept, browsers and the
    # `websockets` lib see it as an HTTP 403 with no code, which is harder
    # to assert on cleanly. So: accept first, validate, close with code.
    await websocket.accept()

    user = await _resolve_user_for_ws(websocket)
    if user is None:
        await websocket.close(code=4001, reason="unauthenticated")
        return

    try:
        oid = PydanticObjectId(task_id)
    except Exception:
        await websocket.close(code=4004, reason="task_not_found")
        return

    task = await Task.get(oid)
    if task is None:
        await websocket.close(code=4004, reason="task_not_found")
        return
    if task.user_id != user.id:
        await websocket.close(code=4003, reason="forbidden")
        return

    await _run_session(websocket, oid)


async def _run_session(websocket: WebSocket, task_id: PydanticObjectId) -> None:
    """Drive replay → live mode under heartbeat + backpressure rules."""

    # First frame must be Resume.
    try:
        first_raw = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=HEARTBEAT_TIMEOUT_S,
        )
        first = WebToOrchestratorAdapter.validate_python(first_raw)
    except (TimeoutError, ValidationError, WebSocketDisconnect):
        with suppress(Exception):
            await websocket.close(code=4400, reason="bad_first_frame")
        return

    if not isinstance(first, Resume):
        with suppress(Exception):
            await websocket.close(code=4400, reason="expected_resume")
        return

    fanout = _get_fanout(websocket)
    queue: asyncio.Queue[OrchestratorToWeb] = asyncio.Queue(maxsize=QUEUE_SIZE)
    subscription = Subscription(queue=queue)
    sub_token = await fanout.subscribe(task_id, subscription)

    last_rx_at = asyncio.get_event_loop().time()
    last_seq_sent = first.after_seq
    last_bp_warned_seq = 0
    bp_warning_seq = 0

    async def send(frame: OrchestratorToWeb) -> None:
        await websocket.send_text(OrchestratorToWebAdapter.dump_json(frame).decode())

    async def pump_outbound() -> None:
        nonlocal last_seq_sent
        while True:
            payload = await queue.get()
            # Skip frames already covered by replay (Mongo-ordered).
            seq = getattr(payload, "seq", None)
            if isinstance(seq, int):
                if seq <= last_seq_sent:
                    continue
                last_seq_sent = seq
            await send(payload)

    async def read_inbound() -> None:
        nonlocal last_rx_at, last_seq_sent
        while True:
            raw = await websocket.receive_json()
            last_rx_at = asyncio.get_event_loop().time()
            try:
                cmd = WebToOrchestratorAdapter.validate_python(raw)
            except ValidationError as exc:
                _logger.warning("ws.web.bad_command", error=str(exc))
                continue
            if isinstance(cmd, ClientPing):
                await send(Pong(nonce=cmd.nonce))
            elif isinstance(cmd, ClientPong):
                pass  # rx timestamp already updated above
            else:  # Resume — only remaining variant of WebToOrchestrator
                # Late re-replay (rare). Stream events the FE missed.
                events = await replay(task_id, after_seq=cmd.after_seq)
                last_seq_sent = cmd.after_seq
                for ev in events:
                    await send(ev)
                    seq = getattr(ev, "seq", None)
                    if isinstance(seq, int):
                        last_seq_sent = seq

    async def heartbeat() -> None:
        nonlocal last_rx_at
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            now = asyncio.get_event_loop().time()
            if now - last_rx_at > HEARTBEAT_TIMEOUT_S:
                raise _HeartbeatTimeoutError
            await send(ServerPing(nonce=uuid.uuid4().hex))

    # Drain initial replay BEFORE entering live mode.
    try:
        replayed = await replay(task_id, after_seq=first.after_seq)
        for ev in replayed:
            await send(ev)
            seq = getattr(ev, "seq", None)
            if isinstance(seq, int):
                last_seq_sent = seq
    except WebSocketDisconnect:
        await fanout.unsubscribe(task_id, sub_token)
        return
    except Exception as exc:
        _logger.warning("ws.web.replay_failed", error=str(exc))
        await fanout.unsubscribe(task_id, sub_token)
        with suppress(Exception):
            await websocket.close(code=1011, reason="replay_failed")
        return

    async def backpressure_watch() -> None:
        """Poll the subscription's drop high-water mark; emit a
        BackpressureWarning whenever it advances past what we've already
        warned about."""
        nonlocal last_bp_warned_seq, bp_warning_seq
        while True:
            await asyncio.sleep(1.0)
            if subscription.last_dropped_seq > last_bp_warned_seq:
                last_bp_warned_seq = subscription.last_dropped_seq
                bp_warning_seq += 1
                with suppress(Exception):
                    await send(
                        BackpressureWarning(
                            seq=bp_warning_seq,
                            last_dropped_seq=last_bp_warned_seq,
                        )
                    )

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(pump_outbound(), name="ws-out")
            tg.create_task(read_inbound(), name="ws-in")
            tg.create_task(heartbeat(), name="ws-hb")
            tg.create_task(backpressure_watch(), name="ws-bp")
    except* WebSocketDisconnect:
        pass
    except* _HeartbeatTimeoutError:
        with suppress(Exception):
            await websocket.close(code=1011, reason="heartbeat_timeout")
    except* Exception as exc_group:
        _logger.warning("ws.web.session_error", error=repr(exc_group))
        with suppress(Exception):
            await websocket.close(code=1011, reason="internal_error")
    finally:
        await fanout.unsubscribe(task_id, sub_token)


class _HeartbeatTimeoutError(Exception):
    pass
