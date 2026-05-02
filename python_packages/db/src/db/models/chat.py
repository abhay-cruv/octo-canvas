"""Chat — slice 8.

A chat is one long-lived `claude-agent-sdk` `ClaudeSDKClient` session
inside a sprite. `Chat ↔ Claude session 1:1`. Multiple chats coexist
per sandbox (capped at `MAX_LIVE_CHATS_PER_SANDBOX`); each runs at
`cwd=/work/` so the dev agent can edit any repo. Branch + PR semantics
defer to slice 9.

The slice-5a `Task` model coexists with this — the `/ws/web/tasks`
plumbing carries over for dev injection until the FE migrates. New
slice 8 work uses `Chat`.
"""

from datetime import UTC, datetime
from typing import ClassVar, Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from db.collections import Collections


def _now() -> datetime:
    return datetime.now(UTC)


ChatStatus = Literal[
    "pending",
    "running",
    "awaiting_input",
    "completed",
    "failed",
    "cancelled",
    "archived",
]


class Chat(Document):
    user_id: PydanticObjectId
    title: str
    status: ChatStatus = "pending"
    initial_prompt: str
    # Set by the SDK on first `ResultMessage` and reused by follow-ups
    # for `--resume`. Null until the first turn completes.
    claude_session_id: str | None = None
    # Per-chat token budgets. Slice 8 emits warning events at 80%; slice
    # 8b lands hard cut-off.
    token_budget_input: int = 1_000_000
    token_budget_output: int = 500_000
    # Live-state hints maintained by the bridge. NOT authoritative
    # (the bridge's in-memory state is); these exist for UI hints +
    # debugging eviction.
    last_alive_at: datetime | None = None
    cold_since_at: datetime | None = None
    # Cumulative token usage rolled up from `TokenUsageEvent`s. Reset
    # on `archived` for analytics rollups (slice 11).
    tokens_input: int = 0
    tokens_output: int = 0
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = Collections.CHATS
        indexes: ClassVar[list[IndexModel]] = [
            # User dashboard: list "my chats by recency, filtered by status".
            IndexModel(
                [
                    ("user_id", ASCENDING),
                    ("status", ASCENDING),
                    ("created_at", DESCENDING),
                ]
            ),
        ]
