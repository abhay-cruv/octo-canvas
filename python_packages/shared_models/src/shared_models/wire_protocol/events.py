"""Orchestrator → web messages on `/ws/web/tasks/{task_id}`.

Slice 5a defines a minimum-viable taxonomy. The full set from
[Plan.md §10.4](../../../../../../docs/Plan.md) lands incrementally —
slice 6 (`ToolCallEvent`, `AssistantMessageEvent`, etc), slice 6b
(`PromptEnhancedEvent`, `AgentAnsweredClarification`), slice 7
(`GitOpEvent`), slice 8 (`FileEditEvent`).

Every event variant carries a discriminator `type` literal so Pydantic v2's
discriminated-union machinery can validate efficiently. `extra="ignore"` is
critical: a frontend running an older bundle must not blow up when the
backend adds new fields. See slice5a.md §risks #1.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared_models.sandbox import SandboxStatus


class _WireEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")


class StatusChangeEvent(_WireEvent):
    type: Literal["status.change"] = "status.change"
    seq: int
    new_status: Literal["pending", "running", "completed", "failed", "cancelled"]


class SandboxStatusEvent(_WireEvent):
    type: Literal["sandbox.status"] = "sandbox.status"
    seq: int
    sandbox_id: str
    status: SandboxStatus
    public_url: str | None = None


class ErrorEvent(_WireEvent):
    type: Literal["error"] = "error"
    seq: int
    kind: str
    message: str


class BackpressureWarning(_WireEvent):
    """Emitted when the per-subscriber outbound queue overflows. The web
    client's reconnect logic should treat this as a hint to bump its replay
    cursor and `Resume` from `last_dropped_seq` on next reconnect."""

    type: Literal["backpressure.warning"] = "backpressure.warning"
    seq: int
    last_dropped_seq: int


class DebugEvent(_WireEvent):
    """Slice 5a only — produced by the dev-only `/api/_internal/...` inject
    endpoint. The full agent event taxonomy replaces this in slice 6+."""

    type: Literal["debug.event"] = "debug.event"
    seq: int
    message: str


class Pong(_WireEvent):
    """Reply to a `Ping` from the web client. Carries `nonce` for correlation
    so the web side can compute round-trip latency. No `seq` — system frame."""

    type: Literal["pong"] = "pong"
    nonce: str


class ServerPing(_WireEvent):
    """Server-initiated heartbeat. The web client must reply with `Pong` (see
    `commands.py`). No `seq` — system frame."""

    type: Literal["ping"] = "ping"
    nonce: str


OrchestratorToWeb = Annotated[
    StatusChangeEvent
    | SandboxStatusEvent
    | ErrorEvent
    | BackpressureWarning
    | DebugEvent
    | Pong
    | ServerPing,
    Field(discriminator="type"),
]
