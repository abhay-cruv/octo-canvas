from datetime import UTC, datetime
from typing import Annotated, Literal

from beanie import Document, Indexed
from pydantic import Field

from db.collections import Collections


def _now() -> datetime:
    return datetime.now(UTC)


# Slice 8: Claude credential mode is a Protocol (`agent_config.credentials`).
# v1 hard-codes `platform_api_key`; OAuth + BYOK modes ship later as
# additional impls + a settings flip — no schema migration.
ClaudeAuthMode = Literal["platform_api_key", "user_oauth", "user_api_key"]

# Slice 8: user-agent provider is pluggable. v1 ships `anthropic` only
# via `LLMProvider` Protocol at `agent_config.llm_provider`. OpenAI /
# Gemini land later as additional `LLMProvider` impls.
UserAgentProvider = Literal["anthropic", "openai", "google"]


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
    # Slice 8: agent runtime config.
    claude_auth_mode: ClaudeAuthMode = "platform_api_key"
    # User agent on the orchestrator BE. Toggleable per user; when OFF,
    # the chat is direct passthrough (raw prompt to bridge, full
    # dev-agent stream to FE, no Mongo memory writes).
    user_agent_enabled: bool = True
    user_agent_provider: UserAgentProvider = "anthropic"
    user_agent_model: str = "claude-haiku-4-5"

    class Settings:
        name = Collections.USERS
