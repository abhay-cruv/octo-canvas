"""WS handler /ws/web/tasks/{task_id} — auth + replay + happy path.

Drives a real uvicorn server in-process so the WS handler runs on the same
event loop as the rest of the test (Beanie's AsyncMongoClient is loop-bound,
so the in-thread `TestClient.websocket_connect` shortcut doesn't work for
us — see the conftest comment).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
import redis.asyncio as redis_asyncio
import uvicorn
import websockets
from beanie import PydanticObjectId
from db import mongo
from db.models import Session, Task, User
from orchestrator.app import app
from orchestrator.middleware.auth import SESSION_COOKIE_NAME
from orchestrator.services.event_store import append_event
from orchestrator.ws.task_fanout import TaskFanout
from shared_models.wire_protocol import DebugEvent

TEST_DB_NAME = "octo_canvas_test"
HOST = "127.0.0.1"
PORT = 39031  # fixed; collision is unlikely on dev/CI

pytestmark = pytest.mark.asyncio


async def _seed_user_session(*, github_user_id: int = 7) -> tuple[User, Session]:
    now = datetime.now(UTC)
    user = User(
        github_user_id=github_user_id,
        github_username=f"u{github_user_id}",
        email=f"u{github_user_id}@e.com",
        last_signed_in_at=now,
        created_at=now,
        updated_at=now,
        github_access_token="t",
    )
    await user.create()
    assert user.id is not None
    session = Session(
        session_id=f"sess-{github_user_id}",
        user_id=user.id,
        expires_at=now + timedelta(days=1),
    )
    await session.create()
    return user, session


@pytest_asyncio.fixture
async def ws_server() -> AsyncIterator[redis_asyncio.Redis]:
    """Spin up a real uvicorn on the SAME event loop as the test, so Beanie's
    loop-bound Mongo client is happy. Tear it down cleanly between tests."""
    if mongo._client is not None and mongo._db_name != TEST_DB_NAME:  # pyright: ignore[reportPrivateUsage]
        await mongo.disconnect()
    await mongo.connect(os.environ["MONGODB_URI"], database=TEST_DB_NAME)
    await mongo.drop_all_collections()
    await mongo.disconnect()
    await mongo.connect(os.environ["MONGODB_URI"], database=TEST_DB_NAME)

    redis = redis_asyncio.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await redis.flushdb()  # type: ignore[misc]

    fanout = TaskFanout(redis)
    await fanout.start()
    app.state.task_fanout = fanout
    app.state.redis_handle = redis

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    # Wait for the server to be ready.
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.02)
    else:
        raise RuntimeError("uvicorn did not start in time")

    try:
        yield redis
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(server_task, timeout=5.0)
        await fanout.stop()
        await redis.flushdb()  # type: ignore[misc]
        await redis.aclose()
        await mongo.disconnect()


def _ws_url(task_id: str) -> str:
    return f"ws://{HOST}:{PORT}/ws/web/tasks/{task_id}"


def _cookie_header(session_id: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={session_id}"}


async def _expect_close(task_id: str, headers: dict[str, str] | None = None) -> int:
    """Connect, expect server-initiated close, return the close code."""
    async with websockets.connect(_ws_url(task_id), additional_headers=headers) as ws:
        try:
            await asyncio.wait_for(ws.recv(), timeout=2.0)
            raise AssertionError("expected server close, got a message")
        except websockets.ConnectionClosed as exc:
            return exc.code


async def test_ws_rejects_missing_cookie(ws_server: "redis_asyncio.Redis") -> None:
    fake_id = str(PydanticObjectId())
    code = await _expect_close(fake_id, headers=None)
    assert code == 4001


async def test_ws_rejects_wrong_user(ws_server: "redis_asyncio.Redis") -> None:
    owner, _ = await _seed_user_session(github_user_id=10)
    _, other_session = await _seed_user_session(github_user_id=20)
    task = Task(user_id=owner.id)  # type: ignore[arg-type]
    await task.insert()
    code = await _expect_close(str(task.id), headers=_cookie_header(other_session.session_id))
    assert code == 4003


async def test_ws_rejects_missing_task(ws_server: "redis_asyncio.Redis") -> None:
    _, session = await _seed_user_session(github_user_id=30)
    fake_id = str(PydanticObjectId())
    code = await _expect_close(fake_id, headers=_cookie_header(session.session_id))
    assert code == 4004


async def _connect(task_id: str, session_id: str) -> Any:
    return await websockets.connect(
        _ws_url(task_id), additional_headers=_cookie_header(session_id)
    )


async def test_ws_replay_happy_path(ws_server: "redis_asyncio.Redis") -> None:
    redis = ws_server
    user, session = await _seed_user_session(github_user_id=40)
    task = Task(user_id=user.id)  # type: ignore[arg-type]
    await task.insert()
    assert task.id is not None

    for i in range(3):
        await append_event(task.id, DebugEvent(seq=0, message=f"m{i}"), redis=redis)

    async with await _connect(str(task.id), session.session_id) as ws:
        await ws.send(json.dumps({"type": "resume", "after_seq": 0}))
        received = [json.loads(await ws.recv()) for _ in range(3)]

    assert [r["seq"] for r in received] == [1, 2, 3]
    assert [r["message"] for r in received] == ["m0", "m1", "m2"]
    assert all(r["type"] == "debug.event" for r in received)


async def test_ws_resume_skips_already_seen(ws_server: "redis_asyncio.Redis") -> None:
    redis = ws_server
    user, session = await _seed_user_session(github_user_id=50)
    task = Task(user_id=user.id)  # type: ignore[arg-type]
    await task.insert()
    assert task.id is not None
    for i in range(5):
        await append_event(task.id, DebugEvent(seq=0, message=f"m{i}"), redis=redis)

    async with await _connect(str(task.id), session.session_id) as ws:
        await ws.send(json.dumps({"type": "resume", "after_seq": 3}))
        first = json.loads(await ws.recv())
        second = json.loads(await ws.recv())
    assert first["seq"] == 4
    assert second["seq"] == 5


async def test_ws_live_event_after_resume(ws_server: "redis_asyncio.Redis") -> None:
    redis = ws_server
    user, session = await _seed_user_session(github_user_id=60)
    task = Task(user_id=user.id)  # type: ignore[arg-type]
    await task.insert()
    assert task.id is not None

    async with await _connect(str(task.id), session.session_id) as ws:
        await ws.send(json.dumps({"type": "resume", "after_seq": 0}))
        # No events yet — give the WS handler a moment to subscribe.
        await asyncio.sleep(0.2)
        await append_event(task.id, DebugEvent(seq=0, message="live"), redis=redis)
        ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    assert ev["type"] == "debug.event"
    assert ev["message"] == "live"


async def test_ws_ping_gets_pong(ws_server: "redis_asyncio.Redis") -> None:
    user, session = await _seed_user_session(github_user_id=70)
    task = Task(user_id=user.id)  # type: ignore[arg-type]
    await task.insert()

    async with await _connect(str(task.id), session.session_id) as ws:
        await ws.send(json.dumps({"type": "resume", "after_seq": 0}))
        await ws.send(json.dumps({"type": "ping", "nonce": "abc"}))
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    assert msg["type"] == "pong"
    assert msg["nonce"] == "abc"
