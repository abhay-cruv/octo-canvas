"""SandboxProvider Protocol.

Slice 4 (provisioning) + slice 5b (clone / exec / fs / checkpoint) +
slice 6 (FS file-ops + watch).

Designed to be **provider-agnostic** so we can swap Sprites for another
backend (Modal, E2B, AWS) without touching the orchestrator. The handle
returned by `create` is opaque — provider-specific identifiers go in
`payload`, the discriminator in `provider`. Higher-level code never reaches
into `payload`.

Slice 5b widened with what's needed to clone repos, reconcile against
the sandbox's `/work` listing, and take/restore checkpoints. Slice 6
adds the per-byte FS surface (`fs_read`, `fs_write`, `fs_rename`) and a
streaming `fs_watch_subscribe` so the orchestrator can fan out file
edits to web subscribers.
"""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Literal, NewType, Protocol

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


@dataclass(frozen=True)
class ExecResult:
    """Return value of `exec_oneshot`. `stdout`/`stderr` are size-bounded by
    the provider (Sprites caps at a few MB by default); callers needing the
    full stream should open an exec session via slice 6+'s `exec_session`."""

    exit_code: int
    stdout: str
    stderr: str
    duration_s: float


@dataclass(frozen=True)
class FsEntry:
    """One entry in a `fs_list` response."""

    name: str
    kind: Literal["file", "dir"]
    size: int


# Provider-opaque checkpoint identity. Persisted on `Sandbox.clean_checkpoint_id`
# in Mongo as a plain string. The matching provider knows how to interpret it.
CheckpointId = NewType("CheckpointId", str)


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
        organization / billing. Returns the opaque handle.

        v1 deliberately keeps this signature minimal — Sprites is already a
        VM, so per-sandbox setup (nvm/pyenv/rbenv, claude CLI, bridge
        daemon) lives in the orchestrator's reconciler. Per-provision
        bridge env (`BRIDGE_TOKEN`, etc.) is delivered later via
        `exec_oneshot` when the bridge daemon is launched."""
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

    # ── Slice 5b additions ────────────────────────────────────────────────

    async def exec_oneshot(
        self,
        handle: SandboxHandle,
        argv: list[str],
        *,
        env: Mapping[str, str],
        cwd: str,
        timeout_s: int = 300,
    ) -> ExecResult:
        """Run `argv` inside the sandbox to completion. Captures stdout and
        stderr. `cwd` is mandatory (no implicit working directory). `env` is
        merged onto the sandbox's process env. Raises `SpritesError` on
        provider errors (network, auth) — a non-zero exit code does NOT
        raise; callers inspect `ExecResult.exit_code`."""
        ...

    async def fs_list(self, handle: SandboxHandle, path: str) -> list[FsEntry]:
        """List entries in `path`. Raises `SpritesError(retriable=False)` if
        the path doesn't exist."""
        ...

    async def fs_delete(self, handle: SandboxHandle, path: str, *, recursive: bool = False) -> None:
        """Delete `path`. `recursive=True` for directories. Idempotent: a
        404 from the provider is treated as already-deleted."""
        ...

    async def snapshot(self, handle: SandboxHandle, *, comment: str) -> CheckpointId:
        """Create a point-in-time checkpoint of the sandbox's filesystem.
        Returns the checkpoint id (provider-opaque string). The orchestrator
        persists this on `Sandbox.clean_checkpoint_id` and feeds it back to
        `restore` on Reset."""
        ...

    async def restore(self, handle: SandboxHandle, checkpoint_id: CheckpointId) -> SandboxState:
        """Roll the sandbox back to a previous checkpoint. Used by Reset to
        avoid the full destroy+create round-trip. Returns the post-restore
        state (typically `warm`)."""
        ...

    # ── Slice 6 additions ────────────────────────────────────────────────

    async def fs_read(self, handle: SandboxHandle, path: str) -> bytes:
        """Read a file from the sandbox filesystem. Returns the raw bytes.
        Raises `SpritesError(retriable=False)` if the path doesn't exist or
        is a directory."""
        ...

    async def fs_write(
        self,
        handle: SandboxHandle,
        path: str,
        content: bytes,
        *,
        mode: int = 0o644,
        mkdir: bool = True,
    ) -> int:
        """Write `content` to `path`, creating parent directories when
        `mkdir=True`. Returns the number of bytes written. Raises
        `SpritesError` on provider errors."""
        ...

    async def fs_rename(self, handle: SandboxHandle, src: str, dst: str) -> None:
        """Rename or move `src` to `dst`. Both paths are absolute (or
        resolved relative to the sandbox's `/`)."""
        ...

    async def pty_dial_info(
        self,
        handle: SandboxHandle,
        *,
        cwd: str = "/work",
        cols: int = 80,
        rows: int = 24,
        attach_session_id: str | None = None,
    ) -> "PtyDialInfo":
        """Tell the orchestrator's PTY broker where to dial. When
        `attach_session_id` is supplied, the URL points at the Sprites
        attach endpoint (`/exec/{session_id}`); otherwise it opens a
        new bash login session.

        The broker pumps bytes both ways across this URL — see
        `apps/orchestrator/src/orchestrator/ws/pty.py`.
        """
        ...

    async def fs_watch_subscribe(
        self,
        handle: SandboxHandle,
        path: str,
        *,
        recursive: bool = True,
    ) -> AsyncIterator["FsEvent"]:
        """Subscribe to filesystem-change events under `path`. Yields
        `FsEvent` records until the consumer closes the iterator (which
        the impl uses as the signal to tear down the underlying watcher).

        Implementations must be async-cancel-safe: cancelling the
        consuming task cleanly closes the underlying connection.
        """
        ...
        # Required by Protocol — bodies are never executed.
        if False:
            yield  # type: ignore[unreachable]


@dataclass(frozen=True)
class PtyDialInfo:
    """Where the orchestrator's PTY broker should dial to reach this
    sandbox's exec channel. Returned by `pty_dial_info` so the broker
    stays provider-agnostic — Sprites, Mock, or any future backend just
    yields a `wss://` URL plus auth headers."""

    url: str
    headers: list[tuple[str, str]]


@dataclass(frozen=True)
class FsEvent:
    """One filesystem-change event from `fs_watch_subscribe`. `path` is the
    absolute path inside the sandbox; `kind` is the change type. `size` is
    the post-event size for create/modify on files, `None` otherwise."""

    path: str
    kind: Literal["create", "modify", "delete", "rename"]
    is_dir: bool
    size: int | None
    timestamp_ms: int
