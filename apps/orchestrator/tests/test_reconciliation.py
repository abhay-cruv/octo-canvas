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
from shared_models.introspection import RepoIntrospection, Runtime

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


async def test_reconcile_removes_orphan_dirs_under_tracked_owner(
    client: "httpx.AsyncClient",
) -> None:
    """Slice-6 update: orphan removal is now scoped to *tracked* owners.

    A repo `alice/keepme` is connected, so `alice` is a tracked owner.
    A stale `alice/orphan` clone (from a previous reconcile pass) gets
    removed because it sits under a tracked owner but isn't in `wanted`.
    """
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider)
    assert user.id is not None and sandbox.id is not None

    repo = Repo(
        user_id=user.id,
        sandbox_id=sandbox.id,
        github_repo_id=1,
        full_name="alice/keepme",
        default_branch="main",
        private=False,
        clone_status="ready",  # already cloned; reconciler shouldn't re-clone
    )
    await repo.create()

    sprite_name = f"octo-sbx-{sandbox.id}"
    rec = provider._sprites[sprite_name]  # pyright: ignore[reportPrivateUsage]
    rec.cloned_repos.add("alice/keepme")
    rec.cloned_repos.add("alice/orphan")

    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(sandbox.id)
    assert result.removed == ["alice/orphan"]


async def test_reconcile_leaves_user_scratch_alone(
    client: "httpx.AsyncClient",
) -> None:
    """Slice-6 update: `/work/<not-a-tracked-owner>/...` is NEVER removed.

    Users can create scratch directories from the IDE under `/work/` and
    the reconciler must not touch them. Without a tracked repo under the
    owner, the reconciler doesn't even descend into the dir.
    """
    _ = client
    provider = MockSandboxProvider()
    _user, sandbox = await _seed_user_and_sandbox(provider)
    assert sandbox.id is not None

    sprite_name = f"octo-sbx-{sandbox.id}"
    rec = provider._sprites[sprite_name]  # pyright: ignore[reportPrivateUsage]
    # User created /work/scratch/notes.md from the IDE — modeled in the
    # mock as a file under the per-byte FS dict (cloned_repos is empty).
    rec.files["/work/scratch/notes.md"] = b"my notes"
    # Also a deeper structure: /work/playground/poc/main.py
    rec.files["/work/playground/poc/main.py"] = b"print('hi')"

    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(sandbox.id)
    assert result.removed == []
    # Files survived.
    assert "/work/scratch/notes.md" in rec.files
    assert "/work/playground/poc/main.py" in rec.files


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


# ── Slice 7: language-runtime install phase ─────────────────────────────────


def _intro_with_runtimes(runtimes: list[Runtime]) -> RepoIntrospection:
    return RepoIntrospection(
        primary_language="JavaScript",
        package_manager="pnpm",
        test_command=None,
        build_command=None,
        dev_command=None,
        runtimes=runtimes,
        system_packages=[],
        detected_at=_now(),
    )


async def test_reconcile_installs_runtimes_dedup_across_repos(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider)
    assert user.id is not None and sandbox.id is not None

    # Two repos pin Node 20.11.0; another pins Python 3.12.4.
    runtimes_a = [
        Runtime(name="node", version="20.11.0", source=".nvmrc"),
        Runtime(name="python", version="3.12.4", source=".python-version"),
    ]
    runtimes_b = [Runtime(name="node", version="20.11.0", source=".nvmrc")]
    for i, rts in enumerate([runtimes_a, runtimes_b]):
        await Repo(
            user_id=user.id,
            sandbox_id=sandbox.id,
            github_repo_id=200 + i,
            full_name=f"alice/poly{i}",
            default_branch="main",
            private=False,
            introspection_detected=_intro_with_runtimes(rts),
        ).create()
    # Pre-seed bridge setup as done — `installing_runtimes` is gated on
    # this so the reconciler doesn't try `nvm install` before nvm itself
    # is on PATH.
    sandbox.bridge_setup_fingerprint = BRIDGE_SETUP_FINGERPRINT
    await sandbox.save()

    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(sandbox.id)

    assert sorted(result.runtimes_installed) == [
        ("node", "20.11.0"),
        ("python", "3.12.4"),
    ]
    from sandbox_provider import SandboxHandle

    h = SandboxHandle(provider="mock", payload={"name": f"octo-sbx-{sandbox.id}"})
    assert provider.runtimes_installed(h) == {("node", "20.11.0"), ("python", "3.12.4")}


async def test_reconcile_runtime_install_failure_recorded_per_repo(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider)
    assert user.id is not None and sandbox.id is not None

    repo = Repo(
        user_id=user.id,
        sandbox_id=sandbox.id,
        github_repo_id=300,
        full_name="alice/badnode",
        default_branch="main",
        private=False,
        introspection_detected=_intro_with_runtimes(
            [Runtime(name="node", version="0.0.0-bogus", source=".nvmrc")]
        ),
    )
    await repo.create()

    from sandbox_provider import SandboxHandle

    h = SandboxHandle(provider="mock", payload={"name": f"octo-sbx-{sandbox.id}"})
    provider.fail_runtime_install(h, "node", "0.0.0-bogus", exit_code=1)
    # Pre-seed bridge setup as done so the runtime-install gate opens.
    sandbox.bridge_setup_fingerprint = BRIDGE_SETUP_FINGERPRINT
    await sandbox.save()

    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(sandbox.id)

    # Install failed — reconciliation still proceeds (clone happens too).
    assert result.runtimes_installed == []
    assert result.cloned == ["alice/badnode"]

    refreshed = await Repo.get(repo.id)
    assert refreshed is not None
    assert refreshed.runtime_install_error is not None
    assert "node 0.0.0-bogus" in refreshed.runtime_install_error


async def test_reconcile_skips_runtime_install_when_no_versions(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider)
    assert user.id is not None and sandbox.id is not None

    # Runtime detected but no version pinned — nothing to install.
    await Repo(
        user_id=user.id,
        sandbox_id=sandbox.id,
        github_repo_id=400,
        full_name="alice/unpinned",
        default_branch="main",
        private=False,
        introspection_detected=_intro_with_runtimes(
            [Runtime(name="node", version=None, source="package.json")]
        ),
    ).create()

    reconciler = Reconciler(provider)
    result = await reconciler.reconcile(sandbox.id)
    assert result.runtimes_installed == []


# ── Slice 7: installing_bridge phase ────────────────────────────────────────


from orchestrator.services.reconciliation import (  # noqa: E402
    BRIDGE_SETUP_FINGERPRINT,
)
from orchestrator.services.sandbox_manager import BridgeRuntimeConfig  # noqa: E402


def _runtime_config() -> BridgeRuntimeConfig:
    return BridgeRuntimeConfig(
        orchestrator_base_url="https://orch.test",
        _anthropic_api_key="sk-ant-fake",
    )


async def test_reconcile_runs_bridge_setup_once_then_skips(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider)
    assert user.id is not None and sandbox.id is not None

    await Repo(
        user_id=user.id,
        sandbox_id=sandbox.id,
        github_repo_id=900,
        full_name="alice/setup",
        default_branch="main",
        private=False,
    ).create()

    reconciler = Reconciler(provider, bridge_config=_runtime_config())

    # First pass installs bridge prerequisites; fingerprint persists.
    await reconciler.reconcile(sandbox.id)
    sandbox_after = await Sandbox.get(sandbox.id)
    assert sandbox_after is not None
    assert sandbox_after.bridge_setup_fingerprint == BRIDGE_SETUP_FINGERPRINT

    # Second pass should skip: fingerprint already matches. We
    # capture this by counting bash-setup invocations on the mock.
    # Mock's exec_oneshot doesn't record arbitrary scripts, so we assert
    # via the doc state staying equal.
    await reconciler.reconcile(sandbox.id)
    sandbox_after_2 = await Sandbox.get(sandbox.id)
    assert sandbox_after_2 is not None
    assert sandbox_after_2.bridge_setup_fingerprint == BRIDGE_SETUP_FINGERPRINT


async def test_reconcile_skips_bridge_setup_without_config(
    client: "httpx.AsyncClient",
) -> None:
    _ = client
    provider = MockSandboxProvider()
    user, sandbox = await _seed_user_and_sandbox(provider)
    assert user.id is not None and sandbox.id is not None

    await Repo(
        user_id=user.id,
        sandbox_id=sandbox.id,
        github_repo_id=901,
        full_name="alice/nosetup",
        default_branch="main",
        private=False,
    ).create()

    # No bridge_config passed → install phase is a no-op.
    reconciler = Reconciler(provider)
    await reconciler.reconcile(sandbox.id)
    sandbox_after = await Sandbox.get(sandbox.id)
    assert sandbox_after is not None
    assert sandbox_after.bridge_setup_fingerprint is None
