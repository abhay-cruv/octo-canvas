"""Slice 8 Phase 0b: build the bridge wheel + transitive workspace deps
for upload to a sprite.

The bridge runs in `/opt/bridge/.venv` (slice 8 Phase 0a). To install it
we ship:
- bridge-*.whl
- shared_models-*.whl
- agent_config-*.whl
- repo_introspection-*.whl
- github_integration-*.whl

PyPI deps (claude-agent-sdk, websockets, httpx, ...) resolve normally;
the workspace wheels are surfaced via `uv pip install --find-links`.

Caching: source-tree fingerprint (sha256 over every file under the
relevant package roots) keys an in-memory cache. Rebuilds are skipped
when content is unchanged. `uv build` itself takes ~5s on this repo,
so this is a small but real win during dev.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

# Workspace packages that ship to the sprite. Order matters only for
# diagnostics; install-time order is up to `uv pip install`.
_BUNDLED_PACKAGES = (
    "apps/bridge",
    "python_packages/shared_models",
    "python_packages/agent_config",
    "python_packages/repo_introspection",
    "python_packages/github_integration",
)

# Filename prefixes (matching the wheel naming uv emits) for the
# packages we keep from a `uv build --all-packages` run. Other wheels
# (orchestrator, db, sandbox_provider) are not needed on the sprite.
_KEEP_WHEEL_PREFIXES = (
    "bridge-",
    "shared_models-",
    "agent_config-",
    "repo_introspection-",
    "github_integration-",
)


@dataclass(frozen=True)
class BridgeWheel:
    filename: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class BridgeWheelBundle:
    wheels: tuple[BridgeWheel, ...]
    combined_sha: str  # sha256 over sorted (filename, sha256) tuples
    bridge_wheel_filename: str  # the one we pass to `uv pip install`

    def find(self, prefix: str) -> BridgeWheel | None:
        for w in self.wheels:
            if w.filename.startswith(prefix):
                return w
        return None


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    # services/bridge_wheel.py → orchestrator → src → orchestrator → apps → repo
    return here.parents[5]


def _source_fingerprint(root: Path) -> str:
    """sha256 over every source file in the bundled packages.
    Excludes __pycache__ / .pyc / .venv / dist / build / .egg-info."""
    h = hashlib.sha256()
    excludes = {"__pycache__", ".venv", "dist", "build", ".pytest_cache"}
    for pkg in _BUNDLED_PACKAGES:
        pkg_root = root / pkg
        if not pkg_root.is_dir():
            continue
        for p in sorted(pkg_root.rglob("*")):
            if not p.is_file():
                continue
            if any(part in excludes for part in p.parts):
                continue
            if p.suffix == ".pyc" or p.name.endswith(".egg-info"):
                continue
            h.update(str(p.relative_to(root)).encode())
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


_lock = Lock()
_cached_fingerprint: str | None = None
_cached_bundle: BridgeWheelBundle | None = None


def build_bridge_wheel_bundle(*, force: bool = False) -> BridgeWheelBundle:
    """Build (or return a cached copy of) the bridge wheel bundle.

    Raises subprocess.CalledProcessError if `uv build` fails.
    """
    global _cached_fingerprint, _cached_bundle
    root = _repo_root()
    fp = _source_fingerprint(root)
    with _lock:
        if not force and _cached_fingerprint == fp and _cached_bundle is not None:
            return _cached_bundle
        bundle = _build_uncached(root)
        _cached_fingerprint = fp
        _cached_bundle = bundle
        return bundle


def _build_uncached(root: Path) -> BridgeWheelBundle:
    """Run `uv build --all-packages` into a temp dir and pluck out the
    wheels we want."""
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError(
            "uv not found on PATH — required to build the bridge wheel bundle. "
            "Install via `curl -LsSf https://astral.sh/uv/install.sh | sh`."
        )
    with tempfile.TemporaryDirectory(prefix="octo-bridge-build-") as td:
        out = Path(td) / "dist"
        subprocess.run(
            [uv, "build", "--all-packages", "--wheel", "--out-dir", str(out)],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        wheels: list[BridgeWheel] = []
        bridge_filename: str | None = None
        for whl in sorted(out.glob("*.whl")):
            if not any(whl.name.startswith(p) for p in _KEEP_WHEEL_PREFIXES):
                continue
            content = whl.read_bytes()
            sha = hashlib.sha256(content).hexdigest()
            wheels.append(BridgeWheel(filename=whl.name, content=content, sha256=sha))
            if whl.name.startswith("bridge-"):
                bridge_filename = whl.name
        if bridge_filename is None:
            raise RuntimeError("uv build produced no bridge-*.whl")
        # Combined sha for change detection on the sandbox side. Stable
        # across rebuilds with identical source.
        combined = hashlib.sha256()
        for w in sorted(wheels, key=lambda x: x.filename):
            combined.update(w.filename.encode())
            combined.update(b"\0")
            combined.update(w.sha256.encode())
            combined.update(b"\0")
        return BridgeWheelBundle(
            wheels=tuple(wheels),
            combined_sha=combined.hexdigest(),
            bridge_wheel_filename=bridge_filename,
        )


def reset_cache_for_tests() -> None:
    """Test helper — clear the in-memory cache."""
    global _cached_fingerprint, _cached_bundle
    with _lock:
        _cached_fingerprint = None
        _cached_bundle = None
