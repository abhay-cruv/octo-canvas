"""Slice 7 — `BridgeRuntimeConfig.env_for` produces the env-var overlay
the reconciler will apply at bridge-launch time. Token minting is no
longer at provision; it happens when the bridge daemon is launched
(slice 8 wires that). For slice 7 we only verify the env-overlay
shape so the token-rotation-at-launch path can rely on it."""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from db import mongo
from db.models import User
from orchestrator.services.sandbox_manager import (
    BridgeRuntimeConfig,
    SandboxManager,
    _hash_bridge_token,  # pyright: ignore[reportPrivateUsage]
    mint_bridge_token,
)
from sandbox_provider import MockSandboxProvider


@pytest_asyncio.fixture
async def _db() -> "object":
    await mongo.connect("mongodb://localhost:27017/octo_canvas_test")
    await mongo.drop_all_collections()
    await mongo.disconnect()
    await mongo.connect("mongodb://localhost:27017/octo_canvas_test")
    try:
        yield None
    finally:
        await mongo.disconnect()


def _config() -> BridgeRuntimeConfig:
    return BridgeRuntimeConfig(
        orchestrator_base_url="https://orch.test",
        _anthropic_api_key="sk-ant-fake",
        claude_auth_mode="platform_api_key",
        max_live_chats_per_sandbox=5,
        idle_after_disconnect_s=300,
    )


async def _seed_user() -> User:
    now = datetime.now(UTC)
    user = User(
        github_user_id=99,
        github_username="u99",
        email="u99@e.com",
        last_signed_in_at=now,
        created_at=now,
        updated_at=now,
        github_access_token="gh",
    )
    await user.create()
    return user


def test_env_for_builds_full_overlay() -> None:
    cfg = _config()
    token = mint_bridge_token()
    env = cfg.env_for(sandbox_id="sbx123", bridge_token=token)
    assert env["BRIDGE_TOKEN"] == token
    assert env["CLAUDE_AUTH_MODE"] == "platform_api_key"
    assert env["MAX_LIVE_CHATS_PER_SANDBOX"] == "5"
    assert env["IDLE_AFTER_DISCONNECT_S"] == "300"
    assert env["ORCHESTRATOR_WS_URL"] == "wss://orch.test/ws/bridge/sbx123"
    # Both base-URL vars set: CLAUDE_CODE_API_BASE_URL is the priority
    # the CLI checks first; ANTHROPIC_BASE_URL is the fallback.
    proxy = "https://orch.test/api/_internal/anthropic-proxy/sbx123"
    assert env["CLAUDE_CODE_API_BASE_URL"] == proxy
    assert env["ANTHROPIC_BASE_URL"] == proxy
    # Bearer-mode auth via ANTHROPIC_AUTH_TOKEN. We deliberately do
    # NOT set ANTHROPIC_API_KEY (it would be lower-precedence noise).
    assert env["ANTHROPIC_AUTH_TOKEN"] == token
    assert "ANTHROPIC_API_KEY" not in env


def test_env_for_never_leaks_real_anthropic_key() -> None:
    cfg = BridgeRuntimeConfig(
        orchestrator_base_url="https://orch.test",
        _anthropic_api_key="sk-ant-real-secret",
    )
    env = cfg.env_for(sandbox_id="sbx", bridge_token="bridge-tok")
    # Audit every value — `sk-ant-real-secret` must never appear.
    for key, value in env.items():
        assert "sk-ant-real-secret" not in value, f"leaked via {key}={value!r}"


def test_repr_masks_secret() -> None:
    cfg = BridgeRuntimeConfig(
        orchestrator_base_url="https://orch.test",
        _anthropic_api_key="sk-ant-real-secret",
    )
    rep = repr(cfg)
    assert "sk-ant-real-secret" not in rep
    assert str(cfg).count("sk-ant-real-secret") == 0


def test_env_for_blank_base_url_yields_empty_urls() -> None:
    cfg = BridgeRuntimeConfig(orchestrator_base_url="", _anthropic_api_key="")
    env = cfg.env_for(sandbox_id="sbx", bridge_token="t")
    assert env["ORCHESTRATOR_WS_URL"] == ""
    assert env["ANTHROPIC_BASE_URL"] == ""
    assert env["CLAUDE_CODE_API_BASE_URL"] == ""


def test_mint_bridge_token_is_url_safe_and_long() -> None:
    token = mint_bridge_token()
    # `secrets.token_urlsafe(32)` → 43-char base64url string.
    assert len(token) >= 40
    # Hashable + deterministic SHA-256.
    h = _hash_bridge_token(token)
    assert len(h) == 64
    int(h, 16)


@pytest.mark.asyncio
async def test_provision_no_longer_mints_token_at_create(_db: object) -> None:
    """Token minting moved to bridge-launch time (reconciler). The
    provision path must NOT touch `bridge_token_hash`."""
    user = await _seed_user()
    assert user.id is not None
    provider = MockSandboxProvider()
    manager = SandboxManager(provider=provider, redis=None)
    sandbox = await manager.get_or_create(user.id)
    assert sandbox.bridge_token_hash is None
