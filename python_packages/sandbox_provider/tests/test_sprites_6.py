"""SpritesProvider slice 6 additions: fs_read, fs_write, fs_rename,
fs_watch_subscribe.

Like `test_sprites.py`, no real network. The SDK's `SpritePath` is faked
behind a sprite wrapper; `fs_watch_subscribe` is exercised by patching
`websockets.connect` to return a fake socket that yields canned JSON frames.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from sandbox_provider import SandboxHandle, SpritesError, SpritesProvider
from sprites import FilesystemError


@dataclass
class _FakePath:
    path: str
    fs: "_FakeFilesystem"

    def read_bytes(self) -> bytes:
        if self.fs.read_raises is not None:
            raise self.fs.read_raises
        if self.path not in self.fs.files:
            raise FilesystemError("not found", "read", self.path)
        return self.fs.files[self.path]

    def write_bytes(
        self, data: bytes, mode: int = 0o644, mkdir_parents: bool = True
    ) -> None:
        if self.fs.write_raises is not None:
            raise self.fs.write_raises
        self.fs.files[self.path] = bytes(data)
        self.fs.write_calls.append((self.path, mode, mkdir_parents, len(data)))

    def rename(self, target: Any) -> "_FakePath":
        target_path = target if isinstance(target, str) else target.path
        if self.fs.rename_raises is not None:
            raise self.fs.rename_raises
        if self.path not in self.fs.files:
            raise FilesystemError("not found", "rename", self.path)
        self.fs.files[target_path] = self.fs.files.pop(self.path)
        self.fs.rename_calls.append((self.path, target_path))
        return _FakePath(path=target_path, fs=self.fs)


@dataclass
class _FakeFilesystem:
    files: dict[str, bytes] = field(default_factory=dict)
    read_raises: BaseException | None = None
    write_raises: BaseException | None = None
    rename_raises: BaseException | None = None
    write_calls: list[tuple[str, int, bool, int]] = field(default_factory=list)
    rename_calls: list[tuple[str, str]] = field(default_factory=list)

    def path(self, p: str) -> _FakePath:
        return _FakePath(path=p, fs=self)


@dataclass
class _FakeSpriteWrapper:
    name: str
    fs: _FakeFilesystem

    def filesystem(self) -> _FakeFilesystem:
        return self.fs


@dataclass
class _FakeClient:
    fs: _FakeFilesystem
    base_url: str = "https://api.sprites.dev"
    token: str = "test-token"

    def sprite(self, name: str) -> _FakeSpriteWrapper:
        return _FakeSpriteWrapper(name=name, fs=self.fs)

    def close(self) -> None:
        pass


def _build_provider(fake: _FakeClient) -> SpritesProvider:
    p = SpritesProvider(token="test-token")
    p._client = fake  # pyright: ignore[reportAttributeAccessIssue]
    return p


_HANDLE = SandboxHandle(provider="sprites", payload={"name": "octo-sbx-x"})


# ── fs_read ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fs_read_returns_bytes_via_sdk_path() -> None:
    fs = _FakeFilesystem(files={"/work/a.txt": b"hello"})
    p = _build_provider(_FakeClient(fs=fs))
    assert await p.fs_read(_HANDLE, "/work/a.txt") == b"hello"


@pytest.mark.asyncio
async def test_fs_read_missing_path_raises_non_retriable() -> None:
    p = _build_provider(_FakeClient(fs=_FakeFilesystem()))
    with pytest.raises(SpritesError) as exc_info:
        await p.fs_read(_HANDLE, "/work/missing")
    assert exc_info.value.retriable is False


# ── fs_write ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fs_write_passes_mode_and_mkdir_to_sdk_and_returns_size() -> None:
    fs = _FakeFilesystem()
    p = _build_provider(_FakeClient(fs=fs))
    n = await p.fs_write(_HANDLE, "/work/new.txt", b"data!", mode=0o600, mkdir=False)
    assert n == 5
    assert fs.files["/work/new.txt"] == b"data!"
    assert fs.write_calls == [("/work/new.txt", 0o600, False, 5)]


@pytest.mark.asyncio
async def test_fs_write_filesystem_error_is_non_retriable() -> None:
    fs = _FakeFilesystem(write_raises=FilesystemError("permission denied", "write", "/x"))
    p = _build_provider(_FakeClient(fs=fs))
    with pytest.raises(SpritesError) as exc_info:
        await p.fs_write(_HANDLE, "/x", b"x")
    assert exc_info.value.retriable is False


# ── fs_rename ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fs_rename_calls_sdk_rename() -> None:
    fs = _FakeFilesystem(files={"/work/old": b"v"})
    p = _build_provider(_FakeClient(fs=fs))
    await p.fs_rename(_HANDLE, "/work/old", "/work/new")
    assert fs.files == {"/work/new": b"v"}
    assert fs.rename_calls == [("/work/old", "/work/new")]


@pytest.mark.asyncio
async def test_fs_rename_missing_src_is_non_retriable() -> None:
    p = _build_provider(_FakeClient(fs=_FakeFilesystem()))
    with pytest.raises(SpritesError) as exc_info:
        await p.fs_rename(_HANDLE, "/work/missing", "/work/x")
    assert exc_info.value.retriable is False


# ── fs_watch_subscribe ────────────────────────────────────────────────────


class _FakeWebSocket:
    """Async iterator over canned text frames; logs send() calls; drops on close."""

    def __init__(self, frames: list[str]) -> None:
        self._frames = list(frames)
        self.sent: list[str] = []
        self.closed = False

    async def send(self, msg: str) -> None:
        self.sent.append(msg)

    def __aiter__(self) -> "_FakeWebSocket":
        return self

    async def __anext__(self) -> str:
        if not self._frames:
            raise StopAsyncIteration
        await asyncio.sleep(0)
        return self._frames.pop(0)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_fs_watch_subscribe_yields_parsed_events(monkeypatch: pytest.MonkeyPatch) -> None:
    frames = [
        json.dumps({"type": "subscribed"}),  # control frame — ignored
        json.dumps(
            {
                "type": "event",
                "path": "/work/foo.txt",
                "event": "create",
                "isDir": False,
                "size": 42,
                "timestamp": 1234,
            }
        ),
        json.dumps(
            {
                "type": "event",
                "path": "/work/foo.txt",
                "event": "remove",
                "isDir": False,
            }
        ),
    ]
    ws = _FakeWebSocket(frames)
    captured_url: dict[str, Any] = {}

    async def fake_connect(
        url: str, *, additional_headers: list[tuple[str, str]], max_size: int
    ) -> _FakeWebSocket:
        captured_url["url"] = url
        captured_url["headers"] = additional_headers
        captured_url["max_size"] = max_size
        return ws

    monkeypatch.setattr("sandbox_provider.sprites.websockets.connect", fake_connect)
    p = _build_provider(_FakeClient(fs=_FakeFilesystem()))

    events = []
    async for ev in p.fs_watch_subscribe(_HANDLE, "/work", recursive=True):
        events.append(ev)

    assert [(ev.kind, ev.path) for ev in events] == [
        ("create", "/work/foo.txt"),
        ("delete", "/work/foo.txt"),
    ]
    assert events[0].size == 42
    assert events[0].timestamp_ms == 1234
    # URL: scheme swapped to wss, query params present.
    assert captured_url["url"].startswith(
        "wss://api.sprites.dev/v1/sprites/octo-sbx-x/fs/watch?"
    )
    assert "path=%2Fwork" in captured_url["url"]
    assert "recursive=true" in captured_url["url"]
    # Bearer auth header.
    assert ("Authorization", "Bearer test-token") in captured_url["headers"]
    # Subscribe frame sent on connect.
    assert json.loads(ws.sent[0]) == {
        "type": "subscribe",
        "paths": ["/work"],
        "recursive": True,
        "workingDir": "/",
    }
    # Closed in finally.
    assert ws.closed is True


@pytest.mark.asyncio
async def test_fs_watch_subscribe_connect_error_raises_retriable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_connect(*args: Any, **kwargs: Any) -> _FakeWebSocket:
        raise OSError("connection refused")

    monkeypatch.setattr("sandbox_provider.sprites.websockets.connect", fake_connect)
    p = _build_provider(_FakeClient(fs=_FakeFilesystem()))

    with pytest.raises(SpritesError) as exc_info:
        async for _ in p.fs_watch_subscribe(_HANDLE, "/work", recursive=True):
            pass
    assert exc_info.value.retriable is True
