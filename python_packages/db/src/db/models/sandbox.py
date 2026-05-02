from datetime import UTC, datetime
from typing import ClassVar

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel
from shared_models.sandbox import ProviderName, SandboxStatus

from db.collections import Collections


def _now() -> datetime:
    return datetime.now(UTC)


class Sandbox(Document):
    """Per-user sandbox handle. v1 enforces "one running sandbox per user" at
    the orchestrator routing layer (services.SandboxManager.get_or_create) —
    never at the Mongo index — so the multi-sandbox future per
    [Plan.md §4](../Plan.md) is just a config flip away.

    Backed by `sandbox_provider.SandboxProvider`. The opaque `provider_handle`
    payload identifies the sandbox at the provider; `provider_name` is the
    discriminator. Higher-level code never reaches into `provider_handle`.
    """

    user_id: PydanticObjectId
    provider_name: ProviderName
    # Opaque payload returned by `provider.create()`. Only the matching
    # `SandboxProvider` impl knows how to read it (e.g. Sprites uses `name`).
    provider_handle: dict[str, str] = Field(default_factory=dict)
    status: SandboxStatus = "provisioning"
    public_url: str | None = None
    last_active_at: datetime | None = None
    spawned_at: datetime | None = None
    destroyed_at: datetime | None = None
    last_reset_at: datetime | None = None
    reset_count: int = 0
    # Slice 5b: id of the most recent `clean` checkpoint produced by a
    # mutating reconciliation pass. `None` until the first successful clone
    # finishes — Reset falls through to the slow destroy+create path while
    # this is unset.
    clean_checkpoint_id: str | None = None
    # Slice 5b: SHA-256 fingerprint of the OAuth token we last wrote into
    # the sandbox's `~/.git-credentials`. The reconciler skips git setup
    # when this matches the user's current token; mismatch → re-run setup
    # (covers Reconnect GitHub flows and token rotation).
    git_configured_token_fp: str | None = None
    # Slice 5b: human-readable banner of what the sandbox is *doing*
    # right now beyond the basic cold/warm/running. Set by the reconciler
    # at phase boundaries (`configuring_git`, `installing_packages`,
    # `cloning`, `checkpointing`) and by `pause` (`pausing`); cleared
    # when the action completes. Display the cold/warm/running pill AND
    # the activity banner together so the user sees what's in flight.
    activity: str | None = None
    activity_detail: str | None = None
    # Slice 7: timestamp the current `activity` was set. UI uses this to
    # show "elapsed 4m 12s" alongside the activity banner so the user
    # can tell "slow legitimate compile" from "actually stuck". Cleared
    # whenever activity transitions to None.
    activity_started_at: datetime | None = None
    # Slice 7: short stderr-tail of the most recent reconciler failure.
    # Set at every `reconcile.*_failed` / `*_error` point (apt failure,
    # bridge_setup, runtime install, clone). Cleared when activity
    # transitions to a NEW phase (so the user sees the freshest error,
    # not yesterday's). Sanitized — never includes tokens.
    last_reconcile_error: str | None = None
    # Slice 7: bridge wiring. The orchestrator mints a per-sandbox token
    # at bridge-launch time (`secrets.token_urlsafe(32)`), pipes the
    # plaintext into the bridge's env as `BRIDGE_TOKEN` via
    # `exec_oneshot`, and persists only the SHA-256 hash here. The bridge
    # presents the plaintext at the (slice-8) WSS handshake; the
    # orchestrator hashes + compares. `None` until the reconciler's
    # bridge-setup phase has launched the daemon for this sandbox.
    bridge_token_hash: str | None = None
    # Slice 7: fingerprint of what the reconciler's `installing_bridge`
    # phase last installed (claude CLI version + nvm/pyenv/rbenv pins).
    # When this matches the orchestrator's current pin set, the
    # bridge-setup phase is a no-op. `None` until first install. When it
    # mismatches (e.g. CLI version bump), the phase re-runs.
    bridge_setup_fingerprint: str | None = None
    # Slice 8 Phase 0b: combined sha256 of the bridge wheel bundle
    # (bridge + workspace deps) currently installed in `/opt/bridge/.venv`
    # on the sprite. The reconciler builds the bundle on the orchestrator,
    # uploads via `fs_write`, and installs via `uv pip install`. When the
    # locally built bundle's combined_sha matches this, the wheel-install
    # step is a no-op — covers the "no source change since last reconcile"
    # path (most reconcile passes). `None` until first install.
    bridge_wheel_sha: str | None = None
    # Slice 8: bridge daemon liveness. `bridge_version` is what the
    # bridge reports in its WSS `Hello` (matches the wheel installed in
    # /opt/bridge/.venv); `bridge_connected_at` is the timestamp of the
    # most recent accepted handshake; `bridge_last_acked_seq_per_chat`
    # mirrors the bridge's ring-buffer ack cursor per chat (used for
    # replay on reconnect — orchestrator says "I have up to seq X for
    # this chat", bridge resends X+1 onward).
    bridge_version: str | None = None
    bridge_connected_at: datetime | None = None
    bridge_last_acked_seq_per_chat: dict[str, int] = Field(default_factory=dict)
    # Populated when status="failed". Sanitized — never contains tokens.
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = Collections.SANDBOXES
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("user_id", ASCENDING)]),
            # For status-based scans (e.g. find every active sandbox for
            # cross-instance reconciliation in slice 5b).
            IndexModel([("status", ASCENDING)]),
        ]
