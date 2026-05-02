"""Slice 6 FS REST tests — happy paths, path-traversal rejection, If-Match."""

import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from db.models import Sandbox, Session, User
from orchestrator.app import app
from orchestrator.middleware.auth import SESSION_COOKIE_NAME
from sandbox_provider import MockSandboxProvider


async def _seed_user_and_session(
    *,
    github_user_id: int = 42,
) -> Session:
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
    return session


def _provider() -> MockSandboxProvider:
    p = app.state.sandbox_provider
    assert isinstance(p, MockSandboxProvider)
    return p


async def _setup(client: httpx.AsyncClient) -> str:
    """Seed user, sign in, create sandbox; return sandbox_id.

    Slice-6 reconciler is owner-scoped — it leaves `/work/repo/...` and
    `/work/scratch/...` alone unless `repo`/`scratch` is a tracked owner —
    so seed-then-list patterns no longer race.
    """
    session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.post("/api/sandboxes")
    assert response.status_code == 200
    sandbox_id: str = response.json()["id"]
    return sandbox_id


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def _seed_file(sandbox_id: str, path: str, content: bytes) -> None:
    """Write a file directly via the provider — bypasses the orchestrator
    so tests can stage state."""
    sandbox = await Sandbox.get(sandbox_id)
    assert sandbox is not None and sandbox.provider_handle is not None
    from sandbox_provider import SandboxHandle

    handle = SandboxHandle(provider="mock", payload=dict(sandbox.provider_handle))
    await _provider().fs_write(handle, path, content)


# ── auth ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fs_get_requires_auth(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/sandboxes/507f1f77bcf86cd799439011/fs?path=/work/x")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_fs_get_404_when_not_owner(client: httpx.AsyncClient) -> None:
    # Owner A
    a = await _seed_user_and_session(github_user_id=1)
    client.cookies.set(SESSION_COOKIE_NAME, a.session_id)
    sbx = (await client.post("/api/sandboxes")).json()["id"]
    # Owner B tries to peek
    b = await _seed_user_and_session(github_user_id=2)
    client.cookies.set(SESSION_COOKIE_NAME, b.session_id)
    r = await client.get(f"/api/sandboxes/{sbx}/fs?path=/work")
    assert r.status_code == 404


# ── path traversal ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        # Bare path traversal upward.
        "/etc/passwd",
        "/var/log/auth.log",
        "/root/.ssh/id_rsa",
        # `..` segments that resolve outside `/work`.
        "/work/../etc/passwd",
        "/work/foo/../../etc/passwd",
        "/work/././../etc/passwd",
        "/work/repo/../../../etc/shadow",
        "/work/..",
        "/work/../..",
        # Relative paths (must be absolute).
        "../etc/passwd",
        "etc/passwd",
        "./etc/passwd",
        "",  # empty rejected by Query min_length, but the validator also
        # would; exercising via min_length=1 means FastAPI 422s — drop
        # this case (covered by Query validation) and pick another.
        # Loose-prefix attacks — `/work` is the root, NOT a substring.
        "/workspace",
        "/work2/foo",
        "/workfoo",
        # Null bytes anywhere in the path.
        "/work\x00/x",
        "/work/foo\x00.txt",
        "\x00/work/x",
        # Trailing relative path that escapes after normalization.
        "/work/foo/bar/../../../../../etc",
        # Bare double dots / escaping segments.
        "/..",
        "/../..",
        # Absolute paths that look like /work but aren't (substring trick).
        "/work_secret/x",
        "/workroot/x",
    ],
)
async def test_fs_get_rejects_traversal(client: httpx.AsyncClient, path: str) -> None:
    sbx = await _setup(client)
    r = await client.get(f"/api/sandboxes/{sbx}/fs", params={"path": path})
    # Empty `path` would be rejected by FastAPI Query before reaching the
    # validator (422). Anything else hits `_validate_path` and 400s.
    assert r.status_code in (400, 422), (path, r.status_code, r.text)


# ── read / list ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fs_read_returns_content_and_sha(client: httpx.AsyncClient) -> None:
    sbx = await _setup(client)
    await _seed_file(sbx, "/work/repo/README.md", b"hello world")
    r = await client.get(f"/api/sandboxes/{sbx}/fs", params={"path": "/work/repo/README.md"})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "file"
    assert body["content"] == "hello world"
    assert body["sha"] == _sha256(b"hello world")
    assert body["size"] == 11


@pytest.mark.asyncio
async def test_fs_list_returns_directory_entries(client: httpx.AsyncClient) -> None:
    sbx = await _setup(client)
    await _seed_file(sbx, "/work/repo/README.md", b"r")
    await _seed_file(sbx, "/work/repo/src/index.ts", b"x")
    # Sanity: provider holds both files before we hit the route.
    sandbox = await Sandbox.get(sbx)
    assert sandbox is not None and sandbox.provider_handle is not None
    from sandbox_provider import SandboxHandle as _SH

    handle = _SH(provider="mock", payload=dict(sandbox.provider_handle))
    rec = _provider()._sprites[handle.payload["name"]]  # pyright: ignore[reportPrivateUsage]
    assert sorted(rec.files.keys()) == ["/work/repo/README.md", "/work/repo/src/index.ts"], rec.files
    r = await client.get(
        f"/api/sandboxes/{sbx}/fs", params={"path": "/work/repo", "list": "true"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "list"
    names = sorted((e["name"], e["type"]) for e in body["entries"])
    assert names == [("README.md", "file"), ("src", "dir")]


@pytest.mark.asyncio
async def test_fs_read_binary_returns_415(client: httpx.AsyncClient) -> None:
    sbx = await _setup(client)
    await _seed_file(sbx, "/work/repo/img.bin", b"\x80\x00\xff")
    r = await client.get(f"/api/sandboxes/{sbx}/fs", params={"path": "/work/repo/img.bin"})
    assert r.status_code == 415


@pytest.mark.asyncio
async def test_fs_read_missing_returns_404(client: httpx.AsyncClient) -> None:
    sbx = await _setup(client)
    r = await client.get(f"/api/sandboxes/{sbx}/fs", params={"path": "/work/repo/nope.md"})
    assert r.status_code == 404


# ── write / If-Match ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fs_write_creates_new_file_without_if_match(client: httpx.AsyncClient) -> None:
    sbx = await _setup(client)
    r = await client.put(
        f"/api/sandboxes/{sbx}/fs",
        params={"path": "/work/repo/new.md"},
        json={"content": "hi"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sha"] == _sha256(b"hi")
    # Persisted via provider.
    read = await client.get(
        f"/api/sandboxes/{sbx}/fs", params={"path": "/work/repo/new.md"}
    )
    assert read.json()["content"] == "hi"


@pytest.mark.asyncio
async def test_fs_write_overwrite_requires_if_match(client: httpx.AsyncClient) -> None:
    sbx = await _setup(client)
    await _seed_file(sbx, "/work/x.md", b"v1")
    r = await client.put(
        f"/api/sandboxes/{sbx}/fs",
        params={"path": "/work/x.md"},
        json={"content": "v2"},
    )
    assert r.status_code == 428  # Precondition Required


@pytest.mark.asyncio
async def test_fs_write_overwrite_412_on_sha_mismatch(client: httpx.AsyncClient) -> None:
    sbx = await _setup(client)
    await _seed_file(sbx, "/work/x.md", b"v1")
    r = await client.put(
        f"/api/sandboxes/{sbx}/fs",
        params={"path": "/work/x.md"},
        json={"content": "v2"},
        headers={"If-Match": _sha256(b"different")},
    )
    assert r.status_code == 412
    assert r.json()["detail"]["current_sha"] == _sha256(b"v1")


@pytest.mark.asyncio
async def test_fs_write_overwrite_succeeds_with_correct_if_match(
    client: httpx.AsyncClient,
) -> None:
    sbx = await _setup(client)
    await _seed_file(sbx, "/work/x.md", b"v1")
    r = await client.put(
        f"/api/sandboxes/{sbx}/fs",
        params={"path": "/work/x.md"},
        json={"content": "v2"},
        headers={"If-Match": _sha256(b"v1")},
    )
    assert r.status_code == 200
    assert r.json()["sha"] == _sha256(b"v2")


# ── delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fs_delete_removes_file(client: httpx.AsyncClient) -> None:
    sbx = await _setup(client)
    await _seed_file(sbx, "/work/x.md", b"v1")
    r = await client.delete(f"/api/sandboxes/{sbx}/fs", params={"path": "/work/x.md"})
    assert r.status_code == 204
    read = await client.get(f"/api/sandboxes/{sbx}/fs", params={"path": "/work/x.md"})
    assert read.status_code == 404


@pytest.mark.asyncio
async def test_fs_delete_refuses_root(client: httpx.AsyncClient) -> None:
    sbx = await _setup(client)
    r = await client.delete(f"/api/sandboxes/{sbx}/fs", params={"path": "/work"})
    assert r.status_code == 400


# ── rename ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fs_rename_moves_file(client: httpx.AsyncClient) -> None:
    sbx = await _setup(client)
    await _seed_file(sbx, "/work/old.md", b"v")
    r = await client.post(
        f"/api/sandboxes/{sbx}/fs",
        params={"path": "/work/old.md", "op": "rename"},
        json={"new_path": "/work/new.md"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new_path"] == "/work/new.md"
    # Old gone, new readable.
    assert (
        await client.get(f"/api/sandboxes/{sbx}/fs", params={"path": "/work/old.md"})
    ).status_code == 404
    read = await client.get(f"/api/sandboxes/{sbx}/fs", params={"path": "/work/new.md"})
    assert read.json()["content"] == "v"


@pytest.mark.asyncio
async def test_fs_rename_rejects_dst_traversal(client: httpx.AsyncClient) -> None:
    sbx = await _setup(client)
    await _seed_file(sbx, "/work/old.md", b"v")
    r = await client.post(
        f"/api/sandboxes/{sbx}/fs",
        params={"path": "/work/old.md", "op": "rename"},
        json={"new_path": "/etc/passwd"},
    )
    assert r.status_code == 400
