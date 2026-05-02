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
