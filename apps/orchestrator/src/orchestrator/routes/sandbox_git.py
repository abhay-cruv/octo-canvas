"""Per-sandbox git read surface (slice 6).

Backed entirely by `provider.exec_oneshot` — no new Protocol method. We
shell out to `git -C <repo_path> status --porcelain=v1 -b -z` for status
and `git -C <repo_path> show <ref>:<rel_path>` for diff content.

This is read-only on purpose. Push/PR/commit live in slice 9.
"""

from __future__ import annotations

from beanie import PydanticObjectId
from db.models import Sandbox, User
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sandbox_provider import SandboxProvider, SpritesError
from shared_models.sandbox_git import GitShowResponse, GitStatusFile, GitStatusResponse

from ..lib.logger import logger
from ..middleware.auth import require_user

router = APIRouter()


_GIT_TIMEOUT_S = 15
_MAX_SHOW_BYTES = 2 * 1024 * 1024  # match the editor cap.


def _git_argv(repo_path: str, *args: str) -> list[str]:
    """Build a `git -c safe.directory='*' -C <repo> ...` argv.

    The reconciler clones repos as root via `sudo -n`, but the orchestrator
    runs `git status` / `git show` as the regular sandbox user. Without
    `safe.directory='*'`, git refuses to touch repos owned by a different
    user with "fatal: detected dubious ownership". We disable that check
    universally for orchestrator-issued reads — the orchestrator is the
    only thing inside the sandbox interpreting these repos."""
    return [
        "git",
        "-c",
        "safe.directory=*",
        "-C",
        repo_path,
        *args,
    ]


def _provider(request: Request) -> SandboxProvider:
    p = getattr(request.app.state, "sandbox_provider", None)
    if p is None:
        raise RuntimeError("sandbox_provider not initialized on app.state")
    return p  # type: ignore[no-any-return]


async def _load_owned(sandbox_id: PydanticObjectId, user: User) -> Sandbox:
    doc = await Sandbox.get(sandbox_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="sandbox not found")
    if not doc.provider_handle:
        raise HTTPException(status_code=409, detail="sandbox not provisioned")
    return doc


def _validate_repo_path(p: str) -> str:
    """Repo paths must be `/work/<owner>/<repo>` — exactly two segments
    under `/work`. Catches traversal AND nonsense paths server-side; the
    git binary would reject most of these, but it's cheaper + safer to
    reject here."""
    if not p.startswith("/work/"):
        raise HTTPException(status_code=400, detail="repo_path must start with /work/")
    if "\x00" in p or ".." in p.split("/"):
        raise HTTPException(status_code=400, detail="invalid repo_path")
    parts = p.removeprefix("/work/").rstrip("/").split("/")
    if len(parts) != 2 or not all(parts):
        raise HTTPException(
            status_code=400,
            detail="repo_path must be /work/<owner>/<repo>",
        )
    return f"/work/{parts[0]}/{parts[1]}"


def _validate_rel_path(p: str) -> str:
    """Relative paths must not escape via `..` and must not be absolute."""
    if not p:
        raise HTTPException(status_code=400, detail="rel_path required")
    if p.startswith("/"):
        raise HTTPException(status_code=400, detail="rel_path must be relative")
    if "\x00" in p or ".." in p.split("/"):
        raise HTTPException(status_code=400, detail="invalid rel_path")
    return p


def _to_handle(doc: Sandbox):  # type: ignore[no-untyped-def]
    from sandbox_provider import SandboxHandle

    return SandboxHandle(provider=doc.provider_name, payload=dict(doc.provider_handle))


# ── GET /api/sandboxes/{id}/git/status ───────────────────────────────────


@router.get("/{sandbox_id}/git/status", response_model=GitStatusResponse)
async def git_status(
    sandbox_id: PydanticObjectId,
    request: Request,
    repo_path: str = Query(..., min_length=1),
    user: User = Depends(require_user),
) -> GitStatusResponse:
    canonical = _validate_repo_path(repo_path)
    doc = await _load_owned(sandbox_id, user)
    provider = _provider(request)
    handle = _to_handle(doc)
    try:
        result = await provider.exec_oneshot(
            handle,
            _git_argv(canonical, "status", "--porcelain=v1", "-b", "-z"),
            env={},
            cwd=canonical,
            timeout_s=_GIT_TIMEOUT_S,
        )
    except SpritesError as exc:
        logger.warning("git.status_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # Always log the raw command + outcome so the user can see exactly
    # what `git status` thought of their tree. Helps diagnose "I edited a
    # file and it doesn't show up" — the FE only sees the parsed result.
    logger.info(
        "git.status_raw",
        repo_path=canonical,
        exit_code=result.exit_code,
        stdout_len=len(result.stdout),
        # NUL-separated; replace for log readability. If this is empty
        # AND exit_code==0, git really sees a clean tree — meaning either
        # the file save didn't reach disk OR it landed at a different
        # path than expected.
        stdout_preview=result.stdout.replace("\x00", "|")[:500],
        stderr_preview=result.stderr[:200],
    )
    if result.exit_code != 0:
        # Anything that fails (not a repo, repo half-cloned, fatal: ..., a
        # path that doesn't exist yet, etc.) returns an empty status — the
        # FE should render an inline "git error" banner per-repo rather
        # than silently showing "no changes". We never 502 for a per-repo
        # problem since one bad repo would poison the whole panel.
        err = (result.stderr or result.stdout).strip()[:300] or (
            f"git status exit {result.exit_code}"
        )
        logger.info(
            "git.status_exit_nonzero",
            repo_path=canonical,
            exit_code=result.exit_code,
            stderr=err,
        )
        return GitStatusResponse(
            repo_path=canonical,
            branch=None,
            detached=False,
            ahead=0,
            behind=0,
            files=[],
            git_error=err,
        )
    return _parse_porcelain_v1(canonical, result.stdout)


def _parse_porcelain_v1(repo_path: str, raw: str) -> GitStatusResponse:
    """Parse `git status --porcelain=v1 -b -z`. The `-z` flag uses NUL
    separators and disables `\\` quoting, which is the only safe way to
    handle paths with spaces / unicode."""
    branch: str | None = None
    detached = False
    ahead = 0
    behind = 0
    files: list[GitStatusFile] = []

    # Records are NUL-terminated. The first record is the branch line.
    # Renames span TWO records (status + new path \0 old path).
    records = raw.split("\x00")
    if not records or records[-1] == "":
        records = records[:-1]
    if not records:
        return GitStatusResponse(
            repo_path=repo_path, branch=None, detached=False, ahead=0, behind=0, files=[]
        )
    first = records[0]
    rest = records[1:]
    if first.startswith("## "):
        line = first[3:]
        if line.startswith("HEAD (no branch)"):
            detached = True
        else:
            # `branch...remote [ahead N, behind M]`
            head, _, tracking = line.partition("...")
            branch = head
            if tracking and "[" in tracking:
                inside = tracking.split("[", 1)[1].rstrip("]")
                for part in inside.split(", "):
                    part = part.strip()
                    if part.startswith("ahead "):
                        ahead = int(part.removeprefix("ahead ") or 0)
                    elif part.startswith("behind "):
                        behind = int(part.removeprefix("behind ") or 0)
    else:
        # First record was already a file entry — branch info absent.
        rest = records

    i = 0
    while i < len(rest):
        rec = rest[i]
        if not rec or len(rec) < 4:
            i += 1
            continue
        idx, wt, sep_path = rec[0], rec[1], rec[3:]
        # Renames consume the next record as the OLD path.
        is_rename = idx == "R" or wt == "R"
        rel_path_orig: str | None = None
        if is_rename and i + 1 < len(rest):
            rel_path_orig = rest[i + 1]
            i += 2
        else:
            i += 1
        files.append(
            GitStatusFile(
                rel_path=sep_path,
                index=idx,
                worktree=wt,
                rel_path_orig=rel_path_orig,
            )
        )

    return GitStatusResponse(
        repo_path=repo_path,
        branch=branch,
        detached=detached,
        ahead=ahead,
        behind=behind,
        files=files,
    )


# ── GET /api/sandboxes/{id}/git/show ─────────────────────────────────────


@router.get("/{sandbox_id}/git/show", response_model=GitShowResponse)
async def git_show(
    sandbox_id: PydanticObjectId,
    request: Request,
    repo_path: str = Query(..., min_length=1),
    rel_path: str = Query(..., min_length=1),
    ref: str = Query("HEAD"),
    user: User = Depends(require_user),
) -> GitShowResponse:
    canonical_repo = _validate_repo_path(repo_path)
    canonical_rel = _validate_rel_path(rel_path)
    if not _is_safe_ref(ref):
        raise HTTPException(status_code=400, detail="invalid ref")
    doc = await _load_owned(sandbox_id, user)
    provider = _provider(request)
    handle = _to_handle(doc)
    spec = f"{ref}:{canonical_rel}"
    try:
        result = await provider.exec_oneshot(
            handle,
            _git_argv(canonical_repo, "show", spec),
            env={},
            cwd=canonical_repo,
            timeout_s=_GIT_TIMEOUT_S,
        )
    except SpritesError as exc:
        logger.warning("git.show_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if result.exit_code != 0:
        # Path doesn't exist at this ref — return exists=False so the FE
        # renders an empty-vs-current diff (i.e. the file was added).
        return GitShowResponse(
            repo_path=canonical_repo,
            rel_path=canonical_rel,
            ref=ref,
            exists=False,
            content="",
            truncated=False,
        )
    raw = result.stdout
    truncated = False
    if len(raw.encode("utf-8", errors="replace")) > _MAX_SHOW_BYTES:
        # Cap at the editor limit; the FE will show a "too large to diff"
        # banner when truncated=True.
        raw = raw.encode("utf-8", errors="replace")[:_MAX_SHOW_BYTES].decode(
            "utf-8", errors="replace"
        )
        truncated = True
    return GitShowResponse(
        repo_path=canonical_repo,
        rel_path=canonical_rel,
        ref=ref,
        exists=True,
        content=raw,
        truncated=truncated,
    )


def _is_safe_ref(ref: str) -> bool:
    """Whitelist refs to forms we expect — `HEAD`, `HEAD~N`, branch/tag
    names, short SHAs. Rejects anything that could shell-escape (we pass
    via argv so this is belt-and-braces; git itself enforces the ref
    grammar, but a server-side guard prevents weirdness like NUL bytes)."""
    if not ref or "\x00" in ref or ".." in ref:
        return False
    if any(ch.isspace() for ch in ref):
        return False
    return all(ch.isalnum() or ch in "-_/.~^@" for ch in ref)
