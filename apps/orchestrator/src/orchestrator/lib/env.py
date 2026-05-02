from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_HERE = Path(__file__).resolve()
_WORKSPACE_ROOT = _HERE.parents[5]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_WORKSPACE_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    orchestrator_port: int = Field(default=3001, alias="ORCHESTRATOR_PORT")
    web_base_url: str = Field(alias="WEB_BASE_URL")

    mongodb_uri: str = Field(alias="MONGODB_URI")
    # Secret-typed: any accidental `repr(settings)` / `model_dump()` /
    # log line shows `SecretStr('**********')` instead of the value.
    # Read with `.get_secret_value()` at the call site that actually
    # needs the plaintext.
    auth_secret: SecretStr = Field(alias="AUTH_SECRET")
    github_oauth_client_id: str = Field(alias="GITHUB_OAUTH_CLIENT_ID")
    github_oauth_client_secret: SecretStr = Field(alias="GITHUB_OAUTH_CLIENT_SECRET")
    orchestrator_base_url: str = Field(alias="ORCHESTRATOR_BASE_URL")

    # Sandbox provisioning (slice 4) — uses Sprites SDK; resources, regions,
    # idle hibernation, and bridge image are all managed by Sprites itself.
    sandbox_provider: Literal["sprites", "mock"] = Field(
        default="sprites", alias="SANDBOX_PROVIDER"
    )
    sprites_token: SecretStr = Field(default=SecretStr(""), alias="SPRITES_TOKEN")
    sprites_base_url: str = Field(default="https://api.sprites.dev", alias="SPRITES_BASE_URL")
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")

    # Slice 5a: gate the dev-only `/api/_internal/...` event-inject endpoint.
    # Defaults true in dev. Set ALLOW_INTERNAL_ENDPOINTS=false in any prod env.
    allow_internal_endpoints: bool = Field(default=True, alias="ALLOW_INTERNAL_ENDPOINTS")

    # Slice 7: bridge wiring. The orchestrator NEVER pipes the real
    # Anthropic key into the sprite — the bridge talks to api.anthropic.com
    # via the orchestrator's `/api/_internal/anthropic-proxy/{sandbox_id}`
    # route (slice 8), and the proxy adds the real key server-side.
    # `SecretStr` so the value masks on any accidental repr / log /
    # `settings.model_dump()`.
    anthropic_api_key: SecretStr = Field(default=SecretStr(""), alias="ANTHROPIC_API_KEY")
    claude_auth_mode: Literal[
        "platform_api_key", "user_oauth", "user_api_key"
    ] = Field(default="platform_api_key", alias="CLAUDE_AUTH_MODE")
    bridge_max_live_chats_per_sandbox: int = Field(
        default=5, alias="MAX_LIVE_CHATS_PER_SANDBOX"
    )
    bridge_idle_after_disconnect_s: int = Field(
        default=300, alias="IDLE_AFTER_DISCONNECT_S"
    )

    @property
    def is_production(self) -> bool:
        return False


settings = Settings()  # pyright: ignore[reportCallIssue]
