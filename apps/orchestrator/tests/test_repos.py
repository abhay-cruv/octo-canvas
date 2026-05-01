from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from githubkit.exception import RequestFailed
from pytest_mock import MockerFixture

from db.models import Repo, Session, User
from orchestrator.middleware.auth import SESSION_COOKIE_NAME
from orchestrator.routes import repos as repos_route


async def _seed_user_and_session(
    *,
    github_user_id: int = 42,
    token: str | None = "gh-token",
) -> tuple[User, Session]:
    now = datetime.now(UTC)
    user = User(
        github_user_id=github_user_id,
        github_username=f"u{github_user_id}",
        email=f"u{github_user_id}@e.com",
        last_signed_in_at=now,
        created_at=now,
        updated_at=now,
        github_access_token=token,
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


def _patch_user_client(mocker: MockerFixture, *, repo_id: int) -> MagicMock:
    fake_resp = MagicMock()
    fake_resp.parsed_data.id = repo_id
    fake_resp.parsed_data.full_name = "octo-org/repo"
    fake_resp.parsed_data.default_branch = "main"
    fake_resp.parsed_data.private = False

    fake_gh = MagicMock()
    fake_gh.rest.repos.async_get = AsyncMock(return_value=fake_resp)
    mocker.patch.object(repos_route, "user_client", return_value=fake_gh)
    return fake_gh


@pytest.mark.asyncio
async def test_list_connected_repos_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/repos")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_connected_repos_empty_then_seeded(
    client: httpx.AsyncClient,
) -> None:
    user, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    response = await client.get("/api/repos")
    assert response.status_code == 200
    assert response.json() == []

    assert user.id is not None
    await Repo(
        user_id=user.id,
        github_repo_id=10,
        full_name="octo/r1",
        default_branch="main",
        private=False,
    ).create()

    response = await client.get("/api/repos")
    body = response.json()
    assert len(body) == 1
    assert body[0]["full_name"] == "octo/r1"
    assert body[0]["clone_status"] == "pending"


@pytest.mark.asyncio
async def test_available_returns_reauth_when_token_missing(
    client: httpx.AsyncClient,
) -> None:
    _, session = await _seed_user_and_session(token=None)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.get("/api/repos/available")
    assert response.status_code == 403
    assert response.json()["detail"] == "github_reauth_required"


@pytest.mark.asyncio
async def test_available_clears_token_on_401(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    user, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    fake_response = MagicMock()
    fake_response.status_code = 401
    fake_gh = MagicMock()
    fake_gh.rest.repos.async_list_for_authenticated_user = AsyncMock(
        side_effect=RequestFailed(fake_response)
    )
    mocker.patch.object(repos_route, "user_client", return_value=fake_gh)

    response = await client.get("/api/repos/available")
    assert response.status_code == 403
    assert response.json()["detail"] == "github_reauth_required"

    refreshed = await User.get(user.id)
    assert refreshed is not None
    assert refreshed.github_access_token is None


@pytest.mark.asyncio
async def test_available_returns_paginated_with_is_connected(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    user, session = await _seed_user_and_session()
    assert user.id is not None
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    # Pre-connect one repo so we can verify is_connected=true
    await Repo(
        user_id=user.id,
        github_repo_id=10,
        full_name="octo/r1",
        default_branch="main",
        private=False,
    ).create()

    repo_a = MagicMock(
        id=10, full_name="octo/r1", default_branch="main", private=False, description=None
    )
    repo_b = MagicMock(
        id=20, full_name="octo/r2", default_branch="main", private=True, description="x"
    )
    fake_resp = MagicMock()
    fake_resp.parsed_data = [repo_a, repo_b]

    fake_gh = MagicMock()
    fake_gh.rest.repos.async_list_for_authenticated_user = AsyncMock(return_value=fake_resp)
    mocker.patch.object(repos_route, "user_client", return_value=fake_gh)

    response = await client.get("/api/repos/available?page=2&per_page=2")
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 2
    assert body["per_page"] == 2
    assert body["has_more"] is True  # 2 returned, per_page=2 → assume more
    assert {r["github_repo_id"]: r["is_connected"] for r in body["repos"]} == {
        10: True,
        20: False,
    }


@pytest.mark.asyncio
async def test_connect_returns_reauth_when_token_missing(
    client: httpx.AsyncClient,
) -> None:
    _, session = await _seed_user_and_session(token=None)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.post(
        "/api/repos/connect",
        json={"github_repo_id": 1, "full_name": "octo/r"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "github_reauth_required"


@pytest.mark.asyncio
async def test_connect_happy_path(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    _patch_user_client(mocker, repo_id=123)

    response = await client.post(
        "/api/repos/connect",
        json={"github_repo_id": 123, "full_name": "octo-org/repo"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["full_name"] == "octo-org/repo"
    assert body["clone_status"] == "pending"

    doc = await Repo.find_one(Repo.github_repo_id == 123)
    assert doc is not None
    assert doc.clone_path is None


@pytest.mark.asyncio
async def test_connect_allows_same_repo_for_different_users(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    """Two users connecting the same github_repo_id must both succeed.
    Previously blocked by a global unique index — fixed with the per-user
    compound key (multi-sandbox forward-compat per Plan.md §4)."""
    other, _ = await _seed_user_and_session(github_user_id=100)
    assert other.id is not None
    await Repo(
        user_id=other.id,
        github_repo_id=555,
        full_name="octo-org/repo",
        default_branch="main",
        private=False,
    ).create()

    _, session = await _seed_user_and_session(github_user_id=200)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    _patch_user_client(mocker, repo_id=555)

    response = await client.post(
        "/api/repos/connect",
        json={"github_repo_id": 555, "full_name": "octo-org/repo"},
    )
    assert response.status_code == 201
    rows = await Repo.find(Repo.github_repo_id == 555).to_list()
    assert len(rows) == 2  # one row per user


@pytest.mark.asyncio
async def test_connect_rejects_duplicate(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    user, session = await _seed_user_and_session()
    assert user.id is not None
    await Repo(
        user_id=user.id,
        github_repo_id=321,
        full_name="octo-org/repo",
        default_branch="main",
        private=False,
    ).create()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    _patch_user_client(mocker, repo_id=321)

    response = await client.post(
        "/api/repos/connect",
        json={"github_repo_id": 321, "full_name": "octo-org/repo"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_connect_rejects_id_mismatch(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    _patch_user_client(mocker, repo_id=999)  # GitHub returns id=999

    response = await client.post(
        "/api/repos/connect",
        json={"github_repo_id": 100, "full_name": "octo-org/repo"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_disconnect_removes_repo(client: httpx.AsyncClient) -> None:
    user, session = await _seed_user_and_session()
    assert user.id is not None
    doc = Repo(
        user_id=user.id,
        github_repo_id=42,
        full_name="octo/x",
        default_branch="main",
        private=False,
    )
    await doc.create()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    response = await client.delete(f"/api/repos/{doc.id}")
    assert response.status_code == 204
    remaining = await Repo.find_one(Repo.github_repo_id == 42)
    assert remaining is None


@pytest.mark.asyncio
async def test_disconnect_rejects_other_users_repo(
    client: httpx.AsyncClient,
) -> None:
    other, _ = await _seed_user_and_session(github_user_id=11)
    assert other.id is not None
    doc = Repo(
        user_id=other.id,
        github_repo_id=77,
        full_name="other/x",
        default_branch="main",
        private=False,
    )
    await doc.create()

    _, session = await _seed_user_and_session(github_user_id=22)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.delete(f"/api/repos/{doc.id}")
    assert response.status_code == 404
