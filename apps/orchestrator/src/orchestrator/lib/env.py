from pathlib import Path

from pydantic import Field
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
    auth_secret: str = Field(alias="AUTH_SECRET")
    github_oauth_client_id: str = Field(alias="GITHUB_OAUTH_CLIENT_ID")
    github_oauth_client_secret: str = Field(alias="GITHUB_OAUTH_CLIENT_SECRET")
    orchestrator_base_url: str = Field(alias="ORCHESTRATOR_BASE_URL")

    @property
    def is_production(self) -> bool:
        return False


settings = Settings()  # pyright: ignore[reportCallIssue]
