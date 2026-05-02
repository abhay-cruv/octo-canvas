"""User settings (user-agent toggle/provider/model) — slice 8 Phase 8b."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from beanie import PydanticObjectId
from db.models import Session, User
from orchestrator.middleware.auth import SESSION_COOKIE_NAME

pytestmark = pytest.mark.asyncio


async def _signed_in_user(client: httpx.AsyncClient) -> User:
    user = User(
        github_user_id=42,
        github_username="alice",
        email="alice@example.com",
        github_access_token="tok",
    )
    await user.insert()
    assert user.id is not None
    sess = Session(
        session_id="test-session",
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await sess.insert()
    client.cookies.set(SESSION_COOKIE_NAME, "test-session")
    return user


async def test_get_settings_returns_defaults(client: httpx.AsyncClient) -> None:
    await _signed_in_user(client)
    res = await client.get("/api/me/settings")
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "user_agent_enabled": True,
        "user_agent_provider": "anthropic",
        "user_agent_model": "claude-haiku-4-5",
    }


async def test_patch_toggles_user_agent_enabled(client: httpx.AsyncClient) -> None:
    user = await _signed_in_user(client)
    res = await client.patch(
        "/api/me/settings", json={"user_agent_enabled": False}
    )
    assert res.status_code == 200
    assert res.json()["user_agent_enabled"] is False
    # Persisted on the User doc.
    fresh = await User.get(user.id)
    assert fresh is not None
    assert fresh.user_agent_enabled is False


async def test_patch_partial_only_touches_provided_fields(
    client: httpx.AsyncClient,
) -> None:
    user = await _signed_in_user(client)
    res = await client.patch(
        "/api/me/settings", json={"user_agent_model": "claude-opus-4-7"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["user_agent_model"] == "claude-opus-4-7"
    assert body["user_agent_enabled"] is True  # untouched
    fresh = await User.get(user.id)
    assert fresh is not None
    assert fresh.user_agent_model == "claude-opus-4-7"


async def test_patch_invalid_provider_rejected(client: httpx.AsyncClient) -> None:
    await _signed_in_user(client)
    res = await client.patch(
        "/api/me/settings", json={"user_agent_provider": "made-up"}
    )
    # Pydantic validation fails the literal — FastAPI returns 422.
    assert res.status_code == 422


async def test_patch_empty_model_silently_ignored(
    client: httpx.AsyncClient,
) -> None:
    """`""` for `user_agent_model` is treated as "no change" — protects
    against the FE accidentally sending an empty string from a cleared
    input field."""
    user = await _signed_in_user(client)
    res = await client.patch(
        "/api/me/settings", json={"user_agent_model": "   "}
    )
    assert res.status_code == 200
    fresh = await User.get(user.id)
    assert fresh is not None
    assert fresh.user_agent_model == "claude-haiku-4-5"


async def test_settings_requires_auth(client: httpx.AsyncClient) -> None:
    # No cookie set.
    res = await client.get("/api/me/settings")
    assert res.status_code == 401


@pytest.fixture(autouse=True)
async def _cleanup(client: Any) -> Any:
    _ = client
    yield
    await User.delete_all()
    await Session.delete_all()
    _ = PydanticObjectId  # keep import live
