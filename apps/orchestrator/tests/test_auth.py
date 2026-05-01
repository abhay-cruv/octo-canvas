from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from pytest_mock import MockerFixture

from db.models import Session, User
from orchestrator.middleware.auth import SESSION_COOKIE_NAME
from orchestrator.routes import auth as auth_route


async def _seed_user_and_session() -> tuple[User, Session]:
    now = datetime.now(UTC)
    user = User(
        github_user_id=42,
        github_username="octocat",
        github_avatar_url="https://example.com/avatar.png",
        email="octocat@example.com",
        display_name="The Octocat",
        created_at=now,
        updated_at=now,
        last_signed_in_at=now,
    )
    await user.create()
    assert user.id is not None
    session = Session(
        session_id="seeded-session-id",
        user_id=user.id,
        expires_at=now + timedelta(days=1),
    )
    await session.create()
    return user, session


@pytest.mark.asyncio
async def test_session_returns_401_without_cookie(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/session")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_session_returns_user_with_valid_cookie(
    client: httpx.AsyncClient,
) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.get("/api/auth/session")
    assert response.status_code == 200
    body = response.json()
    assert body["github_username"] == "octocat"
    assert body["github_user_id"] == 42


@pytest.mark.asyncio
async def test_github_login_redirects_with_state_cookie(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/auth/github/login")
    assert response.status_code == 302
    assert "github.com/login/oauth/authorize" in response.headers["location"]
    assert "vibe_oauth_state" in response.cookies


@pytest.mark.asyncio
async def test_github_callback_rejects_state_mismatch(
    client: httpx.AsyncClient,
) -> None:
    client.cookies.set("vibe_oauth_state", "right")
    response = await client.get(
        "/api/auth/github/callback",
        params={"code": "abc", "state": "wrong"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_github_callback_creates_user_and_session(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    mock_client = AsyncMock()
    mock_client.fetch_token = AsyncMock(return_value={"access_token": "gh-token"})
    mock_client.aclose = AsyncMock()
    mocker.patch.object(auth_route, "_make_oauth_client", return_value=mock_client)

    profile: dict[str, Any] = {
        "id": 99,
        "login": "ada",
        "name": "Ada Lovelace",
        "avatar_url": "https://example.com/ada.png",
        "email": "ada@example.com",
    }

    async def fake_fetch_profile(_token: str) -> dict[str, Any]:
        return profile

    mocker.patch.object(
        auth_route, "_fetch_github_profile", side_effect=fake_fetch_profile
    )

    client.cookies.set("vibe_oauth_state", "shared-state")
    response = await client.get(
        "/api/auth/github/callback",
        params={"code": "real-code", "state": "shared-state"},
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith("/dashboard")
    assert SESSION_COOKIE_NAME in response.cookies

    user = await User.find_one(User.github_user_id == 99)
    assert user is not None
    assert user.github_username == "ada"
    assert user.email == "ada@example.com"

    sessions = await Session.find_all().to_list()
    assert len(sessions) == 1
    assert sessions[0].user_id == user.id


@pytest.mark.asyncio
async def test_logout_clears_session(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.post("/api/auth/logout")
    assert response.status_code == 204
    remaining = await Session.find_one(Session.session_id == session.session_id)
    assert remaining is None


@pytest.mark.asyncio
async def test_me_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_user_with_valid_session(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.get("/api/me")
    assert response.status_code == 200
    body = response.json()
    assert body["github_username"] == "octocat"
    assert body["email"] == "octocat@example.com"
