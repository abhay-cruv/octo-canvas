"""Per-sandbox filesystem REST surface (slice 6).

The IDE file tree + Monaco editor live on top of these endpoints. Auth +
ownership ride on `require_user`; **path validation is server-side only**
(see slice6.md §risk #7) — never trust the FE.

The set of paths the orchestrator allows is `/work` and everything beneath
it. We reject `..`, encoded `..`, absolute paths outside `/work`, null
bytes. Symlink resolution is the provider's responsibility (Sprites does
it server-side); the orchestrator does not stat-resolve.
"""

import hashlib
import posixpath
from typing import Annotated, Literal

from beanie import PydanticObjectId
from db.models import Sandbox, User
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sandbox_provider import SandboxProvider, SpritesError
from shared_models.sandbox_fs import (
    FsEntryDto,
    FsFileResponse,
    FsListResponse,
    FsReadResponse,
    FsRenameRequest,
    FsRenameResponse,
    FsWriteRequest,
    FsWriteResponse,
)

from ..lib.logger import logger
from ..middleware.auth import require_user

router = APIRouter()


_FS_ROOT = "/work"
_MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB — IDE caps; bigger files use the terminal.


def _sandbox_provider(request: Request) -> SandboxProvider:
    provider = getattr(request.app.state, "sandbox_provider", None)
    if provider is None:
        raise RuntimeError("sandbox_provider not initialized on app.state")
    return provider  # type: ignore[no-any-return]


def _validate_path(raw: str) -> str:
    """Reject anything that escapes `/work` after normalization. Returns
    the canonical absolute path. Raises HTTPException(400) on rejection."""
    if not raw:
        raise HTTPException(status_code=400, detail="path is required")
    if "\x00" in raw:
        raise HTTPException(status_code=400, detail="path contains null byte")
    if not raw.startswith("/"):
        raise HTTPException(status_code=400, detail="path must be absolute")
    # `posixpath.normpath` collapses `..` and `.` segments — validate the
    # NORMALIZED path, not the raw input, so `/work/../etc/passwd` becomes
    # `/etc/passwd` and fails the prefix check below.
    normalized = posixpath.normpath(raw)
    # `normpath` strips trailing `/` — re-anchor.
    if not normalized.startswith(_FS_ROOT):
        raise HTTPException(status_code=400, detail="path must be under /work")
    if normalized != _FS_ROOT and not normalized.startswith(_FS_ROOT + "/"):
        # Defensive — `/workspace` would pass the loose prefix check above.
        raise HTTPException(status_code=400, detail="path must be under /work")
    return normalized


async def _load_owned(sandbox_id: PydanticObjectId, user: User) -> Sandbox:
    doc = await Sandbox.get(sandbox_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="sandbox not found")
    if not doc.provider_handle:
        raise HTTPException(status_code=409, detail="sandbox not provisioned")
    return doc


def _to_handle(doc: Sandbox):  # type: ignore[no-untyped-def]
    from sandbox_provider import SandboxHandle

    return SandboxHandle(provider=doc.provider_name, payload=dict(doc.provider_handle or {}))


def _sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _decode_text(content: bytes) -> str:
    """Reject anything that isn't valid UTF-8 — Monaco only renders text in
    slice 6. The FE shows a 'binary file' placeholder when this 415s."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=415,
            detail="file is not valid UTF-8 (binary not supported in slice 6)",
        ) from exc


# ── GET /api/sandboxes/{id}/fs?path=...&list=false ───────────────────────


@router.get("/{sandbox_id}/fs", response_model=FsReadResponse)
async def fs_get(
    sandbox_id: PydanticObjectId,
    request: Request,
    path: str = Query(..., min_length=1),
    list_dir: bool = Query(False, alias="list"),
    user: User = Depends(require_user),
) -> FsReadResponse:
    """Read a file (`list=false`, default) or list a directory (`list=true`).
    Returned discriminated response is `FsFileResponse | FsListResponse`."""
    canonical = _validate_path(path)
    doc = await _load_owned(sandbox_id, user)
    provider = _sandbox_provider(request)
    handle = _to_handle(doc)
    try:
        if list_dir:
            entries = await provider.fs_list(handle, canonical)
            return FsListResponse(
                path=canonical,
                entries=[FsEntryDto(name=e.name, type=e.kind, size=e.size) for e in entries],
            )
        content = await provider.fs_read(handle, canonical)
    except SpritesError as exc:
        raise _provider_error(exc) from exc
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds {_MAX_FILE_BYTES} bytes (slice 6 cap)",
        )
    text = _decode_text(content)
    return FsFileResponse(
        path=canonical,
        content=text,
        sha=_sha256_hex(content),
        size=len(content),
    )


# ── PUT /api/sandboxes/{id}/fs?path=... ──────────────────────────────────


@router.put("/{sandbox_id}/fs", response_model=FsWriteResponse)
async def fs_put(
    sandbox_id: PydanticObjectId,
    body: FsWriteRequest,
    request: Request,
    path: str = Query(..., min_length=1),
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    user: User = Depends(require_user),
) -> FsWriteResponse:
    """Write a file. If the path already exists, callers MUST send
    `If-Match: <sha>` matching the current contents — mismatches return
    412 Precondition Failed. New-file create is allowed without If-Match.
    """
    canonical = _validate_path(path)
    doc = await _load_owned(sandbox_id, user)
    provider = _sandbox_provider(request)
    handle = _to_handle(doc)

    # Compute current sha for the if-match check. Treat NotFound as
    # "doesn't exist yet" — first write is allowed without an If-Match.
    current: bytes | None
    try:
        current = await provider.fs_read(handle, canonical)
    except SpritesError as exc:
        if "not found" in str(exc).lower():
            current = None
        else:
            raise _provider_error(exc) from exc

    if current is not None:
        expected = _strip_etag(if_match)
        if expected is None:
            raise HTTPException(status_code=428, detail="If-Match header required to overwrite")
        actual = _sha256_hex(current)
        if expected != actual:
            raise HTTPException(
                status_code=412,
                detail={"reason": "sha mismatch", "current_sha": actual},
            )

    payload = body.content.encode("utf-8")
    if len(payload) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"file exceeds {_MAX_FILE_BYTES} bytes")

    try:
        size = await provider.fs_write(handle, canonical, payload)
    except SpritesError as exc:
        raise _provider_error(exc) from exc

    return FsWriteResponse(path=canonical, sha=_sha256_hex(payload), size=size)


# ── DELETE /api/sandboxes/{id}/fs?path=... ───────────────────────────────


@router.delete("/{sandbox_id}/fs", status_code=status.HTTP_204_NO_CONTENT)
async def fs_delete(
    sandbox_id: PydanticObjectId,
    request: Request,
    path: str = Query(..., min_length=1),
    recursive: bool = Query(False),
    user: User = Depends(require_user),
) -> None:
    canonical = _validate_path(path)
    if canonical == _FS_ROOT:
        raise HTTPException(status_code=400, detail="refusing to delete /work")
    doc = await _load_owned(sandbox_id, user)
    provider = _sandbox_provider(request)
    handle = _to_handle(doc)
    try:
        await provider.fs_delete(handle, canonical, recursive=recursive)
    except SpritesError as exc:
        raise _provider_error(exc) from exc


# ── POST /api/sandboxes/{id}/fs?path=...&op=rename ───────────────────────


@router.post("/{sandbox_id}/fs", response_model=FsRenameResponse)
async def fs_post(
    sandbox_id: PydanticObjectId,
    body: FsRenameRequest,
    request: Request,
    path: str = Query(..., min_length=1),
    op: Literal["rename"] = Query(...),
    user: User = Depends(require_user),
) -> FsRenameResponse:
    """Path-mutation operations. v1 supports `op=rename`; copy/chmod can
    join later without changing the URL."""
    src = _validate_path(path)
    dst = _validate_path(body.new_path)
    if op != "rename":
        raise HTTPException(status_code=400, detail=f"unsupported op {op!r}")
    doc = await _load_owned(sandbox_id, user)
    provider = _sandbox_provider(request)
    handle = _to_handle(doc)
    try:
        await provider.fs_rename(handle, src, dst)
    except SpritesError as exc:
        raise _provider_error(exc) from exc
    return FsRenameResponse(path=src, new_path=dst)


# ── helpers ──────────────────────────────────────────────────────────────


def _strip_etag(header: str | None) -> str | None:
    """Accept both quoted (`"abc"`) and bare (`abc`) ETag forms — strict
    HTTP says quoted, but devtools and curl users send bare strings."""
    if header is None:
        return None
    return header.strip().strip('"') or None


def _provider_error(exc: SpritesError) -> HTTPException:
    msg = str(exc)
    if "not found" in msg.lower():
        return HTTPException(status_code=404, detail=msg)
    logger.warning("sandbox_fs.provider_error", error=msg, retriable=exc.retriable)
    return HTTPException(status_code=502, detail=msg)
