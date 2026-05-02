"""Sandbox wire-shape models — shared between orchestrator and (eventually) bridge.

Status enum mirrors the Sprites lifecycle (`cold | warm | running`) plus the
app-level transient states (`provisioning`, `resetting`) and the terminal
states (`destroyed`, `failed`). See [slice4.md §5](../../../../docs/slice/slice4.md)
for the state matrix.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SandboxStatus = Literal[
    "provisioning",  # provider.create in flight
    "cold",  # sprite exists, hibernated (Sprites' cold)
    "warm",  # sprite exists, warming up (Sprites' warm)
    "running",  # sprite exists, active (Sprites' running)
    "resetting",  # provider.destroy + provider.create in flight
    "destroyed",  # sprite gone; doc kept for audit
    "failed",  # provider error; needs reset/destroy
]

ProviderName = Literal["sprites", "mock"]


class SandboxResponse(BaseModel):
    id: str
    user_id: str
    provider_name: ProviderName
    status: SandboxStatus
    public_url: str | None
    last_active_at: datetime | None
    spawned_at: datetime | None
    destroyed_at: datetime | None
    last_reset_at: datetime | None
    reset_count: int
    # Slice 5b: progress banner alongside cold/warm/running. Examples:
    # "configuring_git", "cloning", "installing_packages",
    # "checkpointing", "pausing". `None` when idle.
    activity: str | None = None
    activity_detail: str | None = None
    failure_reason: str | None
    created_at: datetime
