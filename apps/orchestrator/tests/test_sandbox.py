from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from beanie import PydanticObjectId
from db.models import Sandbox, Session, User
from orchestrator.app import app
from orchestrator.middleware.auth import SESSION_COOKIE_NAME
from orchestrator.services.sandbox_manager import (
    IllegalSandboxTransitionError,
    SandboxManager,
)
from pytest_mock import MockerFixture
from sandbox_provider import MockSandboxProvider, SandboxHandle, SpritesError


async def _seed_user_and_session(
    *,
    github_user_id: int = 42,
) -> tuple[User, Session]:
    now = datetime.now(UTC)
    user = User(
        github_user_id=github_user_id,
        github_username=f"u{github_user_id}",
        email=f"u{github_user_id}@e.com",
        last_signed_in_at=now,
        created_at=now,
        updated_at=now,
        github_access_token="gh-token",
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


def _manager() -> SandboxManager:
    manager = app.state.sandbox_manager
    assert isinstance(manager, SandboxManager)
    return manager


def _mock_provider() -> MockSandboxProvider:
    provider = app.state.sandbox_provider
    assert isinstance(provider, MockSandboxProvider)
    return provider


# ── Auth + listing ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/sandboxes")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_empty_then_after_create(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    response = await client.get("/api/sandboxes")
    assert response.status_code == 200
    assert response.json() == []

    response = await client.post("/api/sandboxes")
    assert response.status_code == 200
    body = response.json()
    # MockSandboxProvider returns `warm` immediately after create with a
    # synthetic public URL.
    assert body["status"] == "warm"
    assert body["public_url"].startswith("https://vibe-sbx-")
    assert body["provider_name"] == "mock"
    assert body["reset_count"] == 0
    assert body["spawned_at"] is not None

    response = await client.get("/api/sandboxes")
    assert len(response.json()) == 1


# ── get_or_create idempotency + post-destroy fresh-doc rule ────────────────


@pytest.mark.asyncio
async def test_create_is_idempotent(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    first = (await client.post("/api/sandboxes")).json()
    second = (await client.post("/api/sandboxes")).json()
    assert first["id"] == second["id"]


@pytest.mark.asyncio
async def test_create_after_destroy_returns_new_id(
    client: httpx.AsyncClient,
) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    first = (await client.post("/api/sandboxes")).json()
    await client.post(f"/api/sandboxes/{first['id']}/destroy")

    second = (await client.post("/api/sandboxes")).json()
    assert second["id"] != first["id"]
    assert second["status"] == "warm"
    sandboxes = (await client.get("/api/sandboxes")).json()
    assert len(sandboxes) == 2
    by_status = {s["id"]: s["status"] for s in sandboxes}
    assert by_status[first["id"]] == "destroyed"
    assert by_status[second["id"]] == "warm"


@pytest.mark.asyncio
async def test_create_502_on_provider_failure_marks_failed(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    mocker.patch.object(
        _manager()._provider,  # pyright: ignore[reportPrivateUsage]
        "create",
        AsyncMock(side_effect=SpritesError("boom", retriable=False)),
    )

    response = await client.post("/api/sandboxes")
    assert response.status_code == 502

    docs = (await client.get("/api/sandboxes")).json()
    assert len(docs) == 1
    assert docs[0]["status"] == "failed"
    assert docs[0]["failure_reason"] == "boom"


# ── Wake ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wake_forces_running(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    sandbox = (await client.post("/api/sandboxes")).json()
    handle = SandboxHandle(provider="mock", payload={"name": f"vibe-sbx-{sandbox['id']}"})
    _mock_provider()._force_cold(handle)  # simulate Sprites idle-hibernation

    response = await client.post(f"/api/sandboxes/{sandbox['id']}/wake")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["last_active_at"] is not None


@pytest.mark.asyncio
async def test_wake_404_for_other_users_sandbox(
    client: httpx.AsyncClient,
) -> None:
    other, _ = await _seed_user_and_session(github_user_id=11)
    assert other.id is not None
    other_doc = Sandbox(user_id=other.id, provider_name="mock")
    await other_doc.create()

    _, session = await _seed_user_and_session(github_user_id=22)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.post(f"/api/sandboxes/{other_doc.id}/wake")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_wake_409_when_destroyed(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    sandbox = (await client.post("/api/sandboxes")).json()
    await client.post(f"/api/sandboxes/{sandbox['id']}/destroy")

    response = await client.post(f"/api/sandboxes/{sandbox['id']}/wake")
    assert response.status_code == 409


# ── Pause ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pause_transitions_to_cold(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    sandbox = (await client.post("/api/sandboxes")).json()
    # Sprite is `warm` after create; wake first to confirm pause works from
    # any alive state.
    await client.post(f"/api/sandboxes/{sandbox['id']}/wake")

    response = await client.post(f"/api/sandboxes/{sandbox['id']}/pause")
    assert response.status_code == 200
    assert response.json()["status"] == "cold"


@pytest.mark.asyncio
async def test_pause_idempotent_on_cold(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    sandbox = (await client.post("/api/sandboxes")).json()
    await client.post(f"/api/sandboxes/{sandbox['id']}/pause")
    response = await client.post(f"/api/sandboxes/{sandbox['id']}/pause")
    assert response.status_code == 200
    assert response.json()["status"] == "cold"


@pytest.mark.asyncio
async def test_pause_409_from_destroyed(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    sandbox = (await client.post("/api/sandboxes")).json()
    await client.post(f"/api/sandboxes/{sandbox['id']}/destroy")

    response = await client.post(f"/api/sandboxes/{sandbox['id']}/pause")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_pause_404_for_other_users_sandbox(client: httpx.AsyncClient) -> None:
    other, _ = await _seed_user_and_session(github_user_id=11)
    assert other.id is not None
    other_doc = Sandbox(user_id=other.id, provider_name="mock")
    await other_doc.create()

    _, session = await _seed_user_and_session(github_user_id=22)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.post(f"/api/sandboxes/{other_doc.id}/pause")
    assert response.status_code == 404


# ── Refresh ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_resyncs_status(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    sandbox = (await client.post("/api/sandboxes")).json()
    assert sandbox["status"] == "warm"

    handle = SandboxHandle(provider="mock", payload={"name": f"vibe-sbx-{sandbox['id']}"})
    _mock_provider()._force_cold(handle)  # Sprites went idle on its own

    response = await client.post(f"/api/sandboxes/{sandbox['id']}/refresh")
    assert response.status_code == 200
    assert response.json()["status"] == "cold"


@pytest.mark.asyncio
async def test_refresh_is_no_op_for_terminal_states(
    client: httpx.AsyncClient,
) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    sandbox = (await client.post("/api/sandboxes")).json()
    await client.post(f"/api/sandboxes/{sandbox['id']}/destroy")

    response = await client.post(f"/api/sandboxes/{sandbox['id']}/refresh")
    assert response.status_code == 200
    assert response.json()["status"] == "destroyed"


# ── Reset ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_rotates_handle_and_increments_count(
    client: httpx.AsyncClient,
) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    sandbox = (await client.post("/api/sandboxes")).json()
    sandbox_id = sandbox["id"]

    original = await Sandbox.get(PydanticObjectId(sandbox_id))
    assert original is not None
    original_handle_id = original.provider_handle.get("id")
    assert sandbox["reset_count"] == 0

    reset = (await client.post(f"/api/sandboxes/{sandbox_id}/reset")).json()
    assert reset["id"] == sandbox_id  # same Sandbox doc
    assert reset["status"] == "warm"
    assert reset["reset_count"] == 1
    assert reset["last_reset_at"] is not None

    refreshed = await Sandbox.get(PydanticObjectId(sandbox_id))
    assert refreshed is not None
    new_handle_id = refreshed.provider_handle.get("id")
    assert new_handle_id and new_handle_id != original_handle_id

    reset2 = (await client.post(f"/api/sandboxes/{sandbox_id}/reset")).json()
    assert reset2["reset_count"] == 2


@pytest.mark.asyncio
async def test_reset_409_from_destroyed(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    sandbox = (await client.post("/api/sandboxes")).json()
    await client.post(f"/api/sandboxes/{sandbox['id']}/destroy")

    response = await client.post(f"/api/sandboxes/{sandbox['id']}/reset")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_reset_works_from_failed(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    real_create = _manager()._provider.create  # pyright: ignore[reportPrivateUsage]
    mocker.patch.object(
        _manager()._provider,  # pyright: ignore[reportPrivateUsage]
        "create",
        AsyncMock(side_effect=SpritesError("boom", retriable=False)),
    )
    response = await client.post("/api/sandboxes")
    assert response.status_code == 502

    docs = (await client.get("/api/sandboxes")).json()
    assert docs[0]["status"] == "failed"

    mocker.patch.object(
        _manager()._provider,  # pyright: ignore[reportPrivateUsage]
        "create",
        real_create,
    )
    response = await client.post(f"/api/sandboxes/{docs[0]['id']}/reset")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warm"
    assert body["reset_count"] == 1
    assert body["failure_reason"] is None


@pytest.mark.asyncio
async def test_reset_calls_destroy_then_create(
    client: httpx.AsyncClient, mocker: MockerFixture
) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    sandbox = (await client.post("/api/sandboxes")).json()

    destroy_spy = mocker.spy(
        _manager()._provider,  # pyright: ignore[reportPrivateUsage]
        "destroy",
    )
    create_spy = mocker.spy(
        _manager()._provider,  # pyright: ignore[reportPrivateUsage]
        "create",
    )
    response = await client.post(f"/api/sandboxes/{sandbox['id']}/reset")
    assert response.status_code == 200
    assert destroy_spy.call_count == 1
    assert create_spy.call_count == 1


# ── Destroy ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_destroy_from_warm(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    sandbox = (await client.post("/api/sandboxes")).json()

    response = await client.post(f"/api/sandboxes/{sandbox['id']}/destroy")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "destroyed"
    assert body["destroyed_at"] is not None
    assert body["public_url"] is None


@pytest.mark.asyncio
async def test_destroy_idempotent(client: httpx.AsyncClient) -> None:
    _, session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    sandbox = (await client.post("/api/sandboxes")).json()

    first = (await client.post(f"/api/sandboxes/{sandbox['id']}/destroy")).json()
    assert first["status"] == "destroyed"
    second = (await client.post(f"/api/sandboxes/{sandbox['id']}/destroy")).json()
    assert second["status"] == "destroyed"
    assert second["destroyed_at"] == first["destroyed_at"]


@pytest.mark.asyncio
async def test_two_user_isolation(client: httpx.AsyncClient) -> None:
    a, _ = await _seed_user_and_session(github_user_id=100)
    assert a.id is not None
    a_box = Sandbox(user_id=a.id, provider_name="mock")
    await a_box.create()

    _, b_sess = await _seed_user_and_session(github_user_id=200)
    client.cookies.set(SESSION_COOKIE_NAME, b_sess.session_id)
    listing = (await client.get("/api/sandboxes")).json()
    assert listing == []
    for action in ("wake", "refresh", "reset", "destroy"):
        response = await client.post(f"/api/sandboxes/{a_box.id}/{action}")
        assert response.status_code == 404


# ── Manager-level state-machine matrix ─────────────────────────────────────


@pytest.mark.asyncio
async def test_state_machine_matrix(client: httpx.AsyncClient) -> None:
    """For every (from_status, action) pair, assert the correct outcome
    (transition or IllegalSandboxTransitionError) per slice4.md §5."""
    _, _ = await _seed_user_and_session()
    manager = _manager()

    illegal_combos: list[tuple[str, str]] = [
        ("provisioning", "wake"),
        ("provisioning", "reset"),
        ("resetting", "wake"),
        ("resetting", "reset"),
        ("resetting", "destroy"),
        ("destroyed", "wake"),
        ("destroyed", "reset"),
        ("destroyed", "destroy"),
        ("failed", "wake"),
    ]
    for from_status, action in illegal_combos:
        sandbox = Sandbox(
            user_id=PydanticObjectId(),
            provider_name="mock",
            status=from_status,  # type: ignore[arg-type]
        )
        await sandbox.create()
        if from_status == "destroyed" and action == "destroy":
            result = await manager.destroy(sandbox)
            assert result.status == "destroyed"
            continue
        with pytest.raises(IllegalSandboxTransitionError):
            method = getattr(manager, action)
            await method(sandbox)
