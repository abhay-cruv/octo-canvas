from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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
    connected_at: datetime


class ConnectRepoRequest(BaseModel):
    github_repo_id: int
    full_name: str  # "owner/repo" — server re-fetches via the user's OAuth token
