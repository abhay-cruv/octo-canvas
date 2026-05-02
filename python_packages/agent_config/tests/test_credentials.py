import pytest

from agent_config.credentials import (
    ClaudeCredentials,
    CredentialsError,
    PlatformApiKeyCredentials,
)


def test_platform_api_key_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    creds = PlatformApiKeyCredentials()
    assert creds.mode == "platform_api_key"
    assert creds.env() == {"ANTHROPIC_API_KEY": "sk-ant-test"}


def test_platform_api_key_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(CredentialsError):
        PlatformApiKeyCredentials().env()


def test_platform_api_key_satisfies_protocol() -> None:
    # Structural check: the impl is assignable to the Protocol.
    creds: ClaudeCredentials = PlatformApiKeyCredentials()
    assert creds.mode == "platform_api_key"


def test_custom_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALT_KEY", "abc")
    creds = PlatformApiKeyCredentials(env_var="ALT_KEY")
    assert creds.env() == {"ALT_KEY": "abc"}
