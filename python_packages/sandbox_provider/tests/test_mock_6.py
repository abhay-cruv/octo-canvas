"""Slice 6 additions on `MockSandboxProvider`: fs_read, fs_write, fs_rename,
fs_watch_subscribe."""

import asyncio

import pytest
from sandbox_provider import FsEvent, MockSandboxProvider, SandboxHandle, SpritesError


async def _setup() -> tuple[MockSandboxProvider, SandboxHandle]:
    p = MockSandboxProvider()
    handle = await p.create(sandbox_id="sbx1", labels=[])
    return p, handle


@pytest.mark.asyncio
async def test_fs_write_then_read_round_trip() -> None:
    p, handle = await _setup()
    written = await p.fs_write(handle, "/work/foo/bar/README.md", b"hello")
    assert written == 5
    assert await p.fs_read(handle, "/work/foo/bar/README.md") == b"hello"


@pytest.mark.asyncio
async def test_fs_read_missing_path_raises() -> None:
    p, handle = await _setup()
    with pytest.raises(SpritesError):
        await p.fs_read(handle, "/work/missing.txt")


@pytest.mark.asyncio
async def test_fs_write_overwrites_emits_modify_not_create() -> None:
    p, handle = await _setup()
    await p.fs_write(handle, "/work/x.txt", b"v1")

    captured: list[FsEvent] = []

    async def consume() -> None:
        async for ev in p.fs_watch_subscribe(handle, "/work", recursive=True):
            captured.append(ev)
            if len(captured) >= 1:
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let subscriber register
    await p.fs_write(handle, "/work/x.txt", b"v2")
    await asyncio.wait_for(task, timeout=1.0)
    assert captured[0].kind == "modify"
    assert captured[0].path == "/work/x.txt"
    assert captured[0].size == 2


@pytest.mark.asyncio
async def test_fs_rename_moves_bytes() -> None:
    p, handle = await _setup()
    await p.fs_write(handle, "/work/old.txt", b"data")
    await p.fs_rename(handle, "/work/old.txt", "/work/new.txt")
    assert await p.fs_read(handle, "/work/new.txt") == b"data"
    with pytest.raises(SpritesError):
        await p.fs_read(handle, "/work/old.txt")


@pytest.mark.asyncio
async def test_fs_rename_missing_src_raises() -> None:
    p, handle = await _setup()
    with pytest.raises(SpritesError):
        await p.fs_rename(handle, "/work/nope", "/work/dest")


@pytest.mark.asyncio
async def test_fs_list_synthesizes_dirs_and_files_from_writes() -> None:
    p, handle = await _setup()
    await p.fs_write(handle, "/work/a/README.md", b"r")
    await p.fs_write(handle, "/work/a/src/index.ts", b"x")
    listing = await p.fs_list(handle, "/work/a")
    names = sorted((e.name, e.kind) for e in listing)
    assert names == [("README.md", "file"), ("src", "dir")]


@pytest.mark.asyncio
async def test_fs_delete_file_emits_event_and_removes() -> None:
    p, handle = await _setup()
    await p.fs_write(handle, "/work/a/x.txt", b"hi")

    captured: list[FsEvent] = []

    async def consume() -> None:
        async for ev in p.fs_watch_subscribe(handle, "/work", recursive=True):
            captured.append(ev)
            if ev.kind == "delete":
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await p.fs_delete(handle, "/work/a/x.txt")
    await asyncio.wait_for(task, timeout=1.0)
    assert captured[-1].kind == "delete"
    with pytest.raises(SpritesError):
        await p.fs_read(handle, "/work/a/x.txt")


@pytest.mark.asyncio
async def test_fs_watch_recursive_filters_outside_paths() -> None:
    p, handle = await _setup()

    captured: list[FsEvent] = []
    stop = asyncio.Event()

    async def consume() -> None:
        async for ev in p.fs_watch_subscribe(handle, "/work/repo", recursive=True):
            captured.append(ev)
            if stop.is_set():
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    # Outside the subscribed prefix — should NOT fire.
    await p.fs_write(handle, "/work/other/x.txt", b"x")
    # Inside — should fire.
    await p.fs_write(handle, "/work/repo/y.txt", b"y")
    # Give the consumer a tick to drain.
    await asyncio.sleep(0.05)
    stop.set()
    p.close_fs_watch(handle)
    await asyncio.wait_for(task, timeout=1.0)
    paths = [ev.path for ev in captured]
    assert paths == ["/work/repo/y.txt"]


@pytest.mark.asyncio
async def test_emit_fs_event_test_hook_fans_out() -> None:
    p, handle = await _setup()

    captured: list[FsEvent] = []

    async def consume() -> None:
        async for ev in p.fs_watch_subscribe(handle, "/work", recursive=True):
            captured.append(ev)
            break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    p.emit_fs_event(
        handle,
        FsEvent(path="/work/agent.txt", kind="create", is_dir=False, size=4, timestamp_ms=42),
    )
    await asyncio.wait_for(task, timeout=1.0)
    assert captured[0].path == "/work/agent.txt"
    assert captured[0].timestamp_ms == 42


@pytest.mark.asyncio
async def test_snapshot_restore_round_trips_files() -> None:
    p, handle = await _setup()
    await p.fs_write(handle, "/work/keep.txt", b"v1")
    ckpt = await p.snapshot(handle, comment="clean")
    await p.fs_write(handle, "/work/keep.txt", b"v2")
    await p.fs_write(handle, "/work/added.txt", b"new")
    await p.restore(handle, ckpt)
    assert await p.fs_read(handle, "/work/keep.txt") == b"v1"
    with pytest.raises(SpritesError):
        await p.fs_read(handle, "/work/added.txt")
