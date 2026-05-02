"""Application-level layer over `SandboxProvider`.

Encapsulates the v1 routing rule "one running sandbox per user" and the
state-machine for our sandbox doc. The provider interface is opaque — this
layer never reaches into `provider_handle.payload`.

State machine (see [slice4.md §5](../../../../docs/slice/slice4.md)):

    none-doc → POST /api/sandboxes → provisioning
    provisioning → provider.create succeeds → cold | warm | running
    provisioning → provider.create fails → failed

    cold | warm | running → POST .../wake → running (force-warm via no-op exec)
    cold | warm | running → POST .../reset → resetting → provisioning → ...
    cold | warm | running → POST .../destroy → destroyed
    failed → reset → resetting → provisioning → ...
    failed → destroy → destroyed

Sprites auto-hibernates after idle. We resync the live status from the
provider via `refresh_status` (called from routes that read state).

Mongo is the source of truth. Redis is a hot cache only — never read sandbox
state from Redis as primary in this slice. Slice 5a's WS hot path will read
from Redis for sticky-routing decisions.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from beanie import PydanticObjectId
from db.models import Sandbox
from sandbox_provider import SandboxHandle, SandboxProvider, SpritesError
from shared_models.sandbox import SandboxStatus

if TYPE_CHECKING:
    from redis.asyncio.client import Redis

_logger = structlog.get_logger("sandbox_manager")

# Statuses from which the corresponding action is legal. The route layer
# maps violations to HTTP 409. Keep these in lock-step with the table in
# [slice4.md §5](../../../../docs/slice/slice4.md).
_ALIVE: tuple[SandboxStatus, ...] = ("cold", "warm", "running")
_WAKE_FROM: tuple[SandboxStatus, ...] = _ALIVE
_PAUSE_FROM: tuple[SandboxStatus, ...] = _ALIVE  # pause on cold is a no-op
_RESET_FROM: tuple[SandboxStatus, ...] = (*_ALIVE, "failed")
_DESTROY_FROM: tuple[SandboxStatus, ...] = (*_ALIVE, "failed", "provisioning")


class IllegalSandboxTransitionError(Exception):
    """Raised when a state transition is rejected by the matrix. Routes map
    this to HTTP 409."""

    def __init__(self, from_status: SandboxStatus, action: str) -> None:
        super().__init__(f"cannot {action} a sandbox in status {from_status!r}")
        self.from_status = from_status
        self.action = action


def _now() -> datetime:
    return datetime.now(UTC)


def _handle_of(sandbox: Sandbox) -> SandboxHandle:
    """Reconstruct the provider handle from persisted fields."""
    return SandboxHandle(
        provider=sandbox.provider_name,
        payload=dict(sandbox.provider_handle),
    )


class SandboxManager:
    def __init__(self, provider: SandboxProvider, redis: "Redis | None") -> None:
        self._provider = provider
        self._redis = redis

    @property
    def provider_name(self) -> str:
        return self._provider.name

    # ── Lookup ────────────────────────────────────────────────────────────

    async def get_or_create(self, user_id: PydanticObjectId) -> Sandbox:
        """Return the user's most-recent non-`destroyed` sandbox, creating
        one with `status='provisioning'` AND calling `provider.create()` if
        none exists. Idempotent on the second call (returns the existing
        doc rather than provisioning a second sprite)."""
        existing = (
            await Sandbox.find(
                Sandbox.user_id == user_id,
                {"status": {"$ne": "destroyed"}},
            )
            .sort("-created_at")
            .first_or_none()
        )
        if existing is not None:
            return existing
        doc = Sandbox(user_id=user_id, provider_name=self._provider.name)
        await doc.create()
        _logger.info("sandbox.created", sandbox_id=str(doc.id), user_id=str(user_id))
        return await self._provision(doc)

    async def list_for_user(self, user_id: PydanticObjectId) -> list[Sandbox]:
        return await Sandbox.find(Sandbox.user_id == user_id).sort("-created_at").to_list()

    async def refresh_status(self, sandbox: Sandbox) -> Sandbox:
        """Resync live status from the provider. No-ops for sandboxes that
        aren't currently alive (provisioning / resetting / destroyed / failed
        all stay as-is — they're owned by manager transitions)."""
        if sandbox.status not in _ALIVE:
            return sandbox
        try:
            state = await self._provider.status(_handle_of(sandbox))
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)
        sandbox.status = state.status
        sandbox.public_url = state.public_url
        # Once Sprites confirms the sprite has actually idled, drop the
        # "pausing" banner.
        if sandbox.activity == "pausing" and sandbox.status == "cold":
            sandbox.activity = None
            sandbox.activity_detail = None
        await sandbox.save()
        await self._redis_write(sandbox)
        return sandbox

    # ── Transitions ───────────────────────────────────────────────────────

    async def wake(self, sandbox: Sandbox) -> Sandbox:
        if sandbox.status not in _WAKE_FROM:
            raise IllegalSandboxTransitionError(sandbox.status, "wake")
        try:
            state = await self._provider.wake(_handle_of(sandbox))
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)
        sandbox.status = state.status
        sandbox.public_url = state.public_url
        sandbox.last_active_at = _now()
        await sandbox.save()
        await self._redis_write(sandbox)
        _logger.info("sandbox.waked", sandbox_id=str(sandbox.id), status=sandbox.status)
        return sandbox

    async def pause(self, sandbox: Sandbox) -> Sandbox:
        """Force the sandbox to release compute. Sprites has no explicit
        force-pause API; the provider implementation kills active exec
        sessions so Sprites' idle timer can fire. Returned status may still
        be `warm` for a few seconds before going cold — the route
        schedules a delayed re-sync to converge the doc to `cold`."""
        if sandbox.status == "cold":
            return sandbox  # idempotent — already paused
        if sandbox.status not in _PAUSE_FROM:
            raise IllegalSandboxTransitionError(sandbox.status, "pause")
        # Set the activity banner *before* the provider call so the FE's
        # next poll already shows "pausing…" rather than a misleading
        # "warm".
        sandbox.activity = "pausing"
        sandbox.activity_detail = None
        await sandbox.save()
        try:
            state = await self._provider.pause(_handle_of(sandbox))
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)
        sandbox.status = state.status
        sandbox.public_url = state.public_url
        if sandbox.status == "cold":
            sandbox.activity = None
        await sandbox.save()
        await self._redis_write(sandbox)
        _logger.info("sandbox.paused", sandbox_id=str(sandbox.id), status=sandbox.status)
        return sandbox

    async def reset(self, sandbox: Sandbox) -> Sandbox:
        """Wipe `/work` on the sprite and let reconciliation re-clone.

        We don't destroy the sprite — that's wasteful and slow, and
        loses the git config + apt cache + anything else the user has
        installed. We also don't restore from checkpoint — that
        preserves the repos verbatim, which makes Reset feel like a
        no-op. Middle ground: `rm -rf /work` via exec (Sprites' own
        fs/delete refuses to delete the work-root with 400), leave the
        rest of the sprite alone, kick reconcile to re-clone fresh.

        Same `Sandbox._id`, same `provider_handle`, `reset_count`
        incremented, `last_reset_at` updated. If the sprite is cold,
        we wake it first so the wipe + reconcile have somewhere to
        run."""
        if sandbox.status not in _RESET_FROM:
            raise IllegalSandboxTransitionError(sandbox.status, "reset")

        was_cold = sandbox.status == "cold"
        was_failed = sandbox.status == "failed"
        sandbox.status = "resetting"
        await sandbox.save()
        await self._redis_write(sandbox)

        # Failed sandboxes have a broken sprite — wiping /work won't
        # recover them. Fall back to destroy+create so the user gets a
        # working sandbox.
        if was_failed:
            return await self._reset_via_recreate(sandbox)

        # Wake if it was cold so fs_delete + reconcile actually run.
        if was_cold:
            try:
                woken = await self._provider.wake(_handle_of(sandbox))
                sandbox.status = woken.status
                sandbox.public_url = woken.public_url
            except SpritesError as exc:
                _logger.warning(
                    "sandbox.reset.wake_failed",
                    sandbox_id=str(sandbox.id),
                    error=str(exc),
                )

        # Wipe everything under `/work`. We can't use `fs_delete /work`
        # directly — Sprites' fs/delete returns 400 for the work-root
        # path itself. `rm -rf /work && mkdir -p /work` via exec is
        # reliable: idempotent if the dir doesn't exist yet, and the
        # next reconcile pass treats `/work` as fresh-empty.
        try:
            wipe = await self._provider.exec_oneshot(
                _handle_of(sandbox),
                ["sh", "-c", "rm -rf /work && mkdir -p /work"],
                env={},
                cwd="/",
                timeout_s=60,
            )
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)
        if wipe.exit_code != 0:
            _logger.warning(
                "sandbox.reset.wipe_nonzero",
                sandbox_id=str(sandbox.id),
                exit_code=wipe.exit_code,
                stderr=wipe.stderr[-500:],
            )

        # Pull live status — the wipe doesn't change lifecycle but the
        # sprite may have shifted (e.g., still warming after wake).
        try:
            state = await self._provider.status(_handle_of(sandbox))
            sandbox.status = state.status
            sandbox.public_url = state.public_url
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)

        sandbox.reset_count += 1
        sandbox.last_reset_at = _now()
        sandbox.last_active_at = _now()
        sandbox.failure_reason = None
        # /work is gone, so the previous checkpoint no longer reflects
        # current state. Drop it; reconcile takes a fresh one.
        sandbox.clean_checkpoint_id = None
        await sandbox.save()
        await self._redis_write(sandbox)
        _logger.info(
            "sandbox.reset.workdir_wiped",
            sandbox_id=str(sandbox.id),
            status=sandbox.status,
        )
        return sandbox

    async def _reset_via_recreate(self, sandbox: Sandbox) -> Sandbox:
        """Used only for `failed` sandboxes where the sprite itself is
        broken and a `/work` wipe wouldn't recover it. Destroy and
        provision a fresh one with the same `Sandbox._id`."""
        try:
            await self._provider.destroy(_handle_of(sandbox))
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)
        sandbox.provider_handle = {}
        sandbox.public_url = None
        sandbox.reset_count += 1
        sandbox.last_reset_at = _now()
        sandbox.failure_reason = None
        sandbox.status = "provisioning"
        sandbox.clean_checkpoint_id = None
        sandbox.git_configured_token_fp = None
        await sandbox.save()
        return await self._provision(sandbox)

    async def destroy(self, sandbox: Sandbox) -> Sandbox:
        if sandbox.status == "destroyed":
            return sandbox  # idempotent
        if sandbox.status not in _DESTROY_FROM:
            raise IllegalSandboxTransitionError(sandbox.status, "destroy")

        # Best-effort destroy at the provider. If we never got past
        # `provisioning` (provider.create raised but flushed to mongo via
        # _mark_failed), there's no handle to clean up.
        if sandbox.provider_handle:
            try:
                await self._provider.destroy(_handle_of(sandbox))
            except SpritesError as exc:
                # Still mark our doc destroyed; the operator can clean up
                # the orphan sprite via Sprites' dashboard.
                _logger.warning(
                    "sandbox.destroy.provider_failed",
                    sandbox_id=str(sandbox.id),
                    error=str(exc),
                )

        sandbox.status = "destroyed"
        sandbox.destroyed_at = _now()
        sandbox.public_url = None
        await sandbox.save()
        await self._redis_clear(sandbox)
        _logger.info("sandbox.destroyed", sandbox_id=str(sandbox.id))
        return sandbox

    # ── Internals ─────────────────────────────────────────────────────────

    async def _provision(self, sandbox: Sandbox) -> Sandbox:
        if sandbox.id is None:
            raise RuntimeError("sandbox.id is None")
        sandbox.status = "provisioning"
        sandbox.failure_reason = None
        await sandbox.save()
        try:
            handle = await self._provider.create(
                sandbox_id=str(sandbox.id),
                labels=[f"user:{sandbox.user_id}"],
            )
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)

        # Pull the live state to get the public URL + initial status.
        try:
            state = await self._provider.status(handle)
        except SpritesError as exc:
            # Created but couldn't read status — store the handle so destroy
            # can clean up, then mark failed.
            sandbox.provider_handle = dict(handle.payload)
            await sandbox.save()
            return await self._mark_failed(sandbox, exc)

        sandbox.provider_handle = dict(handle.payload)
        sandbox.status = state.status
        sandbox.public_url = state.public_url
        sandbox.spawned_at = _now()
        sandbox.last_active_at = _now()
        await sandbox.save()
        await self._redis_write(sandbox)
        _logger.info(
            "sandbox.provisioned",
            sandbox_id=str(sandbox.id),
            provider=sandbox.provider_name,
            status=sandbox.status,
        )
        return sandbox

    async def _mark_failed(self, sandbox: Sandbox, exc: SpritesError) -> Sandbox:
        sandbox.status = "failed"
        sandbox.failure_reason = str(exc)[:500]
        sandbox.public_url = None
        await sandbox.save()
        await self._redis_clear(sandbox)
        _logger.warning(
            "sandbox.failed",
            sandbox_id=str(sandbox.id),
            error=sandbox.failure_reason,
        )
        return sandbox

    async def _redis_write(self, sandbox: Sandbox) -> None:
        if self._redis is None:
            return
        key = f"sandbox:{sandbox.id}"
        try:
            await self._redis.hset(  # type: ignore[misc]
                key,
                mapping={
                    "status": sandbox.status,
                    "public_url": sandbox.public_url or "",
                    "last_active_at": (
                        sandbox.last_active_at.isoformat() if sandbox.last_active_at else ""
                    ),
                },
            )
            await self._redis.expire(key, 90)
        except Exception as exc:
            _logger.warning(
                "sandbox.redis_write_failed",
                sandbox_id=str(sandbox.id),
                error=str(exc),
            )

    async def _redis_clear(self, sandbox: Sandbox) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.delete(f"sandbox:{sandbox.id}")
        except Exception as exc:
            _logger.warning(
                "sandbox.redis_clear_failed",
                sandbox_id=str(sandbox.id),
                error=str(exc),
            )
