"""In-memory `SandboxProvider` for local dev + tests.

Models Sprites' semantics:
- `create` returns a sprite in `warm` state with a fake public URL.
- `wake` forces `cold` → `running`.
- Idle hibernation is not modeled (Sprites does it with a real timer; for
  tests, we expose `_force_cold(handle)` so tests can simulate the transition
  deterministically).
- `destroy` is idempotent.

State is process-local. Restarting the orchestrator wipes it — fine because
Mongo's `Sandbox` doc is the source of truth and `MockSandboxProvider` is
*never* used in prod (see `provider_factory.build_sandbox_provider`).
"""

import uuid
from dataclasses import dataclass

from sandbox_provider.interface import (
    ProviderName,
    ProviderStatus,
    SandboxHandle,
    SandboxState,
    SpritesError,
)


@dataclass
class _SpriteRecord:
    name: str
    sandbox_id: str
    status: ProviderStatus
    public_url: str
    destroyed: bool = False


class MockSandboxProvider:
    name: ProviderName = "mock"

    def __init__(self) -> None:
        self._sprites: dict[str, _SpriteRecord] = {}

    async def create(self, *, sandbox_id: str, labels: list[str]) -> SandboxHandle:
        _ = labels
        sprite_name = f"vibe-sbx-{sandbox_id}"
        if sprite_name in self._sprites and not self._sprites[sprite_name].destroyed:
            raise SpritesError(f"sprite {sprite_name!r} already exists", retriable=False)
        self._sprites[sprite_name] = _SpriteRecord(
            name=sprite_name,
            sandbox_id=sandbox_id,
            status="warm",
            public_url=f"https://{sprite_name}-mock.sprites.app",
        )
        # Fresh UUID per create call so Reset (destroy+create with the same
        # `sandbox_id`) rotates the id, matching real Sprites behaviour where
        # the UUID is server-assigned per-sprite.
        return SandboxHandle(
            provider="mock",
            payload={"name": sprite_name, "id": f"sprite-mock-{uuid.uuid4().hex[:12]}"},
        )

    async def status(self, handle: SandboxHandle) -> SandboxState:
        rec = self._require(handle)
        return SandboxState(status=rec.status, public_url=rec.public_url)

    async def destroy(self, handle: SandboxHandle) -> None:
        name = handle.payload.get("name", "")
        rec = self._sprites.get(name)
        if rec is None or rec.destroyed:
            return  # idempotent
        rec.destroyed = True

    async def wake(self, handle: SandboxHandle) -> SandboxState:
        rec = self._require(handle)
        # Whatever state we were in, an exec session forces running.
        rec.status = "running"
        return SandboxState(status="running", public_url=rec.public_url)

    async def pause(self, handle: SandboxHandle) -> SandboxState:
        # Mock has no exec sessions to kill; just transition to cold to model
        # Sprites' idle-after-pause behaviour deterministically.
        rec = self._require(handle)
        rec.status = "cold"
        return SandboxState(status="cold", public_url=rec.public_url)

    # ── Test hooks (not part of the Protocol) ────────────────────────────

    def _force_cold(self, handle: SandboxHandle) -> None:
        """Simulate Sprites' idle-hibernation transition for tests."""
        rec = self._require(handle)
        rec.status = "cold"

    def _require(self, handle: SandboxHandle) -> _SpriteRecord:
        if handle.provider != "mock":
            raise SpritesError(
                f"MockSandboxProvider received handle for {handle.provider!r}",
                retriable=False,
            )
        name = handle.payload.get("name", "")
        rec = self._sprites.get(name)
        if rec is None or rec.destroyed:
            raise SpritesError(f"sprite {name!r} not found", retriable=False)
        return rec
