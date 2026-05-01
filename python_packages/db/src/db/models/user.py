from datetime import UTC, datetime
from typing import Annotated

from beanie import Document, Indexed
from pydantic import Field


def _now() -> datetime:
    return datetime.now(UTC)


class User(Document):
    github_user_id: Annotated[int, Indexed(unique=True)]
    github_username: str
    github_avatar_url: str | None = None
    email: str
    display_name: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    last_signed_in_at: datetime = Field(default_factory=_now)
    # Slice 2: OAuth access token (cleared to None on 401; user must re-auth).
    github_access_token: str | None = None

    class Settings:
        name = "users"
