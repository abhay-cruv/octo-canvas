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

import asyncio

from beanie import PydanticObjectId
from db import mongo
from db.models import Repo, Sandbox, User
from fastapi import APIRouter, Depends, HTTPException, status
from shared_models.sandbox import SandboxResponse

from ..lib.logger import logger
from ..middleware.auth import require_user
from ..services.reconciliation import Reconciler
from ..services.sandbox_manager import (
    IllegalSandboxTransitionError,
    SandboxManager,
)
from .deps import get_reconciler, get_sandbox_manager

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
        activity=doc.activity,
        activity_detail=doc.activity_detail,
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


_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def _cancel_tasks_with_prefix(sandbox_id: PydanticObjectId, prefix: str) -> int:
    """Cancel every background task whose name starts with `<prefix>-<id>`.
    Used to override one user intent with another — e.g. pause cancels
    in-flight reconcile, wake cancels in-flight pause-resync (so the
    delayed status pull doesn't flip the just-woken sprite back to cold)."""
    target = f"{prefix}-{sandbox_id}"
    cancelled = 0
    for task in list(_BACKGROUND_TASKS):
        if task.get_name() == target and not task.done():
            task.cancel()
            cancelled += 1
    return cancelled


def _cancel_reconcile_for(sandbox_id: PydanticObjectId) -> int:
    return _cancel_tasks_with_prefix(sandbox_id, "reconcile")


def _cancel_pause_resync_for(sandbox_id: PydanticObjectId) -> int:
    return _cancel_tasks_with_prefix(sandbox_id, "pause-resync")


RECONCILE_WALL_CLOCK_TIMEOUT_S = 900  # 15 min: enough for clone + apt-install


def _kick_reconcile(reconciler: Reconciler, sandbox_id: PydanticObjectId) -> None:
    """Schedule a reconciliation pass without awaiting it. The HTTP
    response returns immediately; clone progress shows up via REST
    polling on `/api/repos`. The per-sandbox lock inside `Reconciler`
    handles concurrent triggers. We hold a strong reference in
    `_BACKGROUND_TASKS` so asyncio doesn't gc the task mid-run.

    Wall-clock timeout: 15 minutes. If the reconcile is still running
    past that, kill it and let the reconciler's top-level safety net
    mark any pending/cloning repos as failed. Without this, a hung
    `exec_oneshot` (websocket stuck on Sprites' side, etc.) would
    leave repos at `pending` forever and FE polling would never stop.
    """

    async def _run() -> None:
        try:
            await asyncio.wait_for(
                reconciler.reconcile(sandbox_id),
                timeout=RECONCILE_WALL_CLOCK_TIMEOUT_S,
            )
        except TimeoutError:
            logger.warning(
                "reconcile.wall_clock_timeout",
                sandbox_id=str(sandbox_id),
                timeout_s=RECONCILE_WALL_CLOCK_TIMEOUT_S,
            )
            # The reconciler's own safety net runs only on exceptions
            # that bubble out of `_run`. The wait_for cancellation
            # interrupts it from outside, so clean up state here.
            await mongo.repos.update_many(
                {
                    "sandbox_id": sandbox_id,
                    "clone_status": {"$in": ["pending", "cloning"]},
                },
                {
                    "$set": {
                        "clone_status": "failed",
                        "clone_error": "reconcile timed out after 15min",
                    }
                },
            )
            await mongo.sandboxes.update_one(
                {"_id": sandbox_id},
                {"$set": {"activity": None, "activity_detail": None}},
            )
        except Exception as exc:
            logger.warning(
                "reconcile.background_failed",
                sandbox_id=str(sandbox_id),
                error=str(exc),
            )

    task = asyncio.create_task(_run(), name=f"reconcile-{sandbox_id}")
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


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
    reconciler: Reconciler = Depends(get_reconciler),
) -> SandboxResponse:
    """Return the user's existing non-destroyed sandbox or provision a fresh
    one. Idempotent: a second call with no destroy in between returns the
    same doc. The returned status reflects what the provider just gave us
    (typically `warm` immediately after create).

    On *fresh provision* (not the idempotent return-existing path), bind
    every `sandbox_id=null` `Repo` row owned by this user to the new
    sandbox and kick off reconciliation in the background — clones are
    network-bound, the HTTP response shouldn't block on them."""
    if user.id is None:
        raise RuntimeError("user.id is None")
    pre_existing = await Sandbox.find(
        Sandbox.user_id == user.id, {"status": {"$ne": "destroyed"}}
    ).first_or_none()
    doc = await manager.get_or_create(user.id)
    _bad_provider_if_failed(doc)
    if pre_existing is None and doc.id is not None:
        # Raw `update_many` to avoid the silent-noop trap with Beanie's
        # `find().update()` chain.
        await mongo.repos.update_many(
            {
                "user_id": user.id,
                "sandbox_id": None,
                "clone_status": {"$ne": "ready"},
            },
            {"$set": {"sandbox_id": doc.id, "clone_status": "pending"}},
        )
        _kick_reconcile(reconciler, doc.id)
    return _to_response(doc)


@router.post("/{sandbox_id}/wake", response_model=SandboxResponse)
async def wake_sandbox(
    sandbox_id: PydanticObjectId,
    user: User = Depends(require_user),
    manager: SandboxManager = Depends(get_sandbox_manager),
    reconciler: Reconciler = Depends(get_reconciler),
) -> SandboxResponse:
    # If the user clicked Start while a pause-resync is still polling,
    # kill it — otherwise its delayed status read would clobber the
    # just-woken state back to whatever Sprites is reporting at that
    # instant (potentially still "cold"). Clear the "pausing" banner
    # too so the FE stops showing the stale message.
    pause_cancelled = _cancel_pause_resync_for(sandbox_id)
    if pause_cancelled:
        logger.info(
            "sandbox.wake.cancelled_pause_resync",
            sandbox_id=str(sandbox_id),
            count=pause_cancelled,
        )
    doc = await _load_owned(sandbox_id, user)
    if doc.activity == "pausing":
        doc.activity = None
        doc.activity_detail = None
        await doc.save()
    try:
        doc = await manager.wake(doc)
    except IllegalSandboxTransitionError as exc:
        raise _conflict(exc) from exc
    _bad_provider_if_failed(doc)
    # If any repo for this sandbox needs work, schedule reconciliation.
    # No-op for sandboxes whose repos are all `ready`.
    if doc.id is not None:
        # Wake is the user-explicit "start working" signal — it's the
        # right place to retry previously-failed clones once. Flip every
        # `failed` repo for this sandbox back to `pending` so the
        # reconciler picks them up alongside genuine pending/orphan
        # work. The earlier no-auto-retry rule is preserved on Refresh /
        # passive polls; only Wake retries.
        await mongo.repos.update_many(
            {"sandbox_id": doc.id, "clone_status": "failed"},
            {"$set": {"clone_status": "pending", "clone_error": None}},
        )

        needs_work = await Repo.find(
            Repo.user_id == user.id,
            {
                "$or": [
                    {"sandbox_id": None},
                    {
                        "sandbox_id": doc.id,
                        "clone_status": {"$in": ["pending", "cloning"]},
                    },
                ]
            },
        ).first_or_none()
        if needs_work is not None:
            _kick_reconcile(reconciler, doc.id)
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
    is preserved; user pays for storage only while paused.

    First cancels any in-flight reconciliation for this sandbox —
    otherwise the reconciler's `exec_oneshot` calls (apt-install,
    git clone) would keep the sprite warm and fight the pause.

    Sprites doesn't expose a force-cold verb — it idles the sprite
    after exec sessions close. The status returned here may still be
    `warm` immediately. We schedule a couple of background re-syncs so
    the doc converges to `cold` once Sprites has actually idled.
    """
    cancelled = _cancel_reconcile_for(sandbox_id)
    if cancelled:
        logger.info(
            "sandbox.pause.cancelled_reconcile",
            sandbox_id=str(sandbox_id),
            count=cancelled,
        )
    doc = await _load_owned(sandbox_id, user)
    try:
        doc = await manager.pause(doc)
    except IllegalSandboxTransitionError as exc:
        raise _conflict(exc) from exc
    _bad_provider_if_failed(doc)
    _schedule_post_pause_refresh(manager, sandbox_id)
    return _to_response(doc)


def _schedule_post_pause_refresh(manager: SandboxManager, sandbox_id: PydanticObjectId) -> None:
    """Re-sync the sandbox's live status a few times after pause so the
    Mongo doc converges to `cold` once Sprites has actually idled. The
    user's UI polls Mongo via `GET /api/sandboxes`; this is what makes
    the pill flip from "warm (releasing)" to "cold"."""

    async def _resync_loop() -> None:
        for delay in (5.0, 15.0, 45.0):
            await asyncio.sleep(delay)
            doc = await Sandbox.get(sandbox_id)
            if doc is None or doc.status in ("destroyed", "cold"):
                return
            try:
                await manager.refresh_status(doc)
            except Exception as exc:
                logger.warning(
                    "sandbox.pause.resync_failed",
                    sandbox_id=str(sandbox_id),
                    error=str(exc),
                )
                return

    task = asyncio.create_task(_resync_loop(), name=f"pause-resync-{sandbox_id}")
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


@router.post("/{sandbox_id}/refresh", response_model=SandboxResponse)
async def refresh_sandbox(
    sandbox_id: PydanticObjectId,
    user: User = Depends(require_user),
    manager: SandboxManager = Depends(get_sandbox_manager),
    reconciler: Reconciler = Depends(get_reconciler),
) -> SandboxResponse:
    """Resync live status from the provider (cold/warm/running). Useful on
    page focus to reflect Sprites' auto-hibernation without polling.

    Refresh does NOT auto-kick reconciliation any more — it used to, but
    that combined with FE polling created a feedback loop where any
    repeatedly-failing clone would keep waking the sprite. Reconciliation
    fires from explicit user actions (provision, wake, connect, retry
    clone) and not from passive status polls.
    """
    doc = await _load_owned(sandbox_id, user)
    doc = await manager.refresh_status(doc)
    _bad_provider_if_failed(doc)
    _ = reconciler  # kept on the signature so the FE keeps the same call
    return _to_response(doc)


@router.post("/{sandbox_id}/reset", response_model=SandboxResponse)
async def reset_sandbox(
    sandbox_id: PydanticObjectId,
    user: User = Depends(require_user),
    manager: SandboxManager = Depends(get_sandbox_manager),
    reconciler: Reconciler = Depends(get_reconciler),
) -> SandboxResponse:
    doc = await _load_owned(sandbox_id, user)
    if doc.id is None:
        raise RuntimeError("sandbox.id is None")
    sandbox_oid = doc.id

    # Flip repos to `pending` BEFORE manager.reset runs (rather than
    # after). Two reasons:
    #   1. The bulk update fires unconditionally — no risk of being
    #      gated out by a status-check edge case.
    #   2. The FE invalidation that fires when this route returns
    #      reads the post-flip state, so the dashboard immediately
    #      shows `pending` even on the fast checkpoint path. Whatever
    #      the reconciler does next (self-heal back to ready, or
    #      re-clone) is the second observable transition.
    upd = await mongo.repos.update_many(
        {"sandbox_id": sandbox_oid},
        {
            "$set": {
                "clone_status": "pending",
                "clone_error": None,
                "clone_path": None,
            }
        },
    )
    logger.info(
        "sandbox.reset.repos_flipped_pending",
        sandbox_id=str(sandbox_oid),
        matched=upd.matched_count,
        modified=upd.modified_count,
    )

    try:
        doc = await manager.reset(doc)
    except IllegalSandboxTransitionError as exc:
        raise _conflict(exc) from exc
    _bad_provider_if_failed(doc)
    # Reconcile self-heals:
    #   - repos on disk → flip back to `ready`
    #   - repos missing → re-clone (git_setup runs first if needed)
    if doc.status in ("cold", "warm", "running"):
        _kick_reconcile(reconciler, sandbox_oid)
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
    # Slice 5b: clone state was owned by the destroyed sandbox. Repos go
    # back to `pending` (they live on as `Repo` rows but with no sandbox).
    # User can re-provision and the new sandbox will re-clone them.
    if doc.id is not None:
        await mongo.repos.update_many(
            {"sandbox_id": doc.id},
            {"$set": {"sandbox_id": None, "clone_status": "pending", "clone_path": None}},
        )
    return _to_response(doc)
