"""Bridge env-var schema.

Single source of truth for what the bridge process reads from its
environment. The orchestrator pipes these into the sprite at provision
time (see `apps/orchestrator/src/orchestrator/services/sandbox_manager.py`).

Slice 7 ships only the schema + a couple of accessors; the bridge's
runtime loop is `main.py`. Slice 8 plugs `ORCHESTRATOR_WS_URL` into a
real WSS dialer — slice 7 leaves it optional and idles when blank.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ClaudeAuthMode = Literal["platform_api_key", "user_oauth", "user_api_key"]


_BAKED_CLI_VERSION_PATH = Path("/opt/bridge/CLAUDE_CLI_VERSION")


class BridgeSettings(BaseSettings):
    """Environment-driven bridge configuration.

    `BRIDGE_TOKEN` is the only required field at runtime; everything
    else has a default safe enough for slice 7's "boot + idle" mode.
    `--self-check` is allowed to construct without `BRIDGE_TOKEN` so
    CI smoke can pass before any orchestrator hands one over.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bridge_token: str = Field(default="", alias="BRIDGE_TOKEN")
    orchestrator_ws_url: str = Field(default="", alias="ORCHESTRATOR_WS_URL")
    # Slice 8: sandbox identity for the WSS path. Orchestrator pipes
    # this in alongside `BRIDGE_TOKEN` at bridge-launch time.
    sandbox_id: str = Field(default="", alias="SANDBOX_ID")
    max_live_chats_per_sandbox: int = Field(
        default=5, alias="MAX_LIVE_CHATS_PER_SANDBOX"
    )
    idle_after_disconnect_s: int = Field(
        default=300, alias="IDLE_AFTER_DISCONNECT_S"
    )
    claude_auth_mode: ClaudeAuthMode = Field(
        default="platform_api_key", alias="CLAUDE_AUTH_MODE"
    )
    # Slice 8: where chats run. Always `/work/` in v1 (no per-chat
    # worktrees) — overridable for tests. Branching defers to slice 9.
    work_root: str = Field(default="/work", alias="WORK_ROOT")


def load_settings() -> BridgeSettings:
    """Construct `BridgeSettings` from the live process env."""
    return BridgeSettings()  # pyright: ignore[reportCallIssue]


def baked_cli_version() -> str:
    """Version of the `claude` CLI baked into the sprite image.

    Read from `/opt/bridge/CLAUDE_CLI_VERSION` (written by the
    Dockerfile). Falls back to `apps/bridge/CLAUDE_CLI_VERSION` when
    running outside the sprite (dev / tests). Returns "unknown" if
    neither is present.
    """
    if _BAKED_CLI_VERSION_PATH.is_file():
        return _BAKED_CLI_VERSION_PATH.read_text().strip()
    here = Path(__file__).resolve()
    repo_pin = here.parents[3] / "CLAUDE_CLI_VERSION"
    if repo_pin.is_file():
        return repo_pin.read_text().strip()
    return "unknown"
