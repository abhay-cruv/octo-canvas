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
    """v1 default. Forwards whichever Anthropic auth env var the bridge
    process was launched with — `ANTHROPIC_AUTH_TOKEN` (Bearer mode)
    OR `ANTHROPIC_API_KEY`.

    **Security note (slice 7):** the value is NOT the platform's real
    Anthropic key. The orchestrator's bridge-launch path pipes a
    per-sandbox synthetic token plus `ANTHROPIC_BASE_URL` pointing at
    the orchestrator's proxy. The real key lives only in the
    orchestrator's memory and is swapped in by the proxy on the
    upstream call.

    Bearer mode (`ANTHROPIC_AUTH_TOKEN` → `Authorization: Bearer ...`)
    is the canonical shape per `BridgeRuntimeConfig.env_for(...)` —
    that path deliberately omits `ANTHROPIC_API_KEY` because the CLI
    treats `ANTHROPIC_AUTH_TOKEN` as higher-priority. We try Bearer
    first, fall back to `ANTHROPIC_API_KEY` for legacy/test contexts.

    `__repr__` is overridden so accidental logging never prints the
    secret.
    """

    mode = "platform_api_key"

    # Order matters: Bearer-mode is the production shape; api-key is
    # the fallback for tests + legacy callers. The first env var that's
    # set wins, and only that one is returned in env() so the CLI sees
    # an unambiguous auth shape.
    _DEFAULT_ENV_VARS: tuple[str, ...] = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")

    def __init__(self, *, env_var: str | None = None) -> None:
        # Backwards-compat: callers that pass an explicit `env_var`
        # (e.g. tests pinning to ALT_KEY) still get single-var behavior.
        if env_var is not None:
            self._env_vars: tuple[str, ...] = (env_var,)
        else:
            self._env_vars = self._DEFAULT_ENV_VARS

    def env(self) -> dict[str, str]:
        for name in self._env_vars:
            value = os.environ.get(name, "")
            if value:
                return {name: value}
        raise CredentialsError(
            f"none of {self._env_vars} set — bridge cannot authenticate to Anthropic"
        )

    def __repr__(self) -> str:
        return f"PlatformApiKeyCredentials(env_vars={self._env_vars!r}, value=***)"
