"""Reconciliation service — slice 5b."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from beanie import PydanticObjectId
from db.models import Repo, Sandbox, User
from orchestrator.services.reconciliation import Reconciler
from sandbox_provider import MockSandboxProvider
from shared_models.introspection import RepoIntrospection

if TYPE_CHECKING:
    import httpx

pytestmark = pytest.mark.asyncio


def _now() -> datetime:
    return datetime.now(UTC)


async def _seed_user_and_sandbox(
    provider: MockSandboxProvider, *, github_token: str | None = "gh-token"
) -> tuple[User, Sandbox]:
    user = User(
        github_user_id=42,
        github_username="u42",
        email="u42@e.com",
        last_signed_in_at=_now(),
        created_at=_now(),
        updated_at=_now(),
        github_access_token=github_token,
    )
    await user.create()
    assert user.id is not None

    sandbox = Sandbox(user_id=user.id, provider_name="mock", status="warm")
    await sandbox.create()
    assert sandbox.id is not None
    handle = await provider.create(sandbox_id=str(sandbox.id), labels=[])
    sandbox.provider_handle = dict(handle.payload)
    sandbox.public_url = "https://x.example"
    await sandbox.save()
    return user, sandbox


def _intro(*, system_packages: list[str] | None = None) -> RepoIntrospection:
    return RepoIntrospection(
        primary_language="Python",
        package_manager="uv",
        test_command="uv run pytest",
        build_command=None,
        dev_command=None,
        runtimes=[],
        system_packages=list(system_packages or []),
        detected_at=_now(),
    )


async def test_reconcile_clones_pending_repos(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider)
    assert user.id is not None and sandbox.id is not None

    repo = Repo(
        user_id=user.id,
        sandbox_id=sandbox.id,
        github_repo_id=1,
        full_name="alice/repo",
        default_branch="main",
        private=False,
    )
    await repo.create()

    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(sandbox.id)
    assert result.cloned == ["alice/repo"]
    assert result.checkpoint_taken is True

    refreshed = await Repo.get(repo.id)
    assert refreshed is not None
    assert refreshed.clone_status == "ready"
    assert refreshed.clone_path == "/work/alice/repo"

    sandbox_after = await Sandbox.get(sandbox.id)
    assert sandbox_after is not None
    assert sandbox_after.clean_checkpoint_id is not None


async def test_reconcile_removes_orphan_dirs(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider)
    assert user.id is not None and sandbox.id is not None

    # Inject an orphan directly into the mock's FS — simulates a clone that
    # was made by a previous reconciliation pass for a now-deleted Repo.
    sprite_name = f"octo-sbx-{sandbox.id}"
    provider._sprites[sprite_name].cloned_repos.add("orphan/repo")  # pyright: ignore[reportPrivateUsage]

    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(sandbox.id)
    assert result.removed == ["orphan/repo"]


async def test_reconcile_noop_takes_no_checkpoint(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    _user, sandbox = await _seed_user_and_sandbox(provider)
    assert sandbox.id is not None
    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(sandbox.id)
    assert result.cloned == []
    assert result.removed == []
    assert result.checkpoint_taken is False


async def test_reconcile_apt_install_dedup_across_repos(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider)
    assert user.id is not None and sandbox.id is not None

    for i, pkgs in enumerate([["libpq-dev"], ["libpq-dev", "libvips-dev"]]):
        repo = Repo(
            user_id=user.id,
            sandbox_id=sandbox.id,
            github_repo_id=10 + i,
            full_name=f"alice/repo{i}",
            default_branch="main",
            private=False,
            introspection_detected=_intro(system_packages=pkgs),
        )
        await repo.create()

    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(sandbox.id)
    assert sorted(result.apt_installed) == ["libpq-dev", "libvips-dev"]


async def test_reconcile_clone_fails_without_token(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider, github_token=None)
    assert user.id is not None and sandbox.id is not None
    repo = Repo(
        user_id=user.id,
        sandbox_id=sandbox.id,
        github_repo_id=1,
        full_name="alice/secret",
        default_branch="main",
        private=False,
    )
    await repo.create()

    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(sandbox.id)
    assert result.failed == [("alice/secret", "github_reauth_required")]
    refreshed = await Repo.get(repo.id)
    assert refreshed is not None
    assert refreshed.clone_status == "failed"
    assert refreshed.clone_error == "github_reauth_required"


async def test_reconcile_serializes_concurrent_triggers(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider)
    assert user.id is not None and sandbox.id is not None
    repo = Repo(
        user_id=user.id,
        sandbox_id=sandbox.id,
        github_repo_id=1,
        full_name="alice/repo",
        default_branch="main",
        private=False,
    )
    await repo.create()

    reconciler = Reconciler(provider)
    a, b = await asyncio.gather(
        reconciler.reconcile(sandbox.id),
        reconciler.reconcile(sandbox.id),
    )
    # First pass clones; second sees no diff.
    cloned = a.cloned + b.cloned
    assert cloned.count("alice/repo") == 1


async def test_reconcile_skips_when_sandbox_destroyed(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider)
    assert user.id is not None and sandbox.id is not None
    sandbox.status = "destroyed"
    await sandbox.save()
    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(sandbox.id)
    assert result.skipped is True
    assert result.skipped_reason == "sandbox_status:destroyed"


async def test_reconcile_skips_unknown_sandbox(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(PydanticObjectId())
    assert result.skipped is True
    assert result.skipped_reason == "sandbox_missing"
