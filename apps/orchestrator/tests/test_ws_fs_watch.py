"""Slice 6 fs-watch broker — auth, fan-out across two subscribers, coalescing."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import uvicorn
import websockets
from beanie import PydanticObjectId
from db import mongo
from db.models import Sandbox, Session, User
from orchestrator.app import app
from orchestrator.middleware.auth import SESSION_COOKIE_NAME
from orchestrator.services.fs_watcher import FsWatcher
from orchestrator.services.reconciliation import Reconciler
from orchestrator.services.sandbox_manager import SandboxManager
from sandbox_provider import FsEvent, MockSandboxProvider, SandboxHandle

TEST_DB_NAME = "octo_canvas_test"
HOST = "127.0.0.1"
PORT = 39051

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
async def fs_server() -> AsyncIterator[MockSandboxProvider]:
    if mongo._client is not None and mongo._db_name != TEST_DB_NAME:  # pyright: ignore[reportPrivateUsage]
        await mongo.disconnect()
    await mongo.connect(os.environ["MONGODB_URI"], database=TEST_DB_NAME)
    await mongo.drop_all_collections()
    await mongo.disconnect()
    await mongo.connect(os.environ["MONGODB_URI"], database=TEST_DB_NAME)

    provider = MockSandboxProvider()
    app.state.sandbox_manager = SandboxManager(provider=provider, redis=None)
    app.state.sandbox_provider = provider
    app.state.reconciler = Reconciler(provider)
    fs_watcher = FsWatcher(provider)
    app.state.fs_watcher = fs_watcher

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.02)
    else:
        raise RuntimeError("uvicorn did not start")

    try:
        yield provider
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(server_task, timeout=5.0)
        await fs_watcher.stop()
        await mongo.disconnect()


def _ws_url(sandbox_id: str) -> str:
    return f"ws://{HOST}:{PORT}/ws/web/sandboxes/{sandbox_id}/fs/watch"


def _cookie(session_id: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={session_id}"}


async def _create_sandbox(user_id: PydanticObjectId, provider: MockSandboxProvider) -> tuple[str, SandboxHandle]:
    handle = await provider.create(sandbox_id=str(user_id), labels=[])
    sandbox = Sandbox(
        user_id=user_id,
        provider_name="mock",
        provider_handle=dict(handle.payload),
        public_url="https://x",
        status="warm",
    )
    await sandbox.insert()
    assert sandbox.id is not None
    return str(sandbox.id), handle


async def test_fs_watch_rejects_wrong_user(fs_server: MockSandboxProvider) -> None:
    owner, _ = await _seed_user_session(github_user_id=10)
    _, other = await _seed_user_session(github_user_id=20)
    assert owner.id is not None
    sbx, _ = await _create_sandbox(owner.id, fs_server)
    async with websockets.connect(_ws_url(sbx), additional_headers=_cookie(other.session_id)) as ws:
        with contextlib.suppress(websockets.ConnectionClosed):
            await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert ws.close_code == 4003


async def test_fs_watch_emits_subscribed_then_events(fs_server: MockSandboxProvider) -> None:
    user, session = await _seed_user_session(github_user_id=30)
    assert user.id is not None
    sbx, handle = await _create_sandbox(user.id, fs_server)

    async with websockets.connect(_ws_url(sbx), additional_headers=_cookie(session.session_id)) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert first["type"] == "fswatch.subscribed"
        assert first["root_path"] == "/work"

        # Inject events via the mock test hook.
        fs_server.emit_fs_event(
            handle,
            FsEvent(path="/work/repo/a.txt", kind="create", is_dir=False, size=3, timestamp_ms=1),
        )
        ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert ev["type"] == "file.edit"
        assert ev["path"] == "/work/repo/a.txt"
        assert ev["kind"] == "create"


async def test_fs_watch_fans_out_to_two_subscribers(fs_server: MockSandboxProvider) -> None:
    user, session = await _seed_user_session(github_user_id=40)
    assert user.id is not None
    sbx, handle = await _create_sandbox(user.id, fs_server)

    async with (
        websockets.connect(_ws_url(sbx), additional_headers=_cookie(session.session_id)) as ws_a,
        websockets.connect(_ws_url(sbx), additional_headers=_cookie(session.session_id)) as ws_b,
    ):
        # Drain the subscribed-frames.
        await asyncio.wait_for(ws_a.recv(), timeout=2.0)
        await asyncio.wait_for(ws_b.recv(), timeout=2.0)

        # Give the second subscriber a tick to register on the watcher.
        await asyncio.sleep(0.05)

        fs_server.emit_fs_event(
            handle,
            FsEvent(path="/work/x.txt", kind="modify", is_dir=False, size=10, timestamp_ms=2),
        )
        a = json.loads(await asyncio.wait_for(ws_a.recv(), timeout=2.0))
        b = json.loads(await asyncio.wait_for(ws_b.recv(), timeout=2.0))
        assert a == b
        assert a["path"] == "/work/x.txt"


async def test_fs_watch_redis_pubsub_cross_instance(fs_server: MockSandboxProvider) -> None:
    """Simulates a second orchestrator instance publishing an event.

    Spins up a SECOND `FsWatcher` (with its own `instance_id`) sharing the
    same Redis. Publishes an event on its channel; the running app's
    watcher receives via Redis pub/sub and fans out to the connected web
    subscriber.
    """
    import os

    import redis.asyncio as redis_asyncio
    from orchestrator.services.fs_watcher import FsWatcher

    user, session = await _seed_user_session(github_user_id=60)
    assert user.id is not None
    sbx, handle = await _create_sandbox(user.id, fs_server)

    redis_url = os.environ["REDIS_URL"]
    second_redis: redis_asyncio.Redis = redis_asyncio.from_url(
        redis_url, decode_responses=True
    )
    second = FsWatcher(fs_server, redis=second_redis)

    # The running app's FsWatcher needs to be the redis-aware one too.
    # Replace the one set up by `fs_server` with a Redis-aware variant
    # for this test only.
    primary_redis: redis_asyncio.Redis = redis_asyncio.from_url(
        redis_url, decode_responses=True
    )
    primary = FsWatcher(fs_server, redis=primary_redis)
    await primary.start()
    app.state.fs_watcher = primary

    try:
        async with websockets.connect(
            _ws_url(sbx), additional_headers=_cookie(session.session_id)
        ) as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)  # subscribed
            # Other instance publishes (simulated by direct call).
            await second._publish(  # pyright: ignore[reportPrivateUsage]
                sbx,
                FsEvent(
                    path="/work/from-other-instance.txt",
                    kind="create",
                    is_dir=False,
                    size=7,
                    timestamp_ms=99,
                ),
            )
            ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert ev["type"] == "file.edit"
            assert ev["path"] == "/work/from-other-instance.txt"
            assert ev["kind"] == "create"
    finally:
        await primary.stop()
        await primary_redis.aclose()
        await second_redis.aclose()


async def test_fs_watch_coalesces_duplicate_events(fs_server: MockSandboxProvider) -> None:
    user, session = await _seed_user_session(github_user_id=50)
    assert user.id is not None
    sbx, handle = await _create_sandbox(user.id, fs_server)

    async with websockets.connect(_ws_url(sbx), additional_headers=_cookie(session.session_id)) as ws:
        await asyncio.wait_for(ws.recv(), timeout=2.0)  # subscribed
        # Three rapid duplicates within the coalesce window.
        for i in range(3):
            fs_server.emit_fs_event(
                handle,
                FsEvent(path="/work/a", kind="modify", is_dir=False, size=i, timestamp_ms=i),
            )
        # We expect exactly one frame; collect with a short timeout.
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert first["path"] == "/work/a"
        # Second recv should time out — only one frame got through.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ws.recv(), timeout=0.4)
