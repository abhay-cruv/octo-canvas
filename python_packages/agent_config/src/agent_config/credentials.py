"""Pluggable Claude credentials.

Per [Plan.md §14.7](../../../../docs/Plan.md). v1 ships a single impl
(`PlatformApiKeyCredentials`) that reads `ANTHROPIC_API_KEY` from the
process env. The Protocol exists so OAuth (`user_oauth`) and BYOK
(`user_api_key`) can land later as new impls + a `User.claude_auth_mode`
flip — no schema migration. The bridge always asks the Protocol for
the env-var dict it should hand to the `claude` CLI subprocess.
"""

from __future__ import annotations

import os
from typing import Protocol


class CredentialsError(Exception):
    """Raised by an impl when it cannot resolve credentials at the moment
    the bridge asks for them. Sanitized — never includes the token."""


class ClaudeCredentials(Protocol):
    """How the bridge asks for Claude auth at session-spawn time.

    `env()` returns the additional env vars to overlay onto the `claude`
    CLI subprocess. The impl decides whether to read from process env,
    a vault, an OAuth refresh, etc.
    """

    mode: str

    def env(self) -> dict[str, str]:
        """Return the env-var overlay. Raises `CredentialsError` if the
        impl cannot produce credentials right now."""
        ...


class PlatformApiKeyCredentials:
    """v1 default. Reads `ANTHROPIC_API_KEY` from the bridge's process
    env and hands it to the `claude` CLI subprocess.

    **Security note (slice 7):** the bridge's `ANTHROPIC_API_KEY` is
    NOT the platform's real Anthropic key. The orchestrator's bridge-
    launch path pipes a per-sandbox synthetic token (the same
    `BRIDGE_TOKEN` that authenticates the WSS handshake) plus
    `ANTHROPIC_BASE_URL` pointing at the orchestrator's proxy route.
    The real key only exists in the orchestrator's process memory and
    is added to outbound Anthropic requests there. From this impl's
    point of view the key is opaque — we just forward whatever env
    var was set.

    `__repr__` is overridden so accidental logging of the credential
    object never prints the secret.
    """

    mode = "platform_api_key"

    def __init__(self, *, env_var: str = "ANTHROPIC_API_KEY") -> None:
        self._env_var = env_var

    def env(self) -> dict[str, str]:
        value = os.environ.get(self._env_var, "")
        if not value:
            raise CredentialsError(
                f"{self._env_var} not set — bridge cannot authenticate to Anthropic"
            )
        return {self._env_var: value}

    def __repr__(self) -> str:
        return f"PlatformApiKeyCredentials(env_var={self._env_var!r}, value=***)"
