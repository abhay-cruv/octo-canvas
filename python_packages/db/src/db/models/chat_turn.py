"""ChatTurn — one round-trip in a Chat (slice 8).

Every user message creates a turn. The first turn (`is_follow_up=False`)
spawns the `ClaudeSDKClient` if cold; follow-ups feed text directly to
the live client (or `--resume` if cold).

`enhanced_prompt` records what the user agent forwarded to the bridge
when user-agent-mode is on (vs. the raw `prompt` the user typed). Both
are kept so the FE can show "user agent added context X" inline.
"""

from datetime import UTC, datetime
from typing import ClassVar, Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from db.collections import Collections


def _now() -> datetime:
    return datetime.now(UTC)


ChatTurnStatus = Literal[
    "queued", "running", "awaiting_input", "completed", "failed", "cancelled"
]


class ChatTurn(Document):
    chat_id: PydanticObjectId
    is_follow_up: bool
    prompt: str  # raw user input
    enhanced_prompt: str | None = None  # user-agent-enhanced (when ON)
    status: ChatTurnStatus = "queued"
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    error: str | None = None

    class Settings:
        name = Collections.CHAT_TURNS
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("chat_id", ASCENDING), ("started_at", ASCENDING)]),
        ]
