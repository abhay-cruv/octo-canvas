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
        be `warm` for a few seconds before going cold."""
        if sandbox.status == "cold":
            return sandbox  # idempotent — already paused
        if sandbox.status not in _PAUSE_FROM:
            raise IllegalSandboxTransitionError(sandbox.status, "pause")
        try:
            state = await self._provider.pause(_handle_of(sandbox))
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)
        sandbox.status = state.status
        sandbox.public_url = state.public_url
        await sandbox.save()
        await self._redis_write(sandbox)
        _logger.info("sandbox.paused", sandbox_id=str(sandbox.id), status=sandbox.status)
        return sandbox

    async def reset(self, sandbox: Sandbox) -> Sandbox:
        """Tear down the current sprite, then provision a fresh one for the
        *same* `Sandbox` doc. Same `_id`, new `provider_handle`, fresh
        filesystem. Increments `reset_count`."""
        if sandbox.status not in _RESET_FROM:
            raise IllegalSandboxTransitionError(sandbox.status, "reset")

        # Mark resetting before any provider call so a crash doesn't leave
        # us in an alive state with a half-destroyed sprite.
        sandbox.status = "resetting"
        await sandbox.save()
        await self._redis_write(sandbox)

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
