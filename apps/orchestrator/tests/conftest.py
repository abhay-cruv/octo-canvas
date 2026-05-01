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
from beanie import init_beanie  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from db.models import Repo, Session, User  # noqa: E402
from orchestrator.app import app  # noqa: E402

TEST_DB_NAME = "vibe_platform_test"


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    motor_client: AsyncIOMotorClient[dict[str, object]] = AsyncIOMotorClient(
        os.environ["MONGODB_URI"]
    )
    for collection in (User, Session, Repo):
        await motor_client[TEST_DB_NAME][collection.Settings.name].delete_many({})
    await init_beanie(
        database=motor_client[TEST_DB_NAME],
        document_models=[User, Session, Repo],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
    motor_client.close()
