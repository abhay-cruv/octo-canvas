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
    # Slice 5a — task-keyed events for `/ws/web/tasks/{task_id}`
    # injection plumbing. Coexists with slice 8's chat-keyed flow so
    # the slice-5a tests keep working until the FE migrates.
    task_id: PydanticObjectId | None = None
    # Slice 8 — chat-keyed events for `/ws/web/chats/{chat_id}`. Bridge
    # frames + user-agent decisions persist with this key.
    chat_id: PydanticObjectId | None = None
    # Slice 8 — `claude-agent-sdk` session id (assigned on first
    # `ResultMessage`). Null on slice-5a rows and on dev events that
    # aren't session-scoped.
    claude_session_id: str | None = None
    seq: int
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = Collections.AGENT_EVENTS
        indexes: ClassVar[list[IndexModel]] = [
            # Partial-filter on task_id != null so chat-keyed rows
            # (task_id=None) don't share the index space with
            # slice-5a task-keyed rows. Sparse alone wouldn't work —
            # Mongo treats explicit `null` as a value (only absent
            # fields are excluded from a sparse index).
            IndexModel(
                [("task_id", ASCENDING), ("seq", ASCENDING)],
                unique=True,
                partialFilterExpression={"task_id": {"$type": "objectId"}},
                name="task_id_seq_unique_partial",
            ),
            IndexModel(
                [("task_id", ASCENDING), ("created_at", ASCENDING)],
                partialFilterExpression={"task_id": {"$type": "objectId"}},
                name="task_id_created_at_partial",
            ),
            # Slice 8 — chat-keyed replay. Same partial-filter trick on
            # chat_id. Compound on `claude_session_id` so post-resume
            # sessions get distinct seq spaces from cold-spawned ones
            # (matches `seq_counters` keying).
            IndexModel(
                [
                    ("chat_id", ASCENDING),
                    ("claude_session_id", ASCENDING),
                    ("seq", ASCENDING),
                ],
                unique=True,
                partialFilterExpression={"chat_id": {"$type": "objectId"}},
                name="chat_session_seq_unique_partial",
            ),
            IndexModel(
                [("chat_id", ASCENDING), ("created_at", ASCENDING)],
                partialFilterExpression={"chat_id": {"$type": "objectId"}},
                name="chat_id_created_at_partial",
            ),
        ]
