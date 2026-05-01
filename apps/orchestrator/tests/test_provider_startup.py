"""Provider selection at startup must be explicit — no silent fallback when
SPRITES_TOKEN is empty."""

from unittest.mock import patch

import pytest
from orchestrator.lib.env import Settings
from orchestrator.lib.provider_factory import build_sandbox_provider
from sandbox_provider import MockSandboxProvider, SpritesProvider


def _settings_with(**overrides: object) -> Settings:
    return Settings(  # pyright: ignore[reportCallIssue]
        WEB_BASE_URL="http://localhost:5173",
        ORCHESTRATOR_BASE_URL="http://localhost:3001",
        AUTH_SECRET="x",
        GITHUB_OAUTH_CLIENT_ID="x",
        GITHUB_OAUTH_CLIENT_SECRET="x",
        MONGODB_URI="mongodb://localhost:27017/test",
        **overrides,  # pyright: ignore[reportArgumentType]
    )


def test_sprites_with_empty_token_aborts() -> None:
    s = _settings_with(SANDBOX_PROVIDER="sprites", SPRITES_TOKEN="")
    with patch("orchestrator.lib.provider_factory.settings", s):
        with pytest.raises(RuntimeError, match="SPRITES_TOKEN is empty"):
            build_sandbox_provider()


def test_sprites_with_token_returns_sprites_provider() -> None:
    s = _settings_with(SANDBOX_PROVIDER="sprites", SPRITES_TOKEN="real-token")
    with patch("orchestrator.lib.provider_factory.settings", s):
        provider = build_sandbox_provider()
        assert isinstance(provider, SpritesProvider)


def test_mock_returns_mock_provider() -> None:
    s = _settings_with(SANDBOX_PROVIDER="mock")
    with patch("orchestrator.lib.provider_factory.settings", s):
        provider = build_sandbox_provider()
        assert isinstance(provider, MockSandboxProvider)
