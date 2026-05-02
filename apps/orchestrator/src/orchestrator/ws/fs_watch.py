"""WebSocket handler for `/ws/web/sandboxes/{sandbox_id}/fs/watch` (slice 6).

Auth via session cookie + ownership check. Subscribes to the per-sandbox
`FsWatcher`, pumps `FileEditEvent` JSON frames to the client. The first
frame after accept is `FsWatchSubscribed` so the FE has a deterministic
'connected' marker.

Close codes:
- 4001 — auth missing/expired
- 4003 — user does not own this sandbox
- 4500 — broker not initialized (server bug)
- 1011 — overflow / upstream error (FE reconnects)
- 1000 — clean close
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from beanie import PydanticObjectId
from db.models import Sandbox, Session, User
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sandbox_provider import SandboxHandle
from shared_models.wire_protocol import FileEditEvent, FsWatchSubscribed

from ..middleware.auth import SESSION_COOKIE_NAME

if TYPE_CHECKING:
    from ..services.fs_watcher import FsWatcher

_logger = structlog.get_logger("ws.fs_watch")

router = APIRouter()


async def _resolve_user(websocket: WebSocket) -> User | None:
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
    return await User.get(session.user_id)


async def _load_owned(sandbox_id: PydanticObjectId, user: User) -> Sandbox | None:
    doc = await Sandbox.get(sandbox_id)
    if doc is None or doc.user_id != user.id:
        return None
    if not doc.provider_handle:
        return None
    return doc


def _watcher(websocket: WebSocket) -> FsWatcher | None:
    return getattr(websocket.app.state, "fs_watcher", None)


@router.websocket("/ws/web/sandboxes/{sandbox_id}/fs/watch")
async def fs_watch_stream(websocket: WebSocket, sandbox_id: str) -> None:
    await websocket.accept()

    user = await _resolve_user(websocket)
    if user is None:
        await websocket.close(code=4001, reason="unauthenticated")
        return
    try:
        oid = PydanticObjectId(sandbox_id)
    except (ValueError, TypeError):
        await websocket.close(code=4003, reason="forbidden")
        return
    doc = await _load_owned(oid, user)
    if doc is None:
        await websocket.close(code=4003, reason="forbidden")
        return

    watcher = _watcher(websocket)
    if watcher is None:
        await websocket.close(code=4500, reason="broker_not_initialized")
        return

    handle = SandboxHandle(provider=doc.provider_name, payload=dict(doc.provider_handle or {}))
    sub = await watcher.subscribe(sandbox_id, handle)

    try:
        await websocket.send_text(
            FsWatchSubscribed(sandbox_id=sandbox_id, root_path="/work").model_dump_json()
        )

        # Drain client frames just to detect disconnect; slice 6 has no
        # client→server messages on this channel.
        async def _drain() -> None:
            try:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
            except WebSocketDisconnect:
                return

        async def _pump() -> None:
            while True:
                event = await sub.queue.get()
                if event is None:
                    if sub.stale:
                        # Overflow or upstream error — close so FE reconnects.
                        await websocket.close(code=1011, reason="overflow_or_upstream_error")
                    return
                frame = FileEditEvent(
                    path=event.path,
                    kind=event.kind,
                    is_dir=event.is_dir,
                    size=event.size,
                    timestamp_ms=event.timestamp_ms,
                )
                await websocket.send_text(frame.model_dump_json())

        drain_task = asyncio.create_task(_drain(), name=f"fswatch-drain-{sandbox_id}")
        pump_task = asyncio.create_task(_pump(), name=f"fswatch-pump-{sandbox_id}")
        try:
            _done, pending = await asyncio.wait(
                {drain_task, pump_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
                with suppress(asyncio.CancelledError):
                    await t
        finally:
            with suppress(Exception):
                await websocket.close()
    finally:
        await watcher.unsubscribe(sandbox_id, sub)
