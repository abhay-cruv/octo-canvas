"""Slice-4 SandboxProvider Protocol.

Designed to be **provider-agnostic** so we can swap Sprites for another
backend (Modal, E2B, AWS) without touching the orchestrator. The handle
returned by `create` is opaque — provider-specific identifiers go in
`payload`, the discriminator in `provider`. Higher-level code never reaches
into `payload`.

Slice 4 surface only. Slice 5b will widen with `fs_*` / `exec_*` / snapshot
methods; slice 6 with `exec_session`. Don't pre-add them.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

# Shared with `shared_models.sandbox.ProviderName` — duplicated here so this
# package has no dependency on `shared_models`. Keep them in sync.
ProviderName = Literal["sprites", "mock"]


@dataclass(frozen=True)
class SandboxHandle:
    """Provider-opaque sandbox identity. Persisted on `Sandbox.provider_handle`
    in Mongo as a JSON dict. The `provider` field discriminates which
    `SandboxProvider` impl wrote it; `payload` is the impl's chosen identity
    fields (e.g. Sprites uses `{"name": ...}`)."""

    provider: ProviderName
    payload: dict[str, str]


# Live status from the underlying provider. The app-level `Sandbox.status`
# enum on the Beanie doc is wider — it adds in-flight states (`provisioning`,
# `resetting`) that the provider doesn't model.
ProviderStatus = Literal["cold", "warm", "running"]


@dataclass(frozen=True)
class SandboxState:
    """What `status()` returns. `public_url` is None until the underlying
    sandbox has provisioned a URL (typically immediately after create)."""

    status: ProviderStatus
    public_url: str | None


class SpritesError(Exception):
    """Wraps any error returned by the underlying provider. Sanitized — never
    includes API tokens or other credentials. `retriable=True` means a 5xx /
    transient network failure; `False` means a logic-level rejection (auth,
    bad request, not found)."""

    def __init__(self, message: str, *, retriable: bool = False) -> None:
        super().__init__(message)
        self.retriable = retriable


class SandboxProvider(Protocol):
    """Sandbox provisioning operations — slice 4 surface.

    `name` is the impl's discriminator (one of `ProviderName`). Stored on
    `Sandbox.provider_name` so the orchestrator knows which provider's
    `provider_handle` to read on subsequent calls.
    """

    name: ProviderName

    async def create(self, *, sandbox_id: str, labels: list[str]) -> SandboxHandle:
        """Provision a new sandbox. `sandbox_id` is the Mongo `Sandbox._id`
        (string). `labels` are arbitrary tags the provider may attach for
        organization / billing. Returns the opaque handle."""
        ...

    async def status(self, handle: SandboxHandle) -> SandboxState:
        """Live status from the provider. Raises `SpritesError` if the
        sandbox no longer exists at the provider."""
        ...

    async def destroy(self, handle: SandboxHandle) -> None:
        """Tear down the sandbox AND its filesystem. Idempotent: a 404 from
        the provider is treated as already-destroyed."""
        ...

    async def wake(self, handle: SandboxHandle) -> SandboxState:
        """Force a `cold` sandbox to `warm`/`running`. Sprites auto-wakes on
        any exec/HTTP/proxy access, so this is implemented as a no-op exec.
        Returns the new state."""
        ...

    async def pause(self, handle: SandboxHandle) -> SandboxState:
        """Force the sandbox to release compute (target `cold`).

        Sprites has no explicit force-pause API verb. The implementation
        kills any active exec sessions (which is what keeps a sprite warm)
        so Sprites' own idle timer can fire. Returns whatever the provider
        currently reports — may still be `warm` for a few seconds before
        Sprites transitions to `cold`. Idempotent on already-cold sandboxes.
        """
        ...
