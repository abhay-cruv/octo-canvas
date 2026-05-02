"""User-agent memory — slice 8 §calls #6.

In-process Mongo helpers (NOT MCP — same Python process as the
orchestrator). MEMORY.md-shape: a top-level index doc per user
(`name="MEMORY"`) lists pointers to topic docs (`prefs`,
`project_<repo>`, `feedback_*`, etc.). The user agent reads/writes
through these four functions with the same conventions as Claude
Code's auto-memory:

- `memory_list` first to discover topics by name + description
- `memory_read` only the relevant topics (keeps context lean)
- `memory_write` after a chat to record what's worth keeping
- `memory_delete` for stale entries

The curation prompt the user-agent uses to decide WHAT to memorize
lives in `agent_config/prompts/user_agent_memory.md` (reserved file —
v1 ships a minimal prompt; iteration is post-slice).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from beanie import PydanticObjectId
from db.models import MemoryKind, UserAgentMemory


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class MemoryEntry:
    """The shape `memory_list` returns. Body is NOT included — keeps
    the listing cheap; the user agent calls `memory_read` per topic
    when it decides one is relevant."""

    name: str
    kind: MemoryKind
    description: str


async def list_memory(user_id: PydanticObjectId) -> list[MemoryEntry]:
    """List every memory topic for a user (excluding the index itself —
    the index is metadata, not a topic to load)."""
    cursor = UserAgentMemory.find(
        UserAgentMemory.user_id == user_id,
        UserAgentMemory.kind != "index",
    ).sort("name")
    rows = await cursor.to_list()
    return [
        MemoryEntry(name=r.name, kind=r.kind, description=r.description) for r in rows
    ]


async def read_memory(user_id: PydanticObjectId, name: str) -> str | None:
    """Read a specific topic's `body` markdown. Returns None if missing."""
    doc = await UserAgentMemory.find_one(
        UserAgentMemory.user_id == user_id,
        UserAgentMemory.name == name,
    )
    return doc.body if doc is not None else None


async def write_memory(
    user_id: PydanticObjectId,
    *,
    name: str,
    kind: MemoryKind,
    description: str,
    body: str,
) -> UserAgentMemory:
    """Upsert a memory entry. The unique index on `(user_id, name)`
    enforces single-row-per-topic; this function picks the upsert
    semantic (replace body + description on subsequent writes)."""
    now = _now()
    doc = await UserAgentMemory.find_one(
        UserAgentMemory.user_id == user_id,
        UserAgentMemory.name == name,
    )
    if doc is None:
        doc = UserAgentMemory(
            user_id=user_id,
            name=name,
            kind=kind,
            description=description,
            body=body,
            updated_at=now,
        )
        await doc.insert()
    else:
        doc.kind = kind
        doc.description = description
        doc.body = body
        doc.updated_at = now
        await doc.save()
    return doc


async def delete_memory(user_id: PydanticObjectId, name: str) -> bool:
    """Returns True if a topic was deleted, False if not found."""
    doc = await UserAgentMemory.find_one(
        UserAgentMemory.user_id == user_id,
        UserAgentMemory.name == name,
    )
    if doc is None:
        return False
    await doc.delete()
    return True
