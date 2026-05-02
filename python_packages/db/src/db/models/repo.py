from datetime import UTC, datetime
from typing import ClassVar, Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel
from shared_models.introspection import IntrospectionOverrides, RepoIntrospection

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
    # What introspection detected. Refreshed on connect + every reintrospect.
    introspection_detected: RepoIntrospection | None = None
    # Sparse user overrides — non-None fields take precedence over detected.
    introspection_overrides: IntrospectionOverrides | None = None
    clone_status: Literal["pending", "cloning", "ready", "failed"] = "pending"
    clone_path: str | None = None
    # Slice 5b: human-readable failure reason. Set alongside
    # `clone_status="failed"`; sanitized of tokens. Common values:
    # "github_reauth_required", "network_error", "timeout".
    clone_error: str | None = None
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
