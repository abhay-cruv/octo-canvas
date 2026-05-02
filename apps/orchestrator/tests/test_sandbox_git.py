"""Slice 6 git read-surface tests — status parsing + show fallbacks."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from db.models import Sandbox, Session, User
from orchestrator.app import app
from orchestrator.middleware.auth import SESSION_COOKIE_NAME
from sandbox_provider import MockSandboxProvider, SandboxHandle


async def _seed_user_and_session(*, github_user_id: int = 42) -> Session:
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


async def _setup(client: httpx.AsyncClient) -> tuple[str, SandboxHandle]:
    session = await _seed_user_and_session()
    client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
    response = await client.post("/api/sandboxes")
    assert response.status_code == 200
    sbx_id: str = response.json()["id"]
    sandbox = await Sandbox.get(sbx_id)
    assert sandbox is not None and sandbox.provider_handle is not None
    handle = SandboxHandle(provider="mock", payload=dict(sandbox.provider_handle))
    return sbx_id, handle


# ── auth + path validation ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_status_requires_auth(client: httpx.AsyncClient) -> None:
    r = await client.get(
        "/api/sandboxes/507f1f77bcf86cd799439011/git/status",
        params={"repo_path": "/work/a/b"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "repo_path",
    [
        "/etc/passwd",
        "/work",
        "/work/onlyowner",
        "/work/owner/repo/extra",
        "/work/../etc",
        "/work/owner\x00/repo",
        "owner/repo",  # not absolute
    ],
)
async def test_git_status_rejects_bad_repo_path(
    client: httpx.AsyncClient, repo_path: str
) -> None:
    sbx, _ = await _setup(client)
    r = await client.get(
        f"/api/sandboxes/{sbx}/git/status", params={"repo_path": repo_path}
    )
    assert r.status_code in (400, 422), (repo_path, r.status_code, r.text)


# ── status parsing ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_status_parses_branch_and_files(client: httpx.AsyncClient) -> None:
    sbx, handle = await _setup(client)
    # Porcelain v1 -b -z output: branch line, then NUL-separated entries.
    raw = (
        "## main...origin/main [ahead 2, behind 1]\x00"
        " M src/index.ts\x00"
        "?? new.txt\x00"
        "A  src/staged.ts\x00"
        "MM src/both.ts\x00"
    )
    _provider().set_git_status_output(handle, "/work/alice/repo", raw)
    r = await client.get(
        f"/api/sandboxes/{sbx}/git/status", params={"repo_path": "/work/alice/repo"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["branch"] == "main"
    assert body["ahead"] == 2
    assert body["behind"] == 1
    assert body["detached"] is False
    files = body["files"]
    by_path = {f["rel_path"]: f for f in files}
    assert by_path["src/index.ts"]["worktree"] == "M"
    assert by_path["src/index.ts"]["index"] == " "
    assert by_path["new.txt"]["index"] == "?"
    assert by_path["new.txt"]["worktree"] == "?"
    assert by_path["src/staged.ts"]["index"] == "A"
    assert by_path["src/staged.ts"]["worktree"] == " "
    assert by_path["src/both.ts"]["index"] == "M"
    assert by_path["src/both.ts"]["worktree"] == "M"


@pytest.mark.asyncio
async def test_git_status_handles_renames(client: httpx.AsyncClient) -> None:
    sbx, handle = await _setup(client)
    raw = (
        "## main\x00"
        "R  new/path.ts\x00"
        "old/path.ts\x00"
    )
    _provider().set_git_status_output(handle, "/work/alice/repo", raw)
    r = await client.get(
        f"/api/sandboxes/{sbx}/git/status", params={"repo_path": "/work/alice/repo"}
    )
    files = r.json()["files"]
    assert files == [
        {
            "rel_path": "new/path.ts",
            "index": "R",
            "worktree": " ",
            "rel_path_orig": "old/path.ts",
        }
    ]


@pytest.mark.asyncio
async def test_git_status_detached_head(client: httpx.AsyncClient) -> None:
    sbx, handle = await _setup(client)
    raw = "## HEAD (no branch)\x00"
    _provider().set_git_status_output(handle, "/work/alice/repo", raw)
    r = await client.get(
        f"/api/sandboxes/{sbx}/git/status", params={"repo_path": "/work/alice/repo"}
    )
    body = r.json()
    assert body["detached"] is True
    assert body["branch"] is None


@pytest.mark.asyncio
async def test_git_status_empty_repo_returns_empty_list(client: httpx.AsyncClient) -> None:
    """No canned output set → mock returns empty stdout → parser returns
    an empty `files` list. (This represents a clean repo.)"""
    sbx, _ = await _setup(client)
    r = await client.get(
        f"/api/sandboxes/{sbx}/git/status", params={"repo_path": "/work/alice/repo"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["files"] == []


# ── show ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_show_returns_content(client: httpx.AsyncClient) -> None:
    sbx, handle = await _setup(client)
    _provider().set_git_show_output(
        handle, "/work/alice/repo", "HEAD:src/x.py", "print('hello')\n"
    )
    r = await client.get(
        f"/api/sandboxes/{sbx}/git/show",
        params={
            "repo_path": "/work/alice/repo",
            "rel_path": "src/x.py",
            "ref": "HEAD",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["content"] == "print('hello')\n"
    assert body["truncated"] is False


@pytest.mark.asyncio
async def test_git_show_missing_returns_exists_false(client: httpx.AsyncClient) -> None:
    sbx, handle = await _setup(client)
    _provider().mark_git_show_missing(handle, "/work/alice/repo", "HEAD:src/new.py")
    r = await client.get(
        f"/api/sandboxes/{sbx}/git/show",
        params={
            "repo_path": "/work/alice/repo",
            "rel_path": "src/new.py",
            "ref": "HEAD",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is False
    assert body["content"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ref",
    ["HEAD; rm -rf", "HEAD\x00", "..", "with spaces", "HEAD..main"],
)
async def test_git_show_rejects_bad_refs(client: httpx.AsyncClient, ref: str) -> None:
    sbx, _ = await _setup(client)
    r = await client.get(
        f"/api/sandboxes/{sbx}/git/show",
        params={
            "repo_path": "/work/alice/repo",
            "rel_path": "src/x.py",
            "ref": ref,
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rel_path",
    ["/etc/passwd", "../etc/passwd", "src/../../etc", "with\x00null"],
)
async def test_git_show_rejects_bad_rel_paths(
    client: httpx.AsyncClient, rel_path: str
) -> None:
    sbx, _ = await _setup(client)
    r = await client.get(
        f"/api/sandboxes/{sbx}/git/show",
        params={"repo_path": "/work/alice/repo", "rel_path": rel_path},
    )
    assert r.status_code == 400
