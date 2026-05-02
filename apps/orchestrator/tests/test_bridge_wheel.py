"""Bridge wheel bundle builder — slice 8 phase 0b."""

from __future__ import annotations

import pytest

from orchestrator.services.bridge_wheel import (
    build_bridge_wheel_bundle,
    reset_cache_for_tests,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_cache_for_tests()


def test_build_produces_bridge_and_workspace_wheels() -> None:
    bundle = build_bridge_wheel_bundle()
    names = sorted(w.filename for w in bundle.wheels)
    # Bridge + four workspace deps (slice 8 brief §1).
    assert any(n.startswith("bridge-") for n in names)
    assert any(n.startswith("shared_models-") for n in names)
    assert any(n.startswith("agent_config-") for n in names)
    assert any(n.startswith("repo_introspection-") for n in names)
    assert any(n.startswith("github_integration-") for n in names)
    # Wheels we don't ship to the sprite are filtered out.
    assert not any(n.startswith("orchestrator-") for n in names)
    assert not any(n.startswith("db-") for n in names)
    assert not any(n.startswith("sandbox_provider-") for n in names)


def test_combined_sha_stable_across_rebuilds() -> None:
    """Two builds against the same source tree must produce the same
    combined sha — that's how the reconciler skips redundant uploads."""
    a = build_bridge_wheel_bundle()
    reset_cache_for_tests()
    b = build_bridge_wheel_bundle(force=True)
    assert a.combined_sha == b.combined_sha


def test_cache_skips_rebuild() -> None:
    a = build_bridge_wheel_bundle()
    b = build_bridge_wheel_bundle()
    # Same Bundle instance returned from cache (identity check, not eq).
    assert a is b


def test_bridge_wheel_filename_points_into_wheels() -> None:
    bundle = build_bridge_wheel_bundle()
    # The filename the reconciler passes to `uv pip install` must match
    # exactly one of the uploaded wheels.
    assert bundle.find(bundle.bridge_wheel_filename.split("-")[0] + "-") is not None
    assert bundle.bridge_wheel_filename.startswith("bridge-")


def test_each_wheel_sha_matches_content() -> None:
    import hashlib

    bundle = build_bridge_wheel_bundle()
    for w in bundle.wheels:
        assert hashlib.sha256(w.content).hexdigest() == w.sha256
