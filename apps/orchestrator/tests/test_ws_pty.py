"""Slice 6 PTY broker — auth, frame routing, Redis-backed reattach.

Spins up an in-process uvicorn (the orchestrator app) and a separate
fake-Sprites WS server. The Mock provider's `_pty_url` is pointed at the
fake server so the broker has somewhere real to dial.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import redis.asyncio as redis_asyncio
import uvicorn
import websockets
from beanie import PydanticObjectId
from db import mongo
from db.models import Sandbox, Session, User
from orchestrator.app import app
from orchestrator.middleware.auth import SESSION_COOKIE_NAME
from orchestrator.services.reconciliation import Reconciler
from orchestrator.services.sandbox_manager import SandboxManager
from sandbox_provider import MockSandboxProvider

TEST_DB_NAME = "octo_canvas_test"
HOST = "127.0.0.1"
ORCH_PORT = 39041
FAKE_SPRITES_PORT = 39042

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


class _FakeSprite:
    """Echo-back upstream that also emits a `session_info` JSON frame on
    connect and an `exit` frame on demand. Tracks the last received bytes
    so tests can assert."""

    def __init__(self) -> None:
        self.received_bytes: list[bytes] = []
        self.received_text: list[str] = []
        self.session_id = "sprite-sess-abc"

    async def handler(self, ws: websockets.ServerConnection) -> None:
        # Send session_info immediately so the broker caches the session id
        # and emits PtySessionInfo to the web client.
        await ws.send(
            json.dumps(
                {
                    "type": "session_info",
                    "session_id": self.session_id,
                    "command": "bash",
                    "created": 1,
                    "cols": 80,
                    "rows": 24,
                    "is_owner": True,
                    "tty": True,
                }
            )
        )
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    self.received_bytes.append(msg)
                    # Echo back so the test can verify forwarding.
                    await ws.send(msg)
                else:
                    self.received_text.append(msg)
                    if msg == "__exit__":
                        await ws.send(json.dumps({"type": "exit", "exit_code": 0}))
                        return
        except websockets.ConnectionClosed:
            return


@pytest_asyncio.fixture
async def pty_server() -> AsyncIterator[tuple[redis_asyncio.Redis, _FakeSprite, MockSandboxProvider]]:
    """Wire up Mongo, Redis, the orchestrator app, a fake Sprites WS server,
    and point the Mock provider at the fake server."""
    if mongo._client is not None and mongo._db_name != TEST_DB_NAME:  # pyright: ignore[reportPrivateUsage]
        await mongo.disconnect()
    await mongo.connect(os.environ["MONGODB_URI"], database=TEST_DB_NAME)
    await mongo.drop_all_collections()
    await mongo.disconnect()
    await mongo.connect(os.environ["MONGODB_URI"], database=TEST_DB_NAME)

    redis = redis_asyncio.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await redis.flushdb()  # type: ignore[misc]

    provider = MockSandboxProvider()
    provider._pty_url = f"ws://{HOST}:{FAKE_SPRITES_PORT}/exec"  # pyright: ignore[reportPrivateUsage]
    app.state.sandbox_manager = SandboxManager(provider=provider, redis=None)
    app.state.sandbox_provider = provider
    app.state.reconciler = Reconciler(provider)
    app.state.redis_handle = redis

    fake = _FakeSprite()
    fake_server = await websockets.serve(fake.handler, HOST, FAKE_SPRITES_PORT)

    config = uvicorn.Config(app, host=HOST, port=ORCH_PORT, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.02)
    else:
        raise RuntimeError("uvicorn did not start")

    try:
        yield redis, fake, provider
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(server_task, timeout=5.0)
        fake_server.close()
        await fake_server.wait_closed()
        await redis.flushdb()  # type: ignore[misc]
        await redis.aclose()
        await mongo.disconnect()


def _ws_url(sandbox_id: str, terminal_id: str) -> str:
    return f"ws://{HOST}:{ORCH_PORT}/ws/web/sandboxes/{sandbox_id}/pty/{terminal_id}"


def _cookie(session_id: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE_NAME}={session_id}"}


async def _create_sandbox(user_id: PydanticObjectId, provider: MockSandboxProvider) -> str:
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
    return str(sandbox.id)


# ── auth / ownership ─────────────────────────────────────────────────────


async def test_pty_rejects_missing_cookie(pty_server: tuple[redis_asyncio.Redis, _FakeSprite, MockSandboxProvider]) -> None:
    fake_id = str(PydanticObjectId())
    async with websockets.connect(_ws_url(fake_id, "t1")) as ws:
        with contextlib.suppress(websockets.ConnectionClosed):
            await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert ws.close_code == 4001


async def test_pty_rejects_wrong_user(pty_server: tuple[redis_asyncio.Redis, _FakeSprite, MockSandboxProvider]) -> None:
    _, _, provider = pty_server
    owner, _ = await _seed_user_session(github_user_id=10)
    _, other = await _seed_user_session(github_user_id=20)
    assert owner.id is not None
    sbx = await _create_sandbox(owner.id, provider)
    async with websockets.connect(_ws_url(sbx, "t1"), additional_headers=_cookie(other.session_id)) as ws:
        with contextlib.suppress(websockets.ConnectionClosed):
            await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert ws.close_code == 4003


async def test_pty_rejects_unknown_sandbox(pty_server: tuple[redis_asyncio.Redis, _FakeSprite, MockSandboxProvider]) -> None:
    _, session = await _seed_user_session(github_user_id=30)
    bogus = str(PydanticObjectId())
    async with websockets.connect(_ws_url(bogus, "t1"), additional_headers=_cookie(session.session_id)) as ws:
        with contextlib.suppress(websockets.ConnectionClosed):
            await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert ws.close_code == 4003


# ── happy path: bytes pump + session_info + Redis cache ──────────────────


async def test_pty_pumps_bytes_and_caches_session_id(
    pty_server: tuple[redis_asyncio.Redis, _FakeSprite, MockSandboxProvider],
) -> None:
    redis, fake, provider = pty_server
    user, session = await _seed_user_session(github_user_id=40)
    assert user.id is not None
    sbx = await _create_sandbox(user.id, provider)

    async with websockets.connect(
        _ws_url(sbx, "term-1"), additional_headers=_cookie(session.session_id)
    ) as ws:
        # First frame: PtySessionInfo (the broker translates Sprites'
        # session_info JSON into our wire shape).
        first = await asyncio.wait_for(ws.recv(), timeout=2.0)
        info = json.loads(first)
        assert info["type"] == "pty.session_info"
        assert info["sprites_session_id"] == "sprite-sess-abc"
        assert info["reattached"] is False

        # Send some stdin bytes; expect the echo back.
        await ws.send(b"echo hi\n")
        echoed = await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert echoed == b"echo hi\n"

        # Resize → forwarded as Sprites JSON.
        await ws.send(json.dumps({"type": "pty.resize", "cols": 120, "rows": 40}))
        # Give the upstream a tick to receive.
        await asyncio.sleep(0.05)

    # Redis caches the upstream session id, keyed by (sandbox, terminal).
    cached = await redis.get(f"pty:{sbx}:term-1")
    assert cached == "sprite-sess-abc"
    # Resize was forwarded.
    assert any('"type": "resize"' in t for t in fake.received_text)


async def test_pty_reattach_sets_attach_session_id(
    pty_server: tuple[redis_asyncio.Redis, _FakeSprite, MockSandboxProvider],
) -> None:
    redis, fake, provider = pty_server
    user, session = await _seed_user_session(github_user_id=50)
    assert user.id is not None
    sbx = await _create_sandbox(user.id, provider)
    # Pre-cache as if a previous connection had landed.
    await redis.set(f"pty:{sbx}:term-1", "sprite-prev", ex=3600)

    async with websockets.connect(
        _ws_url(sbx, "term-1"), additional_headers=_cookie(session.session_id)
    ) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        # Reattached path → flag flips true on the wire frame so the FE
        # can hide its 'opening shell…' state.
        assert first["type"] == "pty.session_info"
        assert first["reattached"] is True
