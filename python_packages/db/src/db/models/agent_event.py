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
            # Sparse on task_id so chat-keyed rows don't violate the
            # uniqueness on (task_id=None, seq).
            IndexModel(
                [("task_id", ASCENDING), ("seq", ASCENDING)],
                unique=True,
                sparse=True,
                name="task_id_seq_unique_sparse",
            ),
            IndexModel(
                [("task_id", ASCENDING), ("created_at", ASCENDING)],
                sparse=True,
                name="task_id_created_at_sparse",
            ),
            # Slice 8 — chat-keyed replay. Sparse so task-keyed rows
            # don't index here. Compound on `claude_session_id` so
            # `--resume`-spawned sessions get distinct seq spaces from
            # cold-spawned ones (matches `seq_counters` keying).
            IndexModel(
                [
                    ("chat_id", ASCENDING),
                    ("claude_session_id", ASCENDING),
                    ("seq", ASCENDING),
                ],
                unique=True,
                sparse=True,
                name="chat_session_seq_unique_sparse",
            ),
            IndexModel(
                [("chat_id", ASCENDING), ("created_at", ASCENDING)],
                sparse=True,
                name="chat_id_created_at_sparse",
            ),
        ]
