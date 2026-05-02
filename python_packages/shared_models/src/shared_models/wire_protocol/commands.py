"""Web → orchestrator messages on `/ws/web/tasks/{task_id}`.

Slice 5a covers session bring-up (`Resume`) + heartbeat (`Ping`/`Pong`). The
task-level commands — `SendFollowUp`, `CancelTask`, `RequestOpenPty`, etc —
land in slices 6/8, see [Plan.md §10.4](../../../../../../docs/Plan.md).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _WireCommand(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Resume(_WireCommand):
    """Sent as the FIRST frame of every (re)connection. The orchestrator
    streams every event with `seq > after_seq` from Mongo, then transitions
    to live mode by subscribing to the per-task fanout channel."""

    type: Literal["resume"] = "resume"
    after_seq: int


class ClientPing(_WireCommand):
    type: Literal["ping"] = "ping"
    nonce: str


class ClientPong(_WireCommand):
    type: Literal["pong"] = "pong"
    nonce: str


WebToOrchestrator = Annotated[
    Resume | ClientPing | ClientPong,
    Field(discriminator="type"),
]
