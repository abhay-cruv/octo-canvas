from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from db.models import Repo, Session, User
from githubkit.exception import RequestFailed
from orchestrator.middleware.auth import SESSION_COOKIE_NAME
from orchestrator.routes import repos as repos_route
from pytest_mock import MockerFixture
from shared_models.introspection import RepoIntrospection


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


def _patch_introspection(
    mocker: MockerFixture,
    *,
    result: RepoIntrospection | None = None,
    raises: Exception | None = None,
) -> AsyncMock:
    """Stub `introspect_via_github` imported into the routes module.

    Default: returns a populated TS/pnpm fixture so connect tests don't need
    to care about Trees + Contents API mocking."""
    if result is None:
        result = RepoIntrospection(
            primary_language="TypeScript",
            package_manager="pnpm",
            test_command="pnpm test",
            build_command="pnpm build",
            dev_command="pnpm dev",
            detected_at=datetime.now(UTC),
        )
    mock = AsyncMock(side_effect=raises) if raises is not None else AsyncMock(return_value=result)
    mocker.patch.object(repos_route, "introspect_via_github", mock)
    return mock


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
    _patch_introspection(mocker)

    response = await client.post(
        "/api/repos/connect",
        json={"github_repo_id": 123, "full_name": "octo-org/repo"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["full_name"] == "octo-org/repo"
    assert body["clone_status"] == "pending"
    assert body["introspection"]["primary_language"] == "TypeScript"
    assert body["introspection"]["package_manager"] == "pnpm"
    assert body["introspection"]["test_command"] == "pnpm test"
    assert body["introspection"]["build_command"] == "pnpm build"

    doc = await Repo.find_one(Repo.github_repo_id == 123)
    assert doc is not None
    assert doc.clone_path is None
    assert doc.introspection_detected is not None
    assert doc.introspection_detected.primary_language == "TypeScript"
    assert doc.introspection_detected.dev_command == "pnpm dev"
    assert body["introspection"]["dev_command"] == "pnpm dev"
    assert body["introspection_detected"]["primary_language"] == "TypeScript"
    assert body["introspection_overrides"] is None


@pytest.mark.asyncio
async def test_connect_swallows_introspection_failure(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    """Non-401 introspection failures must not block the connection."""
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    _patch_user_client(mocker, repo_id=124)
    _patch_introspection(mocker, raises=RuntimeError("trees API exploded"))

    response = await client.post(
        "/api/repos/connect",
        json={"github_repo_id": 124, "full_name": "octo-org/repo"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["introspection"] is None
    doc = await Repo.find_one(Repo.github_repo_id == 124)
    assert doc is not None
    assert doc.introspection_detected is None
    assert doc.introspection_overrides is None


@pytest.mark.asyncio
async def test_connect_propagates_reauth_from_introspection(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    from github_integration import GithubReauthRequired

    user, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    _patch_user_client(mocker, repo_id=125)
    _patch_introspection(mocker, raises=GithubReauthRequired())

    response = await client.post(
        "/api/repos/connect",
        json={"github_repo_id": 125, "full_name": "octo-org/repo"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "github_reauth_required"
    refreshed = await User.get(user.id)
    assert refreshed is not None
    assert refreshed.github_access_token is None
    # The repo row was inserted before introspection; it stays.
    doc = await Repo.find_one(Repo.github_repo_id == 125)
    assert doc is not None


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
    _patch_introspection(mocker)

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


# --- Reintrospect endpoint --------------------------------------------------


async def _seed_repo(user: User, *, github_repo_id: int = 50) -> Repo:
    assert user.id is not None
    doc = Repo(
        user_id=user.id,
        github_repo_id=github_repo_id,
        full_name="octo/x",
        default_branch="main",
        private=False,
    )
    await doc.create()
    return doc


@pytest.mark.asyncio
async def test_reintrospect_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/repos/507f1f77bcf86cd799439011/reintrospect")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reintrospect_returns_reauth_when_token_missing(
    client: httpx.AsyncClient,
) -> None:
    user, session = await _seed_user_and_session(token=None)
    doc = await _seed_repo(user)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.post(f"/api/repos/{doc.id}/reintrospect")
    assert response.status_code == 403
    assert response.json()["detail"] == "github_reauth_required"


@pytest.mark.asyncio
async def test_reintrospect_404_for_other_users_repo(
    client: httpx.AsyncClient,
) -> None:
    other, _ = await _seed_user_and_session(github_user_id=300)
    doc = await _seed_repo(other)
    _, session = await _seed_user_and_session(github_user_id=301)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.post(f"/api/repos/{doc.id}/reintrospect")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reintrospect_happy_path(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    user, session = await _seed_user_and_session()
    doc = await _seed_repo(user)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    mocker.patch.object(repos_route, "user_client", return_value=MagicMock())
    result = RepoIntrospection(
        primary_language="Python",
        package_manager="uv",
        test_command="uv run pytest",
        build_command=None,
        dev_command=None,
        detected_at=datetime.now(UTC),
    )
    _patch_introspection(mocker, result=result)

    response = await client.post(f"/api/repos/{doc.id}/reintrospect")
    assert response.status_code == 200
    body = response.json()
    assert body["introspection"]["primary_language"] == "Python"
    assert body["introspection"]["package_manager"] == "uv"
    assert body["introspection"]["test_command"] == "uv run pytest"
    assert body["introspection"]["build_command"] is None

    refreshed = await Repo.get(doc.id)
    assert refreshed is not None
    assert refreshed.introspection_detected is not None
    assert refreshed.introspection_detected.primary_language == "Python"


@pytest.mark.asyncio
async def test_reintrospect_clears_token_on_reauth(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    from github_integration import GithubReauthRequired

    user, session = await _seed_user_and_session()
    doc = await _seed_repo(user)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    mocker.patch.object(repos_route, "user_client", return_value=MagicMock())
    _patch_introspection(mocker, raises=GithubReauthRequired())

    response = await client.post(f"/api/repos/{doc.id}/reintrospect")
    assert response.status_code == 403
    assert response.json()["detail"] == "github_reauth_required"
    refreshed = await User.get(user.id)
    assert refreshed is not None
    assert refreshed.github_access_token is None


# --- Introspection override endpoint ---------------------------------------


@pytest.mark.asyncio
async def test_overrides_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.patch(
        "/api/repos/507f1f77bcf86cd799439011/introspection", json={}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_overrides_404_for_other_users_repo(client: httpx.AsyncClient) -> None:
    other, _ = await _seed_user_and_session(github_user_id=400)
    doc = await _seed_repo(other)
    _, session = await _seed_user_and_session(github_user_id=401)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.patch(
        f"/api/repos/{doc.id}/introspection", json={"test_command": "x"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_overrides_set_then_clear(client: httpx.AsyncClient) -> None:
    user, session = await _seed_user_and_session()
    doc = await _seed_repo(user)
    # Seed a detected introspection so we can verify the merge.
    doc.introspection_detected = RepoIntrospection(
        primary_language="TypeScript",
        package_manager="pnpm",
        test_command="pnpm test",
        build_command="pnpm build",
        dev_command="pnpm dev",
        detected_at=datetime.now(UTC),
    )
    await doc.save()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    # Override two fields.
    response = await client.patch(
        f"/api/repos/{doc.id}/introspection",
        json={"test_command": "vitest --run", "dev_command": "vite --port 3000"},
    )
    assert response.status_code == 200
    body = response.json()
    # Effective merged values
    assert body["introspection"]["test_command"] == "vitest --run"
    assert body["introspection"]["dev_command"] == "vite --port 3000"
    assert body["introspection"]["build_command"] == "pnpm build"  # detected, not overridden
    # Detected and override fields are exposed separately
    assert body["introspection_detected"]["test_command"] == "pnpm test"
    assert body["introspection_overrides"]["test_command"] == "vitest --run"
    assert body["introspection_overrides"]["build_command"] is None

    # Mongo state
    refreshed = await Repo.get(doc.id)
    assert refreshed is not None
    assert refreshed.introspection_overrides is not None
    assert refreshed.introspection_overrides.test_command == "vitest --run"

    # Clear all overrides
    response = await client.patch(f"/api/repos/{doc.id}/introspection", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["introspection_overrides"] is None
    assert body["introspection"]["test_command"] == "pnpm test"  # back to detected
    refreshed = await Repo.get(doc.id)
    assert refreshed is not None
    assert refreshed.introspection_overrides is None


@pytest.mark.asyncio
async def test_overrides_visible_when_no_detection_yet(
    client: httpx.AsyncClient,
) -> None:
    """If detection hasn't run, overrides still persist and surface on the
    `introspection_overrides` field — but `introspection` (effective merged)
    stays None until detection runs."""
    user, session = await _seed_user_and_session()
    doc = await _seed_repo(user)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    response = await client.patch(
        f"/api/repos/{doc.id}/introspection",
        json={"test_command": "make test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["introspection"] is None  # no detected base to merge into
    assert body["introspection_detected"] is None
    assert body["introspection_overrides"]["test_command"] == "make test"


@pytest.mark.asyncio
async def test_overrides_rejects_unknown_package_manager(
    client: httpx.AsyncClient,
) -> None:
    user, session = await _seed_user_and_session()
    doc = await _seed_repo(user)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.patch(
        f"/api/repos/{doc.id}/introspection", json={"package_manager": "make"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reintrospect_preserves_overrides(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    """User overrides must survive a re-introspect — only `detected` is refreshed."""
    user, session = await _seed_user_and_session()
    doc = await _seed_repo(user)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    mocker.patch.object(repos_route, "user_client", return_value=MagicMock())

    # Set an override first.
    response = await client.patch(
        f"/api/repos/{doc.id}/introspection", json={"test_command": "make test"}
    )
    assert response.status_code == 200

    # Now re-introspect with new detected values.
    new_result = RepoIntrospection(
        primary_language="Rust",
        package_manager="cargo",
        test_command="cargo test",
        build_command="cargo build",
        dev_command="cargo run",
        detected_at=datetime.now(UTC),
    )
    _patch_introspection(mocker, result=new_result)

    response = await client.post(f"/api/repos/{doc.id}/reintrospect")
    assert response.status_code == 200
    body = response.json()
    # Detected refreshed
    assert body["introspection_detected"]["package_manager"] == "cargo"
    # Override survives
    assert body["introspection_overrides"]["test_command"] == "make test"
    # Effective merge: override wins for test_command, detected wins elsewhere
    assert body["introspection"]["test_command"] == "make test"
    assert body["introspection"]["build_command"] == "cargo build"
