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
