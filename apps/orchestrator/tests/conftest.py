import os
from collections.abc import AsyncIterator

import pytest_asyncio

os.environ.setdefault("ORCHESTRATOR_PORT", "3001")
os.environ.setdefault("WEB_BASE_URL", "http://localhost:5173")
os.environ.setdefault("ORCHESTRATOR_BASE_URL", "http://localhost:3001")
os.environ.setdefault("AUTH_SECRET", "test-secret")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "test-client-id")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/octo_canvas_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("SANDBOX_PROVIDER", "mock")

import httpx
import redis.asyncio as redis_asyncio
from db import mongo
from orchestrator.app import app
from orchestrator.services.sandbox_manager import SandboxManager
from sandbox_provider import MockSandboxProvider

TEST_DB_NAME = "octo_canvas_test"


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator["redis_asyncio.Redis"]:
    """Real Redis on the test DB (db 15). Flushes before AND after the test
    so any leftover keys/channels from a prior run don't leak."""
    client: redis_asyncio.Redis = redis_asyncio.from_url(  # pyright: ignore[reportUnknownMemberType]
        os.environ["REDIS_URL"], decode_responses=True
    )
    await client.flushdb()  # type: ignore[misc]
    try:
        yield client
    finally:
        await client.flushdb()  # type: ignore[misc]
        await client.aclose()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    # Connect → drop everything → reconnect so Beanie rebuilds indexes against
    # empty collections. (`delete_many({})` would leave stale indexes from
    # prior schemas in place, which then block valid writes.)
    if mongo._client is not None and mongo._db_name != TEST_DB_NAME:  # pyright: ignore[reportPrivateUsage]
        await mongo.disconnect()
    await mongo.connect(os.environ["MONGODB_URI"], database=TEST_DB_NAME)
    await mongo.drop_all_collections()
    await mongo.disconnect()
    await mongo.connect(os.environ["MONGODB_URI"], database=TEST_DB_NAME)

    # Inject a fresh Mock provider per test so state doesn't leak between
    # tests. ASGITransport doesn't run app.lifespan, so we wire the manager
    # onto app.state ourselves. Redis is None — slice 4 tolerates it.
    provider = MockSandboxProvider()
    manager = SandboxManager(provider=provider, redis=None)
    app.state.sandbox_manager = manager
    app.state.sandbox_provider = provider

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    await mongo.disconnect()
