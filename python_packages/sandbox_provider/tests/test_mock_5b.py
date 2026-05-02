"""Slice 5b additions on `MockSandboxProvider`: exec_oneshot, fs_list,
fs_delete, snapshot, restore."""

import pytest
from sandbox_provider import MockSandboxProvider, SandboxHandle, SpritesError
from sandbox_provider.interface import CheckpointId


async def _setup() -> tuple[MockSandboxProvider, SandboxHandle]:
    p = MockSandboxProvider()
    handle = await p.create(sandbox_id="sbx1", labels=[])
    return p, handle


@pytest.mark.asyncio
async def test_exec_git_clone_recognized() -> None:
    p, handle = await _setup()
    res = await p.exec_oneshot(
        handle,
        ["git", "clone", "--depth", "1", "https://x@github.com/foo/bar.git", "/work/foo/bar"],
        env={},
        cwd="/work",
    )
    assert res.exit_code == 0
    listing = await p.fs_list(handle, "/work")
    assert [e.name for e in listing] == ["foo/bar"]


@pytest.mark.asyncio
async def test_exec_apt_install_records_packages() -> None:
    p, handle = await _setup()
    res = await p.exec_oneshot(
        handle,
        ["apt-get", "install", "-y", "libpq-dev", "libvips-dev"],
        env={},
        cwd="/work",
    )
    assert res.exit_code == 0
    # Mock exposes the recorded set via the private record for assertions.
    rec = p._sprites["octo-sbx-sbx1"]  # pyright: ignore[reportPrivateUsage]
    assert rec.apt_installed == {"libpq-dev", "libvips-dev"}


@pytest.mark.asyncio
async def test_exec_rm_removes_clone() -> None:
    p, handle = await _setup()
    await p.exec_oneshot(
        handle,
        ["git", "clone", "https://github.com/a/b.git", "/work/a/b"],
        env={},
        cwd="/work",
    )
    assert len(await p.fs_list(handle, "/work")) == 1
    res = await p.exec_oneshot(handle, ["rm", "-rf", "/work/a/b"], env={}, cwd="/work")
    assert res.exit_code == 0
    assert await p.fs_list(handle, "/work") == []


@pytest.mark.asyncio
async def test_exec_unknown_command_returns_zero() -> None:
    p, handle = await _setup()
    res = await p.exec_oneshot(handle, ["echo", "hi"], env={}, cwd="/work")
    assert res.exit_code == 0


@pytest.mark.asyncio
async def test_fs_list_unknown_path_empty() -> None:
    p, handle = await _setup()
    assert await p.fs_list(handle, "/nope") == []


@pytest.mark.asyncio
async def test_fs_delete_idempotent() -> None:
    p, handle = await _setup()
    await p.fs_delete(handle, "/work/never", recursive=True)
    # No error.


@pytest.mark.asyncio
async def test_snapshot_restore_round_trip() -> None:
    p, handle = await _setup()
    await p.exec_oneshot(
        handle,
        ["git", "clone", "https://github.com/a/b.git", "/work/a/b"],
        env={},
        cwd="/work",
    )
    ckpt = await p.snapshot(handle, comment="clean")
    # Add another repo after the snapshot.
    await p.exec_oneshot(
        handle,
        ["git", "clone", "https://github.com/c/d.git", "/work/c/d"],
        env={},
        cwd="/work",
    )
    assert {e.name for e in await p.fs_list(handle, "/work")} == {"a/b", "c/d"}
    state = await p.restore(handle, ckpt)
    assert state.status == "warm"
    assert {e.name for e in await p.fs_list(handle, "/work")} == {"a/b"}


@pytest.mark.asyncio
async def test_restore_unknown_checkpoint_raises() -> None:
    p, handle = await _setup()
    with pytest.raises(SpritesError):
        await p.restore(handle, CheckpointId("does-not-exist"))
