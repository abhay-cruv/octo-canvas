import os
from collections.abc import AsyncIterator

import pytest_asyncio

os.environ.setdefault("ORCHESTRATOR_PORT", "3001")
os.environ.setdefault("WEB_BASE_URL", "http://localhost:5173")
os.environ.setdefault("ORCHESTRATOR_BASE_URL", "http://localhost:3001")
os.environ.setdefault("AUTH_SECRET", "test-secret")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "test-client-id")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/vibe_platform_test")

import httpx  # noqa: E402

from db import mongo  # noqa: E402
from orchestrator.app import app  # noqa: E402

TEST_DB_NAME = "vibe_platform_test"


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

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    await mongo.disconnect()
