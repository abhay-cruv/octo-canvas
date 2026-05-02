"""UserAgentMemory — slice 8.

Per-user, MEMORY.md-shape store driving the BE-side user agent. Same
discipline as Claude Code's auto-memory:

- One `kind="index"` doc per user, `name="MEMORY"`, body = the index
  (one-line pointers `- [Title](slug.md) — hook`).
- Per-topic docs (`kind` ∈ {user, feedback, project, reference})
  with `name=<slug>`, `description` for relevance scoring at
  `memory_list` time, and `body` markdown.

The user agent reads/writes via in-process helpers (`memory_list`,
`memory_read`, `memory_write`, `memory_delete`) — NOT MCP. Same Python
process as the orchestrator. Curation prompt steers it to follow the
"why + how to apply" structure for feedback/project entries.
"""

from datetime import UTC, datetime
from typing import ClassVar, Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from db.collections import Collections


def _now() -> datetime:
    return datetime.now(UTC)


MemoryKind = Literal["index", "user", "feedback", "project", "reference"]


class UserAgentMemory(Document):
    user_id: PydanticObjectId
    name: str  # "MEMORY" for the index, else topic slug
    kind: MemoryKind
    description: str  # one-line hook for relevance scoring; empty on index
    body: str  # markdown
    updated_at: datetime = Field(default_factory=_now)

    class Settings:
        name = Collections.USER_AGENT_MEMORY
        indexes: ClassVar[list[IndexModel]] = [
            # Unique per-user (name) — `memory_write` is upsert.
            IndexModel(
                [("user_id", ASCENDING), ("name", ASCENDING)],
                unique=True,
            ),
        ]
