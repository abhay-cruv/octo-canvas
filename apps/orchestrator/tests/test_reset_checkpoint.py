"""SandboxManager.reset — checkpoint fast path vs slow fallback."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from db.models import Sandbox, User
from orchestrator.services.sandbox_manager import SandboxManager
from sandbox_provider import MockSandboxProvider

if TYPE_CHECKING:
    import httpx

pytestmark = pytest.mark.asyncio


def _now() -> datetime:
    return datetime.now(UTC)


async def _seed(provider: MockSandboxProvider) -> tuple[User, Sandbox]:
    user = User(
        github_user_id=1,
        github_username="u",
        email="u@e.com",
        last_signed_in_at=_now(),
        created_at=_now(),
        updated_at=_now(),
        github_access_token="t",
    )
    await user.create()
    assert user.id is not None
    sandbox = Sandbox(user_id=user.id, provider_name="mock", status="warm")
    await sandbox.create()
    assert sandbox.id is not None
    handle = await provider.create(sandbox_id=str(sandbox.id), labels=[])
    sandbox.provider_handle = dict(handle.payload)
    sandbox.public_url = "https://x"
    await sandbox.save()
    return user, sandbox


async def test_reset_wipes_workdir_keeps_sprite(
    client: "httpx.AsyncClient",
) -> None:
    """Healthy Reset wipes `/work` via fs_delete; sprite identity
    (`provider_handle.id`) is preserved so git config, apt cache, etc
    survive."""
    _ = client
    provider = MockSandboxProvider()
    _user, sandbox = await _seed(provider)
    assert sandbox.id is not None
    pre_handle_id = sandbox.provider_handle.get("id")

    manager = SandboxManager(provider=provider, redis=None)
    after = await manager.reset(sandbox)
    assert after.provider_handle.get("id") == pre_handle_id
    assert after.reset_count == 1
    assert after.clean_checkpoint_id is None


async def test_reset_falls_back_to_recreate_when_failed(
    client: "httpx.AsyncClient",
) -> None:
    """Failed sandboxes have a broken sprite — wiping `/work` won't
    fix them, so reset goes through destroy+create. The sprite handle
    rotates."""
    _ = client
    provider = MockSandboxProvider()
    _user, sandbox = await _seed(provider)
    assert sandbox.id is not None
    sandbox.status = "failed"
    sandbox.failure_reason = "boom"
    await sandbox.save()
    pre_handle_id = sandbox.provider_handle.get("id")

    manager = SandboxManager(provider=provider, redis=None)
    after = await manager.reset(sandbox)
    assert after.status in ("warm", "running", "cold")
    assert after.provider_handle.get("id") != pre_handle_id
    assert after.reset_count == 1
    assert after.failure_reason is None
