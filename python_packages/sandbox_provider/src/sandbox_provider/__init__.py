"""Sandbox provisioning behind a single Protocol.

Two implementations:
- `SpritesProvider` — production; wraps the `sprites-py` SDK.
- `MockSandboxProvider` — local dev / tests; in-memory, models Sprites
  status semantics (cold/warm/running, auto-warm-on-create, force-cold for
  test determinism).

Selection happens explicitly in
`apps/orchestrator/src/orchestrator/lib/provider_factory.py` based on the
`SANDBOX_PROVIDER` env var. Empty `SPRITES_TOKEN` does NOT silently fall
back to mock — see slice4.md §0 #8.

Slice 4 is lifecycle-only. Slice 5b widens the Protocol with `fs_*` and
`exec_oneshot` / `exec_session`; slice 6 with checkpoint helpers. Don't
broaden until each slice needs it.
"""

from sandbox_provider.interface import (
    CheckpointId,
    ExecResult,
    FsEntry,
    ProviderName,
    ProviderStatus,
    SandboxHandle,
    SandboxProvider,
    SandboxState,
    SpritesError,
)
from sandbox_provider.mock import MockSandboxProvider
from sandbox_provider.sprites import SpritesProvider

__all__ = [
    "CheckpointId",
    "ExecResult",
    "FsEntry",
    "MockSandboxProvider",
    "ProviderName",
    "ProviderStatus",
    "SandboxHandle",
    "SandboxProvider",
    "SandboxState",
    "SpritesError",
    "SpritesProvider",
]
