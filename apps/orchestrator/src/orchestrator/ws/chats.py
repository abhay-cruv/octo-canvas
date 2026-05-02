"""WebSocket handler for `/ws/web/chats/{chat_id}` — slice 8 Phase 8b.

Mirror of slice-5a's `/ws/web/tasks/{task_id}` against chat-keyed
event flow:
  1. Auth (session cookie → User) + ownership check (Chat.user_id).
  2. Read first frame (`Resume{after_seq}`).
  3. Replay persisted events from Mongo where `seq > after_seq`.
  4. Subscribe to `ChatFanout` for live frames; pump outbound.
  5. 30s server ping / 90s rx-deadline; backpressure-warning on
     subscriber-queue overflow.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from typing import cast

import structlog
from beanie import PydanticObjectId
from db.models import Chat, Session, User
from fastapi import APIRouter, WebSocket
from pydantic import ValidationError
from shared_models.wire_protocol import (
    BackpressureWarning,
    BridgeToOrchestrator,
    BridgeToOrchestratorAdapter,
    ClientPing,
    ClientPong,
    Pong,
    Resume,
    ServerPing,
    WebToOrchestratorAdapter,
)
from starlette.websockets import WebSocketDisconnect

from ..middleware.auth import SESSION_COOKIE_NAME
from ..services.event_store import replay_chat
from .chat_fanout import ChatFanout, ChatSubscription

router = APIRouter()
_logger = structlog.get_logger("ws.chats")

HEARTBEAT_INTERVAL_S = 30.0
HEARTBEAT_TIMEOUT_S = 90.0
QUEUE_SIZE = 1024


class _HeartbeatTimeoutError(Exception):
    pass


async def _resolve_user_for_ws(websocket: WebSocket) -> User | None:
    session_id = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    session = await Session.find_one(Session.session_id == session_id)
    if session is None:
        return None
    return await User.get(session.user_id)


def _get_fanout(websocket: WebSocket) -> ChatFanout:
    fanout = getattr(websocket.app.state, "chat_fanout", None)
    if fanout is None:
        raise RuntimeError("chat_fanout not initialized on app.state")
    return cast("ChatFanout", fanout)


@router.websocket("/ws/web/chats/{chat_id}")
async def chat_stream(websocket: WebSocket, chat_id: str) -> None:
    await websocket.accept()

    user = await _resolve_user_for_ws(websocket)
    if user is None:
        await websocket.close(code=4001, reason="unauthenticated")
        return

    try:
        oid = PydanticObjectId(chat_id)
    except Exception:  # noqa: BLE001
        await websocket.close(code=4004, reason="chat_not_found")
        return

    chat = await Chat.get(oid)
    if chat is None:
        await websocket.close(code=4004, reason="chat_not_found")
        return
    if chat.user_id != user.id:
        await websocket.close(code=4003, reason="forbidden")
        return

    await _run_session(websocket, oid)


async def _run_session(websocket: WebSocket, chat_id: PydanticObjectId) -> None:
    """Replay → live, with heartbeat + backpressure."""
    try:
        first_raw = await asyncio.wait_for(
            websocket.receive_json(), timeout=HEARTBEAT_TIMEOUT_S
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
    queue: asyncio.Queue[BridgeToOrchestrator] = asyncio.Queue(maxsize=QUEUE_SIZE)
    subscription = ChatSubscription(queue=queue)
    sub_token = await fanout.subscribe(chat_id, subscription)

    last_rx_at = asyncio.get_event_loop().time()
    last_seq_sent = first.after_seq
    last_bp_warned_seq = 0
    bp_warning_seq = 0

    async def send_chat(frame: BridgeToOrchestrator) -> None:
        await websocket.send_text(
            BridgeToOrchestratorAdapter.dump_json(frame).decode()
        )

    async def send_web_event(text: str) -> None:
        await websocket.send_text(text)

    async def pump_outbound() -> None:
        nonlocal last_seq_sent
        while True:
            payload = await queue.get()
            seq = getattr(payload, "seq", None)
            if isinstance(seq, int):
                if seq <= last_seq_sent:
                    continue
                last_seq_sent = seq
            await send_chat(payload)

    async def read_inbound() -> None:
        nonlocal last_rx_at, last_seq_sent
        while True:
            raw = await websocket.receive_json()
            last_rx_at = asyncio.get_event_loop().time()
            try:
                cmd = WebToOrchestratorAdapter.validate_python(raw)
            except ValidationError as exc:
                _logger.warning("ws.chats.bad_command", error=str(exc))
                continue
            if isinstance(cmd, ClientPing):
                await send_web_event(Pong(nonce=cmd.nonce).model_dump_json())
            elif isinstance(cmd, ClientPong):
                pass
            else:  # Resume
                events = await replay_chat(chat_id, after_seq=cmd.after_seq)
                last_seq_sent = cmd.after_seq
                for ev in events:
                    await send_chat(ev)
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
            await send_web_event(
                ServerPing(nonce=uuid.uuid4().hex).model_dump_json()
            )

    # Initial replay.
    try:
        replayed = await replay_chat(chat_id, after_seq=first.after_seq)
        for ev in replayed:
            await send_chat(ev)
            seq = getattr(ev, "seq", None)
            if isinstance(seq, int):
                last_seq_sent = seq
    except WebSocketDisconnect:
        await fanout.unsubscribe(chat_id, sub_token)
        return
    except Exception as exc:  # noqa: BLE001
        _logger.warning("ws.chats.replay_failed", error=str(exc))
        await fanout.unsubscribe(chat_id, sub_token)
        with suppress(Exception):
            await websocket.close(code=1011, reason="replay_failed")
        return

    async def backpressure_watch() -> None:
        nonlocal last_bp_warned_seq, bp_warning_seq
        while True:
            await asyncio.sleep(1.0)
            if subscription.last_dropped_seq > last_bp_warned_seq:
                last_bp_warned_seq = subscription.last_dropped_seq
                bp_warning_seq += 1
                with suppress(Exception):
                    await send_web_event(
                        BackpressureWarning(
                            seq=bp_warning_seq,
                            last_dropped_seq=last_bp_warned_seq,
                        ).model_dump_json()
                    )

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(pump_outbound(), name="ws-chat-out")
            tg.create_task(read_inbound(), name="ws-chat-in")
            tg.create_task(heartbeat(), name="ws-chat-hb")
            tg.create_task(backpressure_watch(), name="ws-chat-bp")
    except* WebSocketDisconnect:
        pass
    except* _HeartbeatTimeoutError:
        with suppress(Exception):
            await websocket.close(code=1011, reason="heartbeat_timeout")
    except* Exception as exc_group:  # noqa: BLE001
        _logger.warning("ws.chats.session_error", error=repr(exc_group))
        with suppress(Exception):
            await websocket.close(code=1011, reason="internal_error")
    finally:
        await fanout.unsubscribe(chat_id, sub_token)
