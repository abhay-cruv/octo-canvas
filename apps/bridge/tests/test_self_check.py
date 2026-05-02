"""Slice 7 acceptance: --self-check exits 0 from inside a clean image build."""

from __future__ import annotations

import pytest

from bridge.main import main


def test_self_check_succeeds_without_bridge_token(monkeypatch: pytest.MonkeyPatch) -> None:
    # CI smoke runs `--self-check` from the Dockerfile build stage,
    # before any orchestrator could have minted a token. Must exit 0.
    monkeypatch.delenv("BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_WS_URL", raising=False)
    assert main(["--self-check"]) == 0


def test_self_check_with_token_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIDGE_TOKEN", "tok_abc")
    assert main(["--self-check"]) == 0


def test_run_without_token_but_with_orchestrator_url_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("ORCHESTRATOR_WS_URL", "wss://orch/ws/bridge/abc")
    # If the bridge has somewhere to dial, it must have a token.
    assert main([]) == 2


def test_version_flag_prints_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--version"]) == 0
    out = capsys.readouterr().out
    assert "bridge" in out
    assert "claude-cli" in out


def test_unsupported_auth_mode_self_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `user_oauth` is reserved by the Protocol but has no impl yet.
    monkeypatch.setenv("CLAUDE_AUTH_MODE", "user_oauth")
    with pytest.raises(SystemExit) as exc:
        main(["--self-check"])
    assert exc.value.code != 0
