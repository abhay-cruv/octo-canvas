"""Persisted agent event — the durable copy of every frame that goes out on
`/ws/web/tasks/{task_id}`. Slice 5a's only producer is the dev-inject
endpoint; slice 6+ wires real agent events into the same `append_event`.

`payload` is the JSON-mode dump of an `OrchestratorToWeb` discriminated
union member — i.e. the exact bytes the WS handler will hand to
`OrchestratorToWebAdapter.validate_python` during replay.
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from db.collections import Collections


def _now() -> datetime:
    return datetime.now(UTC)


class AgentEvent(Document):
    task_id: PydanticObjectId
    seq: int
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = Collections.AGENT_EVENTS
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("task_id", ASCENDING), ("seq", ASCENDING)], unique=True),
            IndexModel([("task_id", ASCENDING), ("created_at", ASCENDING)]),
        ]
