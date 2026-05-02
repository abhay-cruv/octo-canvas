from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from shared_models.introspection import IntrospectionOverrides, RepoIntrospection


class AvailableRepo(BaseModel):
    github_repo_id: int
    full_name: str
    default_branch: str
    private: bool
    description: str | None
    is_connected: bool


class AvailableReposPage(BaseModel):
    repos: list[AvailableRepo]
    page: int
    per_page: int
    has_more: bool


class ConnectedRepo(BaseModel):
    id: str
    github_repo_id: int
    full_name: str
    default_branch: str
    private: bool
    clone_status: Literal["pending", "cloning", "ready", "failed"]
    # Slice 5b: human-readable failure reason when `clone_status="failed"`.
    # Sanitized of tokens before persisting; values like
    # "github_reauth_required", "branch_not_found", or a stderr-tail prefix.
    clone_error: str | None = None
    connected_at: datetime
    # Effective values: detected merged with user overrides. Slice 4+ callers
    # (bridge, agent runs) read this — they don't care which fields were user-set.
    introspection: RepoIntrospection | None
    # Raw detection. Exposed so the UI can show "detected was X" alongside an
    # override and so a "Reset" action knows what the field would revert to.
    introspection_detected: RepoIntrospection | None
    # Sparse — only the fields the user explicitly overrode. The UI uses this
    # to render a "(custom)" badge per overridden field.
    introspection_overrides: IntrospectionOverrides | None


class ConnectRepoRequest(BaseModel):
    github_repo_id: int
    full_name: str  # "owner/repo" — server re-fetches via the user's OAuth token
