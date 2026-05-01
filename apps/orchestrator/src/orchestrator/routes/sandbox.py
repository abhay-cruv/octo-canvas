"""Sandbox provisioning endpoints (slice 4).

Path-parameterized from day one (`/api/sandboxes/{sandbox_id}/...`) so the
multi-sandbox future per Plan.md §4 doesn't need a route rename. v1
enforces "one running per user" inside `SandboxManager.get_or_create`, not
in the URL.

No `hibernate` endpoint — Sprites auto-hibernates after idle. The user-facing
"Pause" button is gone in slice 4; users see live status (`cold` ≡ "Paused")
on the dashboard. Wake is kept as an explicit "start a session now"
affordance; Refresh resyncs live status from the provider.
"""

from beanie import PydanticObjectId
from db.models import Sandbox, User
from fastapi import APIRouter, Depends, HTTPException, status
from shared_models.sandbox import SandboxResponse

from ..lib.logger import logger
from ..middleware.auth import require_user
from ..services.sandbox_manager import (
    IllegalSandboxTransitionError,
    SandboxManager,
)
from .deps import get_sandbox_manager

router = APIRouter()


def _to_response(doc: Sandbox) -> SandboxResponse:
    if doc.id is None:
        raise RuntimeError("sandbox doc has no id")
    return SandboxResponse(
        id=str(doc.id),
        user_id=str(doc.user_id),
        provider_name=doc.provider_name,
        status=doc.status,
        public_url=doc.public_url,
        last_active_at=doc.last_active_at,
        spawned_at=doc.spawned_at,
        destroyed_at=doc.destroyed_at,
        last_reset_at=doc.last_reset_at,
        reset_count=doc.reset_count,
        failure_reason=doc.failure_reason,
        created_at=doc.created_at,
    )


async def _load_owned(sandbox_id: PydanticObjectId, user: User) -> Sandbox:
    doc = await Sandbox.get(sandbox_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sandbox not found")
    return doc


def _conflict(exc: IllegalSandboxTransitionError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _bad_provider_if_failed(doc: Sandbox) -> None:
    """If a transition flipped status to `failed`, surface 502 to the
    caller. The doc is already persisted with the failure reason."""
    if doc.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=doc.failure_reason or "sandbox provider error",
        )


@router.get("", response_model=list[SandboxResponse])
async def list_sandboxes(
    user: User = Depends(require_user),
    manager: SandboxManager = Depends(get_sandbox_manager),
) -> list[SandboxResponse]:
    if user.id is None:
        raise RuntimeError("user.id is None")
    docs = await manager.list_for_user(user.id)
    return [_to_response(d) for d in docs]


@router.post("", response_model=SandboxResponse)
async def get_or_create_sandbox(
    user: User = Depends(require_user),
    manager: SandboxManager = Depends(get_sandbox_manager),
) -> SandboxResponse:
    """Return the user's existing non-destroyed sandbox or provision a fresh
    one. Idempotent: a second call with no destroy in between returns the
    same doc. The returned status reflects what the provider just gave us
    (typically `warm` immediately after create)."""
    if user.id is None:
        raise RuntimeError("user.id is None")
    doc = await manager.get_or_create(user.id)
    _bad_provider_if_failed(doc)
    return _to_response(doc)


@router.post("/{sandbox_id}/wake", response_model=SandboxResponse)
async def wake_sandbox(
    sandbox_id: PydanticObjectId,
    user: User = Depends(require_user),
    manager: SandboxManager = Depends(get_sandbox_manager),
) -> SandboxResponse:
    doc = await _load_owned(sandbox_id, user)
    try:
        doc = await manager.wake(doc)
    except IllegalSandboxTransitionError as exc:
        raise _conflict(exc) from exc
    _bad_provider_if_failed(doc)
    logger.info("sandbox.wake_returned", sandbox_id=str(doc.id), status=doc.status)
    return _to_response(doc)


@router.post("/{sandbox_id}/pause", response_model=SandboxResponse)
async def pause_sandbox(
    sandbox_id: PydanticObjectId,
    user: User = Depends(require_user),
    manager: SandboxManager = Depends(get_sandbox_manager),
) -> SandboxResponse:
    """Force the sandbox to release compute. Kills active exec sessions
    so Sprites' idle timer can transition the sprite to `cold`. Filesystem
    is preserved; user pays for storage only while paused."""
    doc = await _load_owned(sandbox_id, user)
    try:
        doc = await manager.pause(doc)
    except IllegalSandboxTransitionError as exc:
        raise _conflict(exc) from exc
    _bad_provider_if_failed(doc)
    return _to_response(doc)


@router.post("/{sandbox_id}/refresh", response_model=SandboxResponse)
async def refresh_sandbox(
    sandbox_id: PydanticObjectId,
    user: User = Depends(require_user),
    manager: SandboxManager = Depends(get_sandbox_manager),
) -> SandboxResponse:
    """Resync live status from the provider (cold/warm/running). Useful on
    page focus to reflect Sprites' auto-hibernation without polling."""
    doc = await _load_owned(sandbox_id, user)
    doc = await manager.refresh_status(doc)
    _bad_provider_if_failed(doc)
    return _to_response(doc)


@router.post("/{sandbox_id}/reset", response_model=SandboxResponse)
async def reset_sandbox(
    sandbox_id: PydanticObjectId,
    user: User = Depends(require_user),
    manager: SandboxManager = Depends(get_sandbox_manager),
) -> SandboxResponse:
    doc = await _load_owned(sandbox_id, user)
    try:
        doc = await manager.reset(doc)
    except IllegalSandboxTransitionError as exc:
        raise _conflict(exc) from exc
    _bad_provider_if_failed(doc)
    return _to_response(doc)


@router.post("/{sandbox_id}/destroy", response_model=SandboxResponse)
async def destroy_sandbox(
    sandbox_id: PydanticObjectId,
    user: User = Depends(require_user),
    manager: SandboxManager = Depends(get_sandbox_manager),
) -> SandboxResponse:
    doc = await _load_owned(sandbox_id, user)
    try:
        doc = await manager.destroy(doc)
    except IllegalSandboxTransitionError as exc:
        raise _conflict(exc) from exc
    return _to_response(doc)
