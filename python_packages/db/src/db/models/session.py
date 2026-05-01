from datetime import UTC, datetime
from typing import Annotated

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field

from db.collections import Collections


def _now() -> datetime:
    return datetime.now(UTC)


class Session(Document):
    session_id: Annotated[str, Indexed(unique=True)]
    user_id: PydanticObjectId
    created_at: datetime = Field(default_factory=_now)
    expires_at: datetime
    last_used_at: datetime = Field(default_factory=_now)

    class Settings:
        name = Collections.SESSIONS
