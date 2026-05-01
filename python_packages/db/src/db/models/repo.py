from datetime import UTC, datetime
from typing import ClassVar, Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from db.collections import Collections


def _now() -> datetime:
    return datetime.now(UTC)


class Repo(Document):
    user_id: PydanticObjectId
    # Slice 4 binds this when the user picks a sandbox at connect time.
    # Today (slice 2) it's null for every row; the compound unique index below
    # stays correct because we include user_id alongside sandbox_id +
    # github_repo_id. Same repo can be connected to multiple sandboxes.
    sandbox_id: PydanticObjectId | None = None
    github_repo_id: int
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
        name = Collections.REPOS
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("user_id", ASCENDING)]),
            IndexModel(
                [
                    ("sandbox_id", ASCENDING),
                    ("user_id", ASCENDING),
                    ("github_repo_id", ASCENDING),
                ],
                unique=True,
                name="uniq_sandbox_user_repo",
            ),
        ]
