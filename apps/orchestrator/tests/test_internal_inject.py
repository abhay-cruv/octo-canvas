"""POST /api/_internal/tasks/{id}/events — slice 5a dev-only injector."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from db.models import Session, Task, User
from orchestrator.middleware.auth import SESSION_COOKIE_NAME

pytestmark = pytest.mark.asyncio


async def _seed(github_user_id: int = 1) -> tuple[User, Session]:
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


async def test_create_task_then_inject_event(client: httpx.AsyncClient) -> None:
    _, session = await _seed(github_user_id=101)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)

    r = await client.post("/api/_internal/tasks")
    assert r.status_code == 201, r.text
    task_id = r.json()["id"]

    r2 = await client.post(
        f"/api/_internal/tasks/{task_id}/events", json={"message": "hello"}
    )
    assert r2.status_code == 202, r2.text
    body = r2.json()
    assert body["task_id"] == task_id
    assert body["seq"] == 1


async def test_inject_rejects_other_users_task(client: httpx.AsyncClient) -> None:
    owner, _ = await _seed(github_user_id=200)
    _, other_session = await _seed(github_user_id=201)
    task = Task(user_id=owner.id)  # type: ignore[arg-type]
    await task.insert()

    client.cookies.set(SESSION_COOKIE_NAME, other_session.session_id)
    r = await client.post(
        f"/api/_internal/tasks/{task.id}/events", json={"message": "x"}
    )
    assert r.status_code == 403


async def test_inject_404_for_missing_task(client: httpx.AsyncClient) -> None:
    _, session = await _seed(github_user_id=300)
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    r = await client.post(
        "/api/_internal/tasks/000000000000000000000000/events",
        json={"message": "x"},
    )
    assert r.status_code == 404


async def test_inject_unauthenticated(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/_internal/tasks/000000000000000000000000/events",
        json={"message": "x"},
    )
    assert r.status_code == 401
