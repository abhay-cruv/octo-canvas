from datetime import UTC, datetime
from typing import Annotated, Literal

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


def _now() -> datetime:
    return datetime.now(UTC)


class Repo(Document):
    user_id: PydanticObjectId
    github_repo_id: Annotated[int, Indexed(unique=True)]
    full_name: str
    default_branch: str
    private: bool
    # Slice 3 widens this to RepoIntrospection | None — keep typed as None for now.
    introspection: None = None
    clone_status: Literal["pending", "cloning", "ready", "failed"] = "pending"
    clone_path: str | None = None
    last_synced_at: datetime | None = None
    connected_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "repos"
