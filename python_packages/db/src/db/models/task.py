"""Task — minimum-viable shape for slice 5a.

Slice 6 widens this with `repo_id`, `prompt`, `current_run_id`, etc. Today
it exists only so the WS subscription on `/ws/web/tasks/{task_id}` has a
durable id to authorize and key against.
See [slice5a.md §1](../../../../../../docs/slice/slice5a.md).
"""

from datetime import UTC, datetime
from typing import ClassVar, Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from db.collections import Collections


def _now() -> datetime:
    return datetime.now(UTC)


TaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class Task(Document):
    user_id: PydanticObjectId
    status: TaskStatus = "pending"
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = Collections.TASKS
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("user_id", ASCENDING)]),
        ]
