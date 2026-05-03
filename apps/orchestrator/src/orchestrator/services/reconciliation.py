"""Per-sandbox reconciliation — slice 5b.

Diffs the sandbox's `/work` listing against the `Repo` rows bound to it,
issues clone/remove ops to converge, runs `apt-get install` for the union
of `system_packages` from every repo's introspection, and (if anything
mutated) snapshots a fresh `clean` checkpoint so Reset is millisecond-fast.

Event-driven only — invoked from sandbox/repo routes after the relevant
state change. No background timer in slice 5b.

Per-sandbox `asyncio.Lock` ensures serial execution: two concurrent
triggers (e.g. simultaneous connect-repo + wake) are serialized; the
second waits for the first then runs another pass against fresh state.
Mongo is canonical — the reconciler reads `Repo` rows and the sprite's
filesystem at the start of each pass and writes back at the end.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from beanie import PydanticObjectId
from db import mongo
from db.models import Repo, Sandbox, User
from pathlib import Path

from sandbox_provider import SandboxHandle, SpritesError

if TYPE_CHECKING:
    from orchestrator.services.sandbox_manager import BridgeRuntimeConfig
    from sandbox_provider import SandboxProvider

from orchestrator.services.bridge_wheel import (
    BridgeWheelBundle,
    build_bridge_wheel_bundle,
)

_logger = structlog.get_logger("reconciliation")

WORK_ROOT = "/work"
APT_TIMEOUT_S = 600
CLONE_TIMEOUT_S = 300

# Fixed-path git config + credentials. Decoupled from `$HOME` so we
# don't rely on env passthrough between exec calls being consistent —
# Sprites' exec sometimes drops/replaces env keys, which previously
# caused git_setup to write credentials under one HOME and clone to
# look under a different one. With `GIT_CONFIG_GLOBAL` pointing at a
# fixed file and the credential helper using an absolute path, every
# git invocation finds the same config and credentials.
GIT_CONFIG_PATH = "/etc/octo-canvas/gitconfig"
GIT_CRED_PATH = "/etc/octo-canvas/git-credentials"
GIT_ENV: dict[str, str] = {
    "GIT_CONFIG_GLOBAL": GIT_CONFIG_PATH,
    "GIT_TERMINAL_PROMPT": "0",
}


@dataclass
class ReconciliationResult:
    cloned: list[str] = field(default_factory=lambda: [])
    removed: list[str] = field(default_factory=lambda: [])
    failed: list[tuple[str, str]] = field(default_factory=lambda: [])
    apt_installed: list[str] = field(default_factory=lambda: [])
    # Slice 7: list of (manager, version) pairs the reconciler installed
    # in the `installing_runtimes` phase. Empty when nothing to install.
    runtimes_installed: list[tuple[str, str]] = field(default_factory=lambda: [])
    checkpoint_taken: bool = False
    new_checkpoint_id: str | None = None
    skipped: bool = False
    skipped_reason: str | None = None


# Slice 7: bridge prerequisites installed once per sprite by the
# `installing_bridge` phase. Sprites is already a VM, so we install nvm/
# pyenv/rbenv + the pinned `claude` CLI directly via `exec_oneshot`
# rather than baking a custom image. Pins live alongside the bridge
# source so a single PR bumps them. Bumping any of these rotates
# `BRIDGE_SETUP_FINGERPRINT` → reconciler re-runs `installing_bridge` on
# next pass; existing sprites pick up the new pin without a restart.
_NVM_PIN = "v0.40.3"
_PYENV_PIN = "v2.5.5"
_RBENV_PIN = "v1.3.2"
# Slice 8: system Node 20 LTS via official nodejs.org tarball — bypasses
# NodeSource's apt repo because Sprites occasionally runs on non-LTS
# Ubuntu codenames (questing/oracular/plucky) that NodeSource doesn't
# publish packages for. Tarball is codename-agnostic, lands node + npm
# + npx into /usr/local/{bin,lib,include,share} (on sudo's secure_path).
_NODE_PIN = "v24.15.0"
# rustup-init is one curl call; no version pin (rustup self-updates).
# `RUSTUP_HOME` / `CARGO_HOME` go to /usr/local so installs survive
# `rm -rf /work` (Reset).
_RUSTUP_HOME = "/usr/local/rustup"
_CARGO_HOME = "/usr/local/cargo"
# Go tarballs from go.dev/dl/. We install per-version into
# `/usr/local/go-versions/<version>` and symlink the highest-installed
# at `/usr/local/go-current` for the activation script's PATH.
_GO_INSTALL_ROOT = "/usr/local/go-versions"
# Slice 8: the bridge process runs in an isolated Python venv at
# `/opt/bridge/.venv` driven by uv-managed Python (NOT pyenv). pyenv is
# user territory — `pyenv global` flips must not break the bridge. uv
# downloads its own python-build-standalone interpreter under
# `UV_PYTHON_INSTALL_DIR=/usr/local/uv-python` so the venv survives Reset
# (which wipes `/work`, not `/opt` or `/usr/local`). Bumping
# `_BRIDGE_VENV_PYTHON` rotates `BRIDGE_SETUP_FINGERPRINT` and forces the
# venv to be recreated on the next reconcile.
_BRIDGE_VENV_PYTHON = "3.12"
_BRIDGE_VENV_DIR = "/opt/bridge/.venv"
_UV_PYTHON_INSTALL_DIR = "/usr/local/uv-python"


def _read_cli_pin() -> str:
    """Read `apps/bridge/CLAUDE_CLI_VERSION` (single line). The file is
    the canonical pin shared with `bridge.config.baked_cli_version()`.
    Returns "unknown" when the repo layout doesn't have the pin file
    (treats as a no-op for tests that don't care)."""
    here = Path(__file__).resolve()
    # services/reconciliation.py → orchestrator → src → orchestrator → apps
    repo_root = here.parents[5]
    pin = repo_root / "apps" / "bridge" / "CLAUDE_CLI_VERSION"
    if pin.is_file():
        return pin.read_text().strip()
    return "unknown"


_CLAUDE_CLI_PIN = _read_cli_pin()
BRIDGE_SETUP_FINGERPRINT = (
    f"nvm={_NVM_PIN};pyenv={_PYENV_PIN};rbenv={_RBENV_PIN};"
    f"claude={_CLAUDE_CLI_PIN};venv-py={_BRIDGE_VENV_PYTHON};"
    f"node={_NODE_PIN}"
)
BRIDGE_SETUP_TIMEOUT_S = 600


# Slice 7: bridge setup is split into two scripts so the slow
# manager/CLI installs can run in parallel with `git clone`s.
#
#   1. `_BRIDGE_SETUP_PRE` — apt baseline + Adoptium repo + git itself.
#      Fast (~30s on a fresh sprite, near-zero on subsequent passes).
#      MUST run before clones because clones need git on PATH; it also
#      grabs the dpkg lock so any other apt step in the reconciler
#      sequences after it.
#   2. `_BRIDGE_SETUP_REST` — runtime managers + system Node + the
#      pinned `claude` CLI + rustup + the Go install root. None of
#      these touch dpkg, so this script can run concurrently with
#      `git clone` of the user's repos. `installing_runtimes` (which
#      needs nvm/pyenv/rbenv on PATH) waits on this.
#
# Both scripts are idempotent at the shell level (`if [ ! -d ... ]` /
# `command -v ...`) and at the reconciler level (skipped entirely when
# `Sandbox.bridge_setup_fingerprint` already matches the current pins).
_BRIDGE_SETUP_PRE = f"""set -euo pipefail
log() {{ echo "[octo-setup-pre] $*"; }}

log "apt baseline"
sudo -n apt-get update -y
sudo -n apt-get install -y --no-install-recommends \\
    git curl wget ca-certificates gnupg build-essential pkg-config \\
    libssl-dev libffi-dev zlib1g-dev libbz2-dev libreadline-dev \\
    libsqlite3-dev liblzma-dev libncurses-dev tk-dev \\
    libpq-dev libxml2-dev libxslt1-dev libvips-dev libjpeg-dev libpng-dev

log "Adoptium apt repo (Java)"
# Adoptium only ships LTS Ubuntu pockets (focal/jammy/noble). Sprites
# may run on a non-LTS image (questing/oracular/plucky/...) — registering
# an unsupported codename breaks every subsequent `apt-get update` with
# "does not have a Release file". Map non-LTS to the most recent LTS
# (Adoptium debs are codename-tolerant; the same .deb installs fine on a
# newer Ubuntu). The script reconciles the source list every run rather
# than only-on-first-run so an existing broken file from a prior version
# of this script gets healed without manual cleanup.
RAW_CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
case "$RAW_CODENAME" in
    focal|jammy|noble) ADOPTIUM_CODENAME="$RAW_CODENAME" ;;
    *) ADOPTIUM_CODENAME=noble ;;
esac
ADOPTIUM_LINE="deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $ADOPTIUM_CODENAME main"
sudo -n install -d -m 0755 /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/adoptium.gpg ]; then
    wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public \\
        | sudo -n gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg
fi
# Always rewrite the source list (cheap; heals stale codenames from
# earlier broken runs).
echo "$ADOPTIUM_LINE" | sudo -n tee /etc/apt/sources.list.d/adoptium.list >/dev/null
sudo -n apt-get update -y

log "go install root + version-manager dirs"
sudo -n install -d -m 0755 {_GO_INSTALL_ROOT}
sudo -n install -d -m 0755 {_RUSTUP_HOME} {_CARGO_HOME}

log "pre done"
"""


_BRIDGE_SETUP_REST = f"""set -euo pipefail
log() {{ echo "[octo-setup] $*"; }}

log "nvm @ {_NVM_PIN}"
if [ ! -d /usr/local/nvm ]; then
    sudo -n git clone --branch {_NVM_PIN} --depth 1 \\
        https://github.com/nvm-sh/nvm.git /usr/local/nvm
fi

log "pyenv @ {_PYENV_PIN}"
if [ ! -d /usr/local/pyenv ]; then
    sudo -n git clone --branch {_PYENV_PIN} --depth 1 \\
        https://github.com/pyenv/pyenv.git /usr/local/pyenv
fi

log "rbenv @ {_RBENV_PIN}"
if [ ! -d /usr/local/rbenv ]; then
    sudo -n git clone --branch {_RBENV_PIN} --depth 1 \\
        https://github.com/rbenv/rbenv.git /usr/local/rbenv
    sudo -n git clone --depth 1 \\
        https://github.com/rbenv/ruby-build.git \\
        /usr/local/rbenv/plugins/ruby-build
fi

log "rustup (no toolchain - installing_runtimes installs per-repo versions)"
if [ ! -x {_CARGO_HOME}/bin/rustup ]; then
    sudo -n env RUSTUP_HOME={_RUSTUP_HOME} CARGO_HOME={_CARGO_HOME} \\
        bash -c "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \\
                | sh -s -- -y --default-toolchain none --no-modify-path"
    sudo -n chmod -R a+rX {_CARGO_HOME} {_RUSTUP_HOME}
fi

log "activation script"
sudo -n tee /etc/profile.d/octo-runtimes.sh >/dev/null <<'PROFILE'
export NVM_DIR=/usr/local/nvm
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
export PYENV_ROOT=/usr/local/pyenv
export PATH="$PYENV_ROOT/bin:$PATH"
command -v pyenv >/dev/null 2>&1 && eval "$(pyenv init -)"
export RBENV_ROOT=/usr/local/rbenv
export PATH="$RBENV_ROOT/bin:$PATH"
command -v rbenv >/dev/null 2>&1 && eval "$(rbenv init -)"
export RUSTUP_HOME=__RUSTUP_HOME__
export CARGO_HOME=__CARGO_HOME__
export PATH="$CARGO_HOME/bin:$PATH"
# Go: highest-installed version is symlinked at __GO_CURRENT__.
export PATH="__GO_CURRENT__/bin:$PATH"
PROFILE
sudo -n sed -i \\
    -e 's|__RUSTUP_HOME__|{_RUSTUP_HOME}|g' \\
    -e 's|__CARGO_HOME__|{_CARGO_HOME}|g' \\
    -e 's|__GO_CURRENT__|/usr/local/go-current|g' \\
    /etc/profile.d/octo-runtimes.sh
sudo -n chmod 0755 /etc/profile.d/octo-runtimes.sh

log "system Node {_NODE_PIN} via official tarball (codename-agnostic)"
# Bypass NodeSource's apt repo because it doesn't publish for every
# Ubuntu codename Sprites ships (questing/oracular/plucky). The
# nodejs.org tarball drops node+npm+npx into /usr/local/bin etc.
# which is on sudo's secure_path. Idempotent: skip when the pinned
# version is already at /usr/local/bin/node.
if [ ! -x /usr/local/bin/node ] || \\
   [ "$(/usr/local/bin/node --version 2>/dev/null)" != "{_NODE_PIN}" ]; then
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64) NODE_ARCH=x64 ;;
        aarch64|arm64) NODE_ARCH=arm64 ;;
        *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
    esac
    NODE_TARBALL="node-{_NODE_PIN}-linux-${{NODE_ARCH}}.tar.xz"
    NODE_URL="https://nodejs.org/dist/{_NODE_PIN}/${{NODE_TARBALL}}"
    TMP=$(mktemp -d)
    curl -fsSL "$NODE_URL" -o "$TMP/node.tar.xz"
    sudo -n tar -xJ -C /usr/local --strip-components=1 -f "$TMP/node.tar.xz"
    rm -rf "$TMP"
fi

log "verify node + npm"
/usr/local/bin/node --version
/usr/local/bin/npm --version

log "claude CLI @ {_CLAUDE_CLI_PIN}"
# Use absolute paths so sudo's secure_path lookup never matters.
# `npm` is `#!/usr/bin/env node` — passing PATH=/usr/local/bin to sudo
# guarantees `env node` resolves correctly even on stripped sudoers
# configs.
sudo -n env "PATH=/usr/local/bin:/usr/bin:/bin" \\
    /usr/local/bin/npm install -g @anthropic-ai/claude-code@{_CLAUDE_CLI_PIN}

log "uv (system-wide install for bridge venv)"
# uv at /usr/local/bin/uv — on every shell's PATH, no profile.d edit
# needed. INSTALLER_NO_MODIFY_PATH=1 stops the installer from touching
# user shell rc files; UV_INSTALL_DIR places the binary system-wide.
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh \\
        | sudo -n env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
fi

log "/opt/bridge skeleton + isolated Python {_BRIDGE_VENV_PYTHON} venv"
# /opt/bridge survives Reset (which wipes /work). Owned by the sprite
# user so `fs_write` (slice 6) and the bridge process itself can write
# to /opt/bridge/wheels and /opt/bridge/.venv without sudo.
SPRITE_USER=$(id -un)
sudo -n install -d -m 0755 -o "$SPRITE_USER" -g "$SPRITE_USER" \\
    /opt/bridge /opt/bridge/wheels {_UV_PYTHON_INSTALL_DIR}
# `--python-preference only-managed` forces uv to use its own
# python-build-standalone build, NOT pyenv's or system Python — so
# `pyenv global 3.13` (user territory) cannot break the bridge.
# UV_PYTHON_INSTALL_DIR pins the managed Python to /usr/local so it
# survives /work resets and is shared across venv recreations.
if [ ! -x {_BRIDGE_VENV_DIR}/bin/python ]; then
    UV_PYTHON_INSTALL_DIR={_UV_PYTHON_INSTALL_DIR} \\
        uv venv {_BRIDGE_VENV_DIR} \\
            --python {_BRIDGE_VENV_PYTHON} \\
            --python-preference only-managed
fi

log "verify"
bash -lc 'claude --version'
bash -lc 'nvm --version'
bash -lc 'pyenv --version'
bash -lc 'rbenv --version'
bash -lc 'rustup --version'
uv --version
{_BRIDGE_VENV_DIR}/bin/python --version

log "done"
"""


# Slice 7: per-runtime install commands the `installing_runtimes` phase
# fires for each `(name, version)` pair. The managers themselves are
# installed by `installing_bridge` (above). v1 wires only node/python/
# ruby — go/rust/java are detected by introspection but the toolchains
# are heterogeneous; the agent can still install ad-hoc during chat.
#
# pyenv/rbenv ship Python/Ruby version recipes via their bundled
# `python-build` / `ruby-build` plugins. Those plugin databases must
# be current to know about a release — pyenv 2.4.15 (our pin) was
# tagged before Python 3.13.5 existed, so a naive `pyenv install
# 3.13.5` fails with `definition not found`. The fallback retries
# once after `sudo -n git pull` inside the relevant repo (exactly what
# pyenv prints to stderr on miss). Cheap on a hit, self-heals on a
# miss without rotating the pin.
_RUNTIME_INSTALL_CMDS: dict[str, list[str]] = {
    # `bash -lc` so /etc/profile.d/octo-runtimes.sh is sourced and
    # `nvm`/`pyenv`/`rbenv`/`rustup` + the go-current symlink are on
    # PATH.
    # `nvm install` already activates the version it just installed
    # for the *current* shell, but we also set it as the default so a
    # fresh terminal lands on it without needing `nvm use {version}`.
    "node": ["bash", "-lc", "nvm install {version} && nvm alias default {version}"],
    # NB: pyenv/rbenv were `git clone --depth 1 --branch <pin>` so the
    # working tree sits on a detached HEAD at the tag — `git pull` is a
    # no-op (no tracking branch). When `installing_runtimes` asks for a
    # version newer than the pin's catalog, we fetch the latest master
    # with depth 1 and check out FETCH_HEAD before retrying. This
    # advances the plugin's recipe database without needing a full
    # un-shallow clone.
    "python": [
        "bash",
        "-lc",
        # Use uv-managed prebuilt cpython (python-build-standalone)
        # instead of pyenv's compile-from-source. ~30s download vs.
        # 10+ min `gcc` on a 1-vCPU sprite. Same install-dir as the
        # bridge's own python (created in _BRIDGE_SETUP_REST and owned
        # by the sprite user, so no sudo for the install itself).
        # Symlinks into /usr/local/bin make the version reachable as
        # `python3` and `python<MAJ.MIN>` for any interactive shell —
        # /usr/local/bin sits ahead of pyenv shims on PATH so the
        # global default lands here. Repos with a `.python-version`
        # file still hit pyenv's shim if they activate pyenv first,
        # but the default-resolution case no longer compiles cpython.
        'set -euo pipefail; '
        'V="{version}"; '
        'UV_PYTHON_INSTALL_DIR=/usr/local/uv-python '
        'uv python install "$V"; '
        'PYBIN=$(UV_PYTHON_INSTALL_DIR=/usr/local/uv-python '
        'uv python find "$V" --python-preference only-managed); '
        'sudo -n ln -sfn "$PYBIN" /usr/local/bin/python3; '
        'sudo -n ln -sfn "$PYBIN" /usr/local/bin/python; '
        'MM=$(echo "$V" | cut -d. -f1,2); '
        'sudo -n ln -sfn "$PYBIN" "/usr/local/bin/python${{MM}}"',
    ],
    "ruby": [
        "bash",
        "-lc",
        # Same `pyenv global` rationale — set this as rbenv's default
        # so `ruby` resolves outside of an `.ruby-version` repo.
        'rbenv install -s {version} || ('
        "echo 'rbenv install failed — updating ruby-build and retrying' "
        '&& sudo -n git -C "$RBENV_ROOT/plugins/ruby-build" fetch --depth 1 origin master '
        '&& sudo -n git -C "$RBENV_ROOT/plugins/ruby-build" checkout --quiet FETCH_HEAD '
        '&& rbenv install -s {version}'
        ') '
        '&& sudo -n tee "$RBENV_ROOT/version" >/dev/null <<<"{version}" '
        '&& rbenv rehash',
    ],
    # Java via Adoptium Temurin: introspection emits versions like
    # `17`, `17.0.13`, or `21.0.1`; we install the matching major
    # (`temurin-<major>-jdk`). Multiple majors coexist as separate
    # packages under `/usr/lib/jvm/`; system `java` defaults to the
    # last installed (or whatever `update-alternatives` selects). The
    # agent picks the right `JAVA_HOME` per repo from there.
    "java": [
        "bash",
        "-lc",
        # `{{` / `}}` escape Python's `.format()` so `${MAJOR}` reaches
        # the shell verbatim. Introspection emits versions like `17`,
        # `17.0.13`, `21.0.1` — `cut -d. -f1` collapses them all to the
        # major.
        'MAJOR=$(echo "{version}" | cut -d. -f1) '
        "&& sudo -n apt-get install -y --no-install-recommends "
        '"temurin-${{MAJOR}}-jdk"',
    ],
    # Rust via rustup: versions look like `1.83.0` or `stable`.
    # `rustup toolchain install` is idempotent (already-installed is a
    # no-op + 0 exit); rustup self-updates so no retry-with-pull dance
    # is needed.
    "rust": [
        "bash",
        "-lc",
        "rustup toolchain install {version} --profile minimal --no-self-update",
    ],
    # Go: download the prebuilt amd64 tarball from go.dev/dl/, extract
    # to `/usr/local/go-versions/<version>/`, and re-point
    # `/usr/local/go-current` at the highest installed version (lex
    # sort works for `1.X.Y` strings up to two-digit minor/patch).
    # `command -v go` checks aren't useful — the install root is the
    # source of truth for "is this version present".
    "go": [
        "bash",
        "-lc",
        # `{{` / `}}` escape Python's `.format()` so `${V}` etc. reach
        # the shell verbatim.
        "set -euo pipefail; "
        'V="{version}"; '
        'TARGET="/usr/local/go-versions/${{V}}"; '
        'if [ ! -x "${{TARGET}}/bin/go" ]; then '
        "  TMP=$(mktemp -d); "
        '  curl -fsSL "https://go.dev/dl/go${{V}}.linux-amd64.tar.gz" '
        '    | tar -xz -C "${{TMP}}"; '
        '  sudo -n mkdir -p "${{TARGET}}"; '
        '  sudo -n cp -a "${{TMP}}/go/." "${{TARGET}}/"; '
        '  rm -rf "${{TMP}}"; '
        "fi; "
        "LATEST=$(ls -1 /usr/local/go-versions | sort -V | tail -1); "
        'sudo -n ln -sfn "/usr/local/go-versions/${{LATEST}}" /usr/local/go-current',
    ],
}
# Per-runtime install timeout. Most managers (nvm, rustup, java apt,
# go tarball) finish in <60s — they download prebuilt artifacts.
# pyenv + rbenv compile from source on slower sprites: cpython 3.13.x
# can take 10+ minutes on a 1-CPU VM, ruby is similar. 1200s gives
# enough headroom for the slowest legitimate compile path while still
# bounding a hung command.
RUNTIME_INSTALL_TIMEOUT_S = 1200


def _now() -> datetime:
    return datetime.now(UTC)


def _handle_of(sandbox: Sandbox) -> SandboxHandle:
    return SandboxHandle(
        provider=sandbox.provider_name,
        payload=dict(sandbox.provider_handle),
    )


# Per-sandbox lock map. Lives at module scope: per-process singleton, sized
# by the count of unique sandboxes ever reconciled by this orchestrator
# instance. Locks aren't reaped — they're cheap (one mutex per sandbox) and
# the alternative (cleanup on destroy) introduces a race.
_locks: dict[PydanticObjectId, asyncio.Lock] = {}


def _lock_for(sandbox_id: PydanticObjectId) -> asyncio.Lock:
    lock = _locks.get(sandbox_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[sandbox_id] = lock
    return lock


class Reconciler:
    """One per-orchestrator-process. Holds a `SandboxProvider` reference;
    routes pull this from `app.state.reconciler`.

    `bridge_config` is optional: when wired (via `app.lifespan`), the
    reconciler runs the slice-7 `installing_bridge` phase that installs
    nvm/pyenv/rbenv + the pinned `claude` CLI inside the sprite. Tests
    that don't care about bridge setup pass `None` and that phase is
    skipped entirely.
    """

    def __init__(
        self,
        provider: SandboxProvider,
        *,
        bridge_config: "BridgeRuntimeConfig | None" = None,
        bridge_session_fleet: "object | None" = None,
    ) -> None:
        self._provider = provider
        self._bridge_config = bridge_config
        # When BRIDGE_TRANSPORT=service_proxy, `bridge_session_fleet` is
        # a `BridgeSessionFleet` whose `ensure_started(sandbox)` PUT-s
        # + starts the Sprites Service for this sandbox's bridge daemon.
        # In dial_back mode it stays `None` and the legacy
        # `_ensure_bridge_running` (PID-file + nohup) runs instead.
        self._bridge_session_fleet = bridge_session_fleet

    async def reconcile(self, sandbox_id: PydanticObjectId) -> ReconciliationResult:
        async with _lock_for(sandbox_id):
            try:
                return await self._run(sandbox_id)
            except Exception as exc:
                # Defensive: any unexpected exception (network timeout
                # not wrapped by the provider, schema decode error,
                # etc.) bails the run cleanly instead of leaving repos
                # stuck at `pending` forever. Mark every still-pending
                # / cloning repo for this sandbox as `failed` so the
                # FE stops polling and the user can retry via Wake.
                _logger.warning(
                    "reconcile.unexpected_error",
                    sandbox_id=str(sandbox_id),
                    error=str(exc)[:300],
                )
                await mongo.repos.update_many(
                    {
                        "sandbox_id": sandbox_id,
                        "clone_status": {"$in": ["pending", "cloning"]},
                    },
                    {
                        "$set": {
                            "clone_status": "failed",
                            "clone_error": f"reconcile aborted: {str(exc)[:200]}",
                        }
                    },
                )
                # Clear any in-flight activity banner.
                if sandbox_id in _locks:
                    await mongo.sandboxes.update_one(
                        {"_id": sandbox_id},
                        {"$set": {"activity": None, "activity_detail": None}},
                    )
                result = ReconciliationResult()
                result.skipped = True
                result.skipped_reason = f"error:{type(exc).__name__}"
                return result

    async def _run(self, sandbox_id: PydanticObjectId) -> ReconciliationResult:
        result = ReconciliationResult()
        sandbox = await Sandbox.get(sandbox_id)
        if sandbox is None or sandbox.status in ("destroyed", "failed"):
            result.skipped = True
            result.skipped_reason = (
                "sandbox_missing" if sandbox is None else f"sandbox_status:{sandbox.status}"
            )
            return result
        if sandbox.status in ("provisioning", "resetting"):
            result.skipped = True
            result.skipped_reason = f"sandbox_transient:{sandbox.status}"
            return result
        # Don't auto-warm a paused sandbox just to clone. The user
        # explicitly chose `cold`; reconciliation will run on the next
        # explicit wake.
        if sandbox.status == "cold":
            result.skipped = True
            result.skipped_reason = "sandbox_cold"
            return result

        # Slice 7: clear any stale activity from a previous crashed pass.
        # The end-of-pass `_set_activity(None, None)` doesn't run if the
        # process died (timeout, OOM, redeploy), leaving the dashboard
        # showing a 5+ hour-old "installing_runtimes" banner. Reset at
        # pass start so each phase's first `_set_activity` call writes
        # a fresh timestamp.
        if sandbox.activity is not None:
            await _set_activity(sandbox, None, None)

        # Claim any orphan repos owned by this user. Covers users who
        # provisioned before slice 5b shipped (the route's fresh-provision
        # bulk-bind only fires on the *first* provision call).
        await mongo.repos.update_many(
            {"user_id": sandbox.user_id, "sandbox_id": None},
            {"$set": {"sandbox_id": sandbox_id, "clone_status": "pending"}},
        )
        repos = await Repo.find(Repo.sandbox_id == sandbox_id).to_list()
        user = await User.get(sandbox.user_id)
        if user is None:
            result.skipped = True
            result.skipped_reason = "user_missing"
            return result

        # 1. Diff: what's on disk vs what should be. Two-level walk
        # because Repo.full_name = "<owner>/<repo>" and Sprites' fs_list
        # returns one level at a time. The mock returns full_name strings
        # directly for back-compat with our pre-real-fs tests, so we
        # accept either shape.
        #
        # **Scope cleanup to tracked owners only.** Slice 6 lets users
        # create files freely under `/work/...` from the IDE. If we walked
        # every top-level dir and removed anything that didn't match a
        # connected `Repo.full_name`, we'd nuke the user's scratch
        # directories (`/work/notes.md`, `/work/playground/...`). So we
        # only descend into owner dirs that own at least one tracked repo,
        # and only remove `owner/repo` paths under those owners. A user
        # creating `/work/scratch/foo.md` is left alone because `scratch`
        # is not a tracked owner.
        #
        # Tradeoff: if a user disconnects every repo under owner `octocat`,
        # `/work/octocat/...` will survive on disk because `octocat` is no
        # longer tracked. We accept that — losing user files is much worse
        # than leaving stale clones around. Explicit Reset wipes `/work`
        # entirely and is the right escape hatch.
        wanted = {r.full_name: r for r in repos}
        tracked_owners = {full_name.split("/", 1)[0] for full_name in wanted}

        on_disk: set[str] = set()
        try:
            top = await self._provider.fs_list(_handle_of(sandbox), WORK_ROOT)
        except SpritesError as exc:
            if not exc.retriable and "not found" in str(exc).lower():
                top = []
            else:
                raise
        for entry in top:
            if entry.kind != "dir":
                continue
            if "/" in entry.name:
                # Mock-style: "owner/repo" already in one entry. Only
                # accept it if its owner is tracked.
                owner_part = entry.name.split("/", 1)[0]
                if owner_part in tracked_owners:
                    on_disk.add(entry.name)
                continue
            owner = entry.name
            if owner not in tracked_owners:
                # User-created scratch dir — leave it alone, don't even
                # list its children.
                continue
            try:
                sub = await self._provider.fs_list(_handle_of(sandbox), f"{WORK_ROOT}/{owner}")
            except SpritesError:
                continue
            for s in sub:
                if s.kind == "dir":
                    on_disk.add(f"{owner}/{s.name}")

        to_clone = [r for full_name, r in wanted.items() if full_name not in on_disk]
        to_remove = sorted(on_disk - set(wanted))
        mutated = False

        # Self-heal: any repo that's already on disk (e.g. after a
        # checkpoint-restore Reset) but whose Mongo `clone_status` says
        # otherwise — flip to `ready`. Without this, the FE shows
        # "pending" forever for repos that the fast-reset path already
        # restored from the checkpoint.
        for full_name, r in wanted.items():
            if full_name in on_disk and r.clone_status != "ready" and r.id is not None:
                await mongo.repos.update_one(
                    {"_id": r.id},
                    {
                        "$set": {
                            "clone_status": "ready",
                            "clone_path": f"{WORK_ROOT}/{full_name}",
                            "clone_error": None,
                        }
                    },
                )

        # 2.0. Bridge prerequisites pre-step (slice 7) — once per
        # sprite, idempotent via `Sandbox.bridge_setup_fingerprint`.
        # Pre installs the apt baseline + Adoptium repo so `git` is on
        # PATH for clones. The slow rest (managers + Node + claude CLI
        # + rustup + go install root) runs in parallel with clones
        # below. Skipped when the current pin set already matches.
        bridge_pre_ok = True
        if to_clone and self._bridge_config is not None:
            if sandbox.bridge_setup_fingerprint != BRIDGE_SETUP_FINGERPRINT:
                await _set_activity(sandbox, "installing_bridge", _CLAUDE_CLI_PIN)
            bridge_pre_ok = await self._bridge_setup_pre(sandbox)

        # 2a. One-time git setup. Writes ~/.gitconfig (identity) and
        # ~/.git-credentials (OAuth token) inside the sandbox so plain
        # `git clone https://github.com/...` works for the agent AND any
        # interactive shell session — no per-command auth flags needed.
        # Skipped when the configured token fingerprint matches the
        # user's current token, so this is essentially a no-op after the
        # first reconciliation pass.
        if to_clone:
            # Make sure `/work` exists before *anything* else cwds into
            # it. Fresh sprites don't have it.
            try:
                await self._provider.exec_oneshot(
                    _handle_of(sandbox),
                    ["mkdir", "-p", WORK_ROOT],
                    env={},
                    cwd="/",
                    timeout_s=15,
                )
            except SpritesError as exc:
                _logger.warning(
                    "reconcile.mkdir_work_failed",
                    sandbox_id=str(sandbox_id),
                    error=str(exc),
                )
            await _set_activity(sandbox, "configuring_git", None)
            await self._ensure_git_setup(sandbox, user)

        # 2b. apt install — once per pass, deduped union of every alive
        # repo's detected + override-merged system_packages. Skipped if empty.
        # `apt-get update` first — Sprites' base images often ship without
        # cached package lists, so `install` alone returns "Unable to
        # locate package …" or exits 1 with empty stderr.
        apt_pkgs = _merge_system_packages(repos)
        if apt_pkgs and to_clone:
            await _set_activity(sandbox, "installing_packages", ", ".join(apt_pkgs[:5]))
            try:
                upd = await self._provider.exec_oneshot(
                    _handle_of(sandbox),
                    # `sudo -n` so we don't hang on a password prompt if
                    # passwordless sudo isn't configured. dpkg requires
                    # root; Sprites exec runs unprivileged by default.
                    ["sudo", "-n", "apt-get", "update"],
                    env={"DEBIAN_FRONTEND": "noninteractive"},
                    cwd="/",
                    timeout_s=APT_TIMEOUT_S,
                )
                if upd.exit_code != 0:
                    _logger.warning(
                        "reconcile.apt_update_failed",
                        sandbox_id=str(sandbox_id),
                        exit_code=upd.exit_code,
                        stderr=upd.stderr[-500:],
                    )
                    await _set_reconcile_error(
                        sandbox,
                        f"apt-get update exit {upd.exit_code}: {upd.stderr.strip()[-200:]}",
                    )
                exec_result = await self._provider.exec_oneshot(
                    _handle_of(sandbox),
                    ["sudo", "-n", "apt-get", "install", "-y", *apt_pkgs],
                    env={"DEBIAN_FRONTEND": "noninteractive"},
                    cwd="/",
                    timeout_s=APT_TIMEOUT_S,
                )
                if exec_result.exit_code == 0:
                    result.apt_installed = list(apt_pkgs)
                else:
                    _logger.warning(
                        "reconcile.apt_install_failed",
                        sandbox_id=str(sandbox_id),
                        exit_code=exec_result.exit_code,
                        stderr=exec_result.stderr[-1000:],
                        stdout=exec_result.stdout[-500:],
                    )
                    await _set_reconcile_error(
                        sandbox,
                        f"apt install exit {exec_result.exit_code}: {exec_result.stderr.strip()[-200:]}",
                    )
            except SpritesError as exc:
                _logger.warning(
                    "reconcile.apt_install_error",
                    sandbox_id=str(sandbox_id),
                    error=str(exc),
                )
                await _set_reconcile_error(
                    sandbox, f"apt install: {str(exc)[:200]}"
                )

        # 3. Clones run in parallel with bridge_setup_rest. Clones only
        # need git on PATH (provided by bridge_setup_pre above) and
        # don't touch /usr/local/* where bridge-rest writes — so the
        # two are race-free. Clones are still serialized within
        # themselves (one git clone at a time per sandbox; Sprites
        # exec sessions don't always like concurrent commands).
        bridge_rest_task: asyncio.Task[None] | None = None
        if (
            bridge_pre_ok
            and self._bridge_config is not None
            and sandbox.bridge_setup_fingerprint != BRIDGE_SETUP_FINGERPRINT
        ):
            bridge_rest_task = asyncio.create_task(self._bridge_setup_rest(sandbox))

        for repo in to_clone:
            await asyncio.sleep(0)  # cooperative cancellation point
            fresh = await Sandbox.get(sandbox_id)
            if fresh is None or fresh.status not in ("warm", "running"):
                _logger.info(
                    "reconcile.aborted",
                    sandbox_id=str(sandbox_id),
                    reason=f"status:{fresh.status if fresh else 'missing'}",
                )
                break
            await _set_activity(sandbox, "cloning", repo.full_name)
            ok = await self._clone_one(sandbox, repo, user.github_access_token)
            if ok:
                result.cloned.append(repo.full_name)
                mutated = True
            else:
                result.failed.append((repo.full_name, repo.clone_error or "unknown"))

        if bridge_rest_task is not None:
            # Wait for bridge_setup_rest before installing_runtimes —
            # the per-repo nvm/pyenv/rbenv/rustup/go installs need the
            # managers it sets up. If clones finished first, this is
            # the part of the wait the user actually feels.
            await _set_activity(sandbox, "installing_bridge", _CLAUDE_CLI_PIN)
            await bridge_rest_task

        # 2b. Bridge wheel install (slice 8 phase 0b). Builds the wheel
        # bundle locally + uploads + uv pip installs into
        # /opt/bridge/.venv. Idempotent on Sandbox.bridge_wheel_sha —
        # most reconcile passes are no-ops. Only runs when bridge setup
        # has completed (the venv must exist).
        if (
            self._bridge_config is not None
            and sandbox.bridge_setup_fingerprint == BRIDGE_SETUP_FINGERPRINT
        ):
            await self._install_bridge_wheel(sandbox)

        # 2bb. Launch (or relaunch) the bridge daemon (slice 8 phase 8c).
        # Mints a fresh BRIDGE_TOKEN, persists its hash, kills any
        # existing bridge.main, starts a new one via nohup. Token
        # rotation on every relaunch — the bridge dials home with the
        # new token and the WSS handler validates against the freshly
        # persisted hash.
        if (
            self._bridge_config is not None
            and sandbox.bridge_setup_fingerprint == BRIDGE_SETUP_FINGERPRINT
            and sandbox.bridge_wheel_sha is not None
        ):
            if self._bridge_session_fleet is not None:
                # service_proxy: PUT the bridge service def + POST start.
                # Idempotent — already-running services just refresh env.
                # The legacy `_ensure_bridge_running` is left intact for
                # dial_back mode but never reached here.
                try:
                    await self._bridge_session_fleet.ensure_started(sandbox)  # type: ignore[attr-defined]
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "reconcile.bridge_service_start_failed",
                        sandbox_id=str(sandbox_id),
                        error=str(exc)[:200],
                    )
            else:
                await self._ensure_bridge_running(sandbox)

        # 2c. Language-runtime install (slice 7). Deduped union across
        # repos; each (manager, version) installed once. Best-effort —
        # failures set `Repo.runtime_install_error` for the affected
        # repos but never block subsequent passes (a missing runtime
        # degrades to "agent installs ad-hoc" rather than data loss).
        # Runs after clones because clones don't depend on it; clones
        # already happened in parallel with bridge_setup_rest above.
        runtime_targets = _merge_runtime_targets(repos)
        # Skip `installing_runtimes` entirely when bridge setup hasn't
        # finished — nvm/pyenv/rbenv/rustup aren't on PATH yet, so every
        # `nvm install <ver>` would exit 127 (command not found) and
        # plaster `Repo.runtime_install_error` with noise. The next
        # reconcile pass after bridge setup succeeds will re-run runtime
        # install cleanly.
        bridge_setup_done = (
            sandbox.bridge_setup_fingerprint == BRIDGE_SETUP_FINGERPRINT
        )
        if runtime_targets and not bridge_setup_done:
            _logger.info(
                "reconcile.skip_runtime_install",
                sandbox_id=str(sandbox_id),
                reason="bridge_setup_not_done",
                targets=runtime_targets,
            )
        if runtime_targets and bridge_setup_done:
            await _set_activity(
                sandbox,
                "installing_runtimes",
                ", ".join(f"{m} {v}" for m, v in runtime_targets[:3]),
            )
            installed, install_errors = await self._install_runtimes(
                sandbox, runtime_targets
            )
            result.runtimes_installed = installed
            for repo in repos:
                # Determine each repo's expected runtimes; mark error if
                # any of them are in `install_errors`. Mutates the
                # in-memory `Repo` so any later save doesn't wipe the
                # field; persists right away too so the FE sees it.
                repo_targets = _runtime_targets_for(repo)
                missing = [t for t in repo_targets if t in install_errors]
                if missing:
                    detail = "; ".join(
                        f"{m} {v}: {install_errors[(m, v)]}" for m, v in missing
                    )
                    repo.runtime_install_error = detail[:500]
                    # Don't bump `runtimes_installed_at` — the repo isn't
                    # in a fully-installed state. Leave whatever value
                    # was there (typically None on first attempt).
                else:
                    repo.runtime_install_error = None
                    # Mark the repo's runtimes as installed at this
                    # moment. The dashboard banner uses this timestamp
                    # to switch from "no state" to "Installed".
                    repo.runtimes_installed_at = _now()
                await repo.save()

        # 4. Removes — serialized.
        for full_name in to_remove:
            try:
                await self._provider.fs_delete(
                    _handle_of(sandbox),
                    f"{WORK_ROOT}/{full_name}",
                    recursive=True,
                )
                result.removed.append(full_name)
                mutated = True
            except SpritesError as exc:
                _logger.warning(
                    "reconcile.remove_failed",
                    sandbox_id=str(sandbox_id),
                    full_name=full_name,
                    error=str(exc),
                )

        # 5. Checkpoint only if mutated.
        if mutated:
            await _set_activity(sandbox, "checkpointing", None)
            try:
                ckpt = await self._provider.snapshot(
                    _handle_of(sandbox), comment=f"clean@{int(time.time())}"
                )
                sandbox.clean_checkpoint_id = str(ckpt)
                # Atomic field update for the same reason as
                # `_set_activity`: avoid clobbering concurrent destroy
                # / reset writes via a stale full-doc save.
                if sandbox.id is not None:
                    await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
                        {"$set": {"clean_checkpoint_id": str(ckpt)}}
                    )
                result.checkpoint_taken = True
                result.new_checkpoint_id = str(ckpt)
            except SpritesError as exc:
                _logger.warning(
                    "reconcile.snapshot_failed",
                    sandbox_id=str(sandbox_id),
                    error=str(exc),
                )

        await _set_activity(sandbox, None, None)
        _logger.info(
            "reconcile.done",
            sandbox_id=str(sandbox_id),
            cloned=len(result.cloned),
            removed=len(result.removed),
            failed=len(result.failed),
            checkpoint=result.new_checkpoint_id,
        )
        return result

    async def _verify_toolchain_present(self, sandbox: Sandbox) -> bool:
        """Quick filesystem check that everything `_BRIDGE_SETUP_REST`
        installs is still on disk. Reset preserves `/usr/local/*` and
        `/opt/bridge` by design, but a half-installed previous pass or
        manual cleanup can leave the fingerprint pointing at state that
        doesn't exist. Returns True when every probe passes.
        """
        probe = (
            "command -v uv >/dev/null "
            "&& [ -x /usr/local/bin/node ] "
            "&& [ -d /usr/local/nvm ] "
            "&& [ -d /usr/local/pyenv ] "
            "&& [ -d /usr/local/rbenv ] "
            f"&& [ -x {_CARGO_HOME}/bin/rustup ] "
            f"&& [ -x {_BRIDGE_VENV_DIR}/bin/python ]"
        )
        try:
            res = await self._provider.exec_oneshot(
                _handle_of(sandbox),
                ["bash", "-lc", probe],
                env={},
                cwd="/",
                timeout_s=15,
            )
        except Exception:  # noqa: BLE001 — probe is best-effort
            return False
        return res.exit_code == 0

    async def _bridge_setup_pre(self, sandbox: Sandbox) -> bool:
        """Slice 7: fast prereq for `git clone` + the rest of bridge
        setup. Runs the apt baseline, registers the Adoptium apt key,
        and creates the rust/go install roots. Returns True if the
        pre-step finished cleanly (caller then proceeds to clones +
        bridge-rest in parallel); False on failure (caller skips
        bridge-rest; clones still attempt — system git may already be
        present from a prior pass).

        Skipped entirely when `Sandbox.bridge_setup_fingerprint` already
        matches AND the on-disk toolchain still exists — when the probe
        fails (e.g. half-installed previous pass) the fingerprint is
        cleared and full setup re-runs.
        """
        if sandbox.bridge_setup_fingerprint == BRIDGE_SETUP_FINGERPRINT:
            if await self._verify_toolchain_present(sandbox):
                return True
            _logger.info(
                "reconcile.toolchain_missing_reinstalling",
                sandbox_id=str(sandbox.id),
            )
            sandbox.bridge_setup_fingerprint = None
            if sandbox.id is not None:
                await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
                    {"$set": {"bridge_setup_fingerprint": None}}
                )
        try:
            res = await self._provider.exec_oneshot(
                _handle_of(sandbox),
                ["bash", "-lc", _BRIDGE_SETUP_PRE],
                env={"DEBIAN_FRONTEND": "noninteractive"},
                cwd="/",
                timeout_s=BRIDGE_SETUP_TIMEOUT_S,
            )
        except SpritesError as exc:
            _logger.warning(
                "reconcile.bridge_setup_pre_error",
                sandbox_id=str(sandbox.id),
                error=str(exc)[:200],
            )
            await _set_reconcile_error(
                sandbox, f"bridge setup (pre): {str(exc)[:200]}"
            )
            return False
        if res.exit_code != 0:
            _logger.warning(
                "reconcile.bridge_setup_pre_failed",
                sandbox_id=str(sandbox.id),
                exit_code=res.exit_code,
                stderr=res.stderr[-1000:],
            )
            await _set_reconcile_error(
                sandbox,
                f"bridge setup (pre) exit {res.exit_code}: {res.stderr.strip()[-200:]}",
            )
            return False
        return True

    async def _bridge_setup_rest(self, sandbox: Sandbox) -> None:
        """Slice 7: slow part of bridge setup — runtime managers +
        system Node + pinned `claude` CLI + rustup. Designed to run
        concurrently with `git clone` of the user's repos (no dpkg
        lock contention, no shared state with clones). On success,
        persists `Sandbox.bridge_setup_fingerprint`; on failure leaves
        it unset so the next reconcile pass retries."""
        if sandbox.bridge_setup_fingerprint == BRIDGE_SETUP_FINGERPRINT:
            return
        try:
            res = await self._provider.exec_oneshot(
                _handle_of(sandbox),
                ["bash", "-lc", _BRIDGE_SETUP_REST],
                env={"DEBIAN_FRONTEND": "noninteractive"},
                cwd="/",
                timeout_s=BRIDGE_SETUP_TIMEOUT_S,
            )
        except SpritesError as exc:
            _logger.warning(
                "reconcile.bridge_setup_error",
                sandbox_id=str(sandbox.id),
                error=str(exc)[:200],
            )
            await _set_reconcile_error(sandbox, f"bridge setup: {str(exc)[:200]}")
            return
        if res.exit_code != 0:
            _logger.warning(
                "reconcile.bridge_setup_failed",
                sandbox_id=str(sandbox.id),
                exit_code=res.exit_code,
                stderr=res.stderr[-1000:],
                stdout=res.stdout[-500:],
            )
            await _set_reconcile_error(
                sandbox,
                f"bridge setup exit {res.exit_code}: {res.stderr.strip()[-200:]}",
            )
            return
        sandbox.bridge_setup_fingerprint = BRIDGE_SETUP_FINGERPRINT
        if sandbox.id is not None:
            await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
                {"$set": {"bridge_setup_fingerprint": BRIDGE_SETUP_FINGERPRINT}}
            )
        _logger.info(
            "reconcile.bridge_setup_done",
            sandbox_id=str(sandbox.id),
            fingerprint=BRIDGE_SETUP_FINGERPRINT,
        )

    async def _ensure_bridge_running(self, sandbox: Sandbox) -> None:
        """Slice 8 Phase 8c: launch (or relaunch) the bridge daemon
        inside the sprite. Idempotent: kills any existing
        `bridge.main` process, mints a fresh `BRIDGE_TOKEN`, persists
        its sha256 on `Sandbox.bridge_token_hash`, and starts a new
        `python -m bridge.main` via `nohup`. Token rotation on every
        relaunch keeps the auth surface tight without needing to
        recover the plaintext (we only ever stored the hash).

        Skipped when:
          - `bridge_config` isn't wired (tests / dev pre-bridge)
          - the wheel hasn't been installed yet (nothing to launch)
          - `ORCHESTRATOR_WS_URL` is empty (single-laptop dev — no
            orchestrator to dial)

        Service-proxy mode short-circuit: when a `bridge_session_fleet`
        is wired, delegate to its `ensure_started`. The legacy nohup
        path below stays intact for dial_back mode.
        """
        if self._bridge_session_fleet is not None:
            # service_proxy: PUT + start the Sprites Service.
            try:
                await self._bridge_session_fleet.ensure_started(sandbox)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "reconcile.bridge_service_ensure_failed",
                    sandbox_id=str(sandbox.id),
                    error=str(exc)[:200],
                )
            return

        if self._bridge_config is None:
            return
        if sandbox.bridge_wheel_sha is None:
            return
        env_template = self._bridge_config.env_for(
            sandbox_id=str(sandbox.id) if sandbox.id is not None else "",
            bridge_token="dummy",  # used only to detect "no orch" via ws_url
        )
        if not env_template.get("ORCHESTRATOR_WS_URL"):
            # Dev path — nothing to dial.
            return

        from orchestrator.services.sandbox_manager import (
            _hash_bridge_token,
            mint_bridge_token,
        )

        bridge_token = mint_bridge_token()
        token_hash = _hash_bridge_token(bridge_token)
        env = self._bridge_config.env_for(
            sandbox_id=str(sandbox.id) if sandbox.id is not None else "",
            bridge_token=bridge_token,
        )
        # Persist the hash BEFORE launching: the bridge will dial home
        # immediately and the WSS handshake validates against this hash.
        # If the persist fails we don't want a bridge alive with a token
        # the orchestrator can't validate.
        if sandbox.id is not None:
            await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
                {"$set": {"bridge_token_hash": token_hash}}
            )
            sandbox.bridge_token_hash = token_hash

        await _set_activity(sandbox, "launching_bridge", None)
        # Two non-obvious gotchas this script handles:
        #
        # 1. Sprites kills the exec session's pgroup on `exec_oneshot`
        #    return — `nohup` alone isn't enough. `setsid` puts the
        #    bridge in its OWN session/pgroup; `< /dev/null` cuts
        #    stdin so SIGHUP can't propagate that way.
        #
        # 2. We CANNOT use `pkill -f 'python -m bridge.main'` to find
        #    the previous bridge — that pattern also matches the bash
        #    process running this script (the script body contains
        #    that string literal as `argv[2]`), so pkill SIGTERMs
        #    itself and the script exits 143. PID-file path is the
        #    correct primitive: write `$BRIDGE_PID` after launch,
        #    read + kill it on next launch.
        #
        # 3. 0.5s liveness sanity check — if the bridge crashed at
        #    startup (bad env, missing module), surface its log here
        #    instead of letting `bridge_status` report
        #    `is_running=false` later with no diagnostics.
        launch_script = """set -euo pipefail
SPRITE_USER=$(id -un)
sudo -n install -d -m 0755 -o "$SPRITE_USER" -g "$SPRITE_USER" /var/log/octo
PIDFILE=/opt/bridge/bridge.pid
if [ -f "$PIDFILE" ]; then
    OLD=$(cat "$PIDFILE" 2>/dev/null || true)
    if [ -n "${OLD:-}" ] && kill -0 "$OLD" 2>/dev/null; then
        kill "$OLD" 2>/dev/null || true
        for _ in 1 2 3 4 5; do
            kill -0 "$OLD" 2>/dev/null || break
            sleep 0.2
        done
        kill -9 "$OLD" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
fi
setsid nohup /opt/bridge/.venv/bin/python -m bridge.main \\
    > /var/log/octo/bridge.log 2>&1 < /dev/null &
BRIDGE_PID=$!
disown
echo "$BRIDGE_PID" > "$PIDFILE"
sleep 0.5
if kill -0 "$BRIDGE_PID" 2>/dev/null; then
    echo "bridge launched: pid=$BRIDGE_PID"
else
    echo "bridge exited within 0.5s — log follows:" >&2
    tail -n 80 /var/log/octo/bridge.log >&2 || true
    exit 1
fi
"""
        try:
            res = await self._provider.exec_oneshot(
                _handle_of(sandbox),
                ["bash", "-lc", launch_script],
                env=env,
                cwd="/",
                timeout_s=30,
            )
        except Exception as exc:  # noqa: BLE001
            # Sprites SDK rc37 has a `TimeoutError(**kwargs)` bug that
            # raises TypeError on timeout (slice-7 followup; same
            # workaround as sandbox_git.py). Catch broadly so the
            # error doesn't escape into the route handler — the
            # routes layer assumes this returns cleanly on failure.
            _logger.warning(
                "reconcile.bridge_launch_error",
                sandbox_id=str(sandbox.id),
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
            )
            await _set_reconcile_error(
                sandbox,
                f"bridge launch ({type(exc).__name__}): {str(exc)[:200]}",
            )
            return
        if res.exit_code != 0:
            _logger.warning(
                "reconcile.bridge_launch_failed",
                sandbox_id=str(sandbox.id),
                exit_code=res.exit_code,
                stderr=res.stderr[-500:],
            )
            await _set_reconcile_error(
                sandbox,
                f"bridge launch exit {res.exit_code}: "
                f"{res.stderr.strip()[-200:]}",
            )
            return
        _logger.info(
            "reconcile.bridge_launched",
            sandbox_id=str(sandbox.id),
            stdout=res.stdout.strip(),
        )

    async def _install_bridge_wheel(self, sandbox: Sandbox) -> None:
        """Slice 8 Phase 0b: build the bridge wheel bundle locally,
        upload it to `/opt/bridge/wheels/`, and `uv pip install` it
        into `/opt/bridge/.venv`. Idempotent on `Sandbox.bridge_wheel_sha`
        — when the locally built bundle's combined sha matches what's
        already installed, this is a fast no-op.

        Best-effort: failures set `last_reconcile_error` but don't
        derail the rest of the pass; next pass retries. The bridge
        process itself isn't launched here — that's a later phase.
        """
        try:
            # `force=True` skips the in-memory bundle cache. The
            # orchestrator may not have reloaded uvicorn after a bridge-
            # source edit (uvicorn watches `apps/orchestrator/`, not
            # `apps/bridge/`), so a cached bundle could be stale even
            # though `fs_write` + `uv pip install --reinstall-package`
            # would otherwise propagate the new code. Forcing here
            # guarantees the latest source on every install attempt.
            bundle = await asyncio.to_thread(build_bridge_wheel_bundle, force=True)
        except Exception as exc:  # noqa: BLE001 — surface any build error
            _logger.warning(
                "reconcile.bridge_wheel_build_failed",
                sandbox_id=str(sandbox.id),
                error=str(exc)[:200],
            )
            await _set_reconcile_error(
                sandbox, f"bridge wheel build: {str(exc)[:200]}"
            )
            return
        if sandbox.bridge_wheel_sha == bundle.combined_sha:
            return
        await _set_activity(
            sandbox, "installing_bridge_wheel", bundle.combined_sha[:12]
        )
        handle = _handle_of(sandbox)
        # 1. Upload all wheels under /opt/bridge/wheels/.
        for wheel in bundle.wheels:
            try:
                await self._provider.fs_write(
                    handle,
                    f"/opt/bridge/wheels/{wheel.filename}",
                    wheel.content,
                    mkdir=True,
                )
            except SpritesError as exc:
                _logger.warning(
                    "reconcile.bridge_wheel_upload_failed",
                    sandbox_id=str(sandbox.id),
                    filename=wheel.filename,
                    error=str(exc)[:200],
                )
                await _set_reconcile_error(
                    sandbox, f"bridge wheel upload: {str(exc)[:200]}"
                )
                return
        # 2. Install. `--reinstall-package` for each workspace package
        # forces reinstall on those (their version strings don't bump
        # per code change), while leaving PyPI deps (claude-agent-sdk,
        # websockets, ...) cached when their pins haven't changed.
        # `--find-links` surfaces the workspace wheels we just uploaded;
        # PyPI deps still resolve from PyPI.
        workspace_pkgs = [
            "bridge",
            "shared-models",
            "agent-config",
            "repo-introspection",
            "github-integration",
        ]
        reinstall_flags = " ".join(
            f"--reinstall-package {p}" for p in workspace_pkgs
        )
        cmd = (
            f"/usr/local/bin/uv pip install "
            f"--python /opt/bridge/.venv/bin/python "
            f"--find-links /opt/bridge/wheels "
            f"{reinstall_flags} "
            f"/opt/bridge/wheels/{bundle.bridge_wheel_filename}"
        )
        try:
            res = await self._provider.exec_oneshot(
                handle,
                ["bash", "-lc", cmd],
                env={},
                cwd="/",
                timeout_s=BRIDGE_SETUP_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001
            # Sprites SDK rc37 `TimeoutError(**kwargs)` bug — see
            # `_ensure_bridge_running`'s broad-catch comment for
            # context. Catch broadly so the route handler sees a
            # clean failure return instead of a 500.
            _logger.warning(
                "reconcile.bridge_wheel_install_error",
                sandbox_id=str(sandbox.id),
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
            )
            await _set_reconcile_error(
                sandbox,
                f"bridge wheel install ({type(exc).__name__}): {str(exc)[:200]}",
            )
            return
        if res.exit_code != 0:
            _logger.warning(
                "reconcile.bridge_wheel_install_failed",
                sandbox_id=str(sandbox.id),
                exit_code=res.exit_code,
                stderr=res.stderr[-1000:],
            )
            await _set_reconcile_error(
                sandbox,
                f"bridge wheel install exit {res.exit_code}: "
                f"{res.stderr.strip()[-200:]}",
            )
            return
        sandbox.bridge_wheel_sha = bundle.combined_sha
        if sandbox.id is not None:
            await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
                {"$set": {"bridge_wheel_sha": bundle.combined_sha}}
            )
        _logger.info(
            "reconcile.bridge_wheel_installed",
            sandbox_id=str(sandbox.id),
            combined_sha=bundle.combined_sha[:12],
            wheel_count=len(bundle.wheels),
        )
        # Service-proxy: Sprites supervises the bridge daemon, so a new
        # wheel doesn't reach the running process until we restart the
        # service. Without this, the bridge keeps running stale code
        # even after we successfully reinstall the wheel. The fleet
        # tears down its cached BridgeSession + restart the service —
        # next `ensure_started` rebuilds the connection.
        if self._bridge_session_fleet is not None:
            try:
                await self._bridge_session_fleet.restart(sandbox)  # type: ignore[attr-defined]
                _logger.info(
                    "reconcile.bridge_service_restarted_after_wheel",
                    sandbox_id=str(sandbox.id),
                )
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "reconcile.bridge_service_restart_failed",
                    sandbox_id=str(sandbox.id),
                    error=str(exc)[:200],
                )

    async def _ensure_git_setup(self, sandbox: Sandbox, user: User) -> None:
        """One-time-per-token git setup inside the sandbox.

        Writes:
        - `~/.gitconfig`: identity (`user.name`, `user.email`) + sets
          `credential.helper=store` for github.com so subsequent ops
          read auth from `~/.git-credentials`.
        - `~/.git-credentials`: a single line
          `https://x-access-token:<token>@github.com` so any
          `git clone https://github.com/...` (or push, fetch, pull) just
          works without per-command auth flags.

        After this runs once, the sandbox is a properly-configured git
        workstation for the user — same commands work for the agent and
        any human shell session.

        The OAuth token *does* land on disk inside the sandbox at
        `~/.git-credentials`. That's fine: the sandbox is per-user and
        isolated, and the token is already in our control plane (Mongo).
        Sandbox destroy or reset wipes the file with the rest of the FS.

        Idempotent — skipped when the configured token fingerprint
        already matches the user's current token.
        """
        token = user.github_access_token or ""
        if not token:
            return  # caller already short-circuits clones with no token
        # Bump this version any time the script body below changes shape so
        # already-configured sandboxes get rewritten on next reconcile.
        # v2 added `[safe] directory = *` to fix "dubious ownership" errors
        # for repos cloned via `sudo -n`.
        config_version = "v2"
        fp = hashlib.sha256(f"{config_version}:{token}".encode()).hexdigest()
        if sandbox.git_configured_token_fp == fp:
            return  # already configured for this exact token + version

        name = user.github_username or "octo-canvas user"
        email = user.email or f"{user.github_username}@users.noreply.github.com"
        # Write to fixed paths under /etc/octo-canvas/. `sudo -n` because
        # /etc/ is root-owned and the sprite exec runs unprivileged. The
        # `GIT_CONFIG_GLOBAL` env var (set on every later git command via
        # `GIT_ENV`) tells git to read our config file regardless of $HOME,
        # so clones from any user/HOME find the same credentials.
        cred_line = f"https://x-access-token:{token}@github.com"
        # Two configs:
        # - `/etc/octo-canvas/gitconfig` (orchestrator-only via
        #   `GIT_CONFIG_GLOBAL`): identity + credentials. Only the
        #   orchestrator's exec_oneshot calls see this — keeps the OAuth
        #   token off the user's HOME.
        # - `/etc/gitconfig` (system-level, read by EVERY git invocation
        #   regardless of HOME or env): `safe.directory=*`. This is what
        #   the user's interactive terminal AND the slice-8 agent need to
        #   work on repos cloned by `sudo -n`. Without it, every git
        #   command fails with "fatal: detected dubious ownership".
        script = (
            "set -eu\n"
            'sudo -n mkdir -p "$(dirname "$GIT_CONFIG")"\n'
            'sudo -n tee "$GIT_CRED_FILE" > /dev/null <<EOF\n'
            "$GIT_CRED_LINE\n"
            "EOF\n"
            'sudo -n chmod 644 "$GIT_CRED_FILE"\n'
            'sudo -n tee "$GIT_CONFIG" > /dev/null <<EOF\n'
            "[user]\n"
            "\tname = $GIT_USER_NAME\n"
            "\temail = $GIT_USER_EMAIL\n"
            "[credential]\n"
            f"\thelper = store --file={GIT_CRED_PATH}\n"
            "[init]\n"
            "\tdefaultBranch = main\n"
            "EOF\n"
            'sudo -n chmod 644 "$GIT_CONFIG"\n'
            # System-wide gitconfig — every shell, every user, every
            # git tool inside the sandbox sees it.
            "sudo -n tee /etc/gitconfig > /dev/null <<EOF\n"
            "[safe]\n"
            "\tdirectory = *\n"
            "EOF\n"
            "sudo -n chmod 644 /etc/gitconfig\n"
        )
        try:
            res = await self._provider.exec_oneshot(
                _handle_of(sandbox),
                ["sh", "-c", script],
                env={
                    "GIT_USER_NAME": name,
                    "GIT_USER_EMAIL": email,
                    "GIT_CRED_LINE": cred_line,
                    "GIT_CONFIG": GIT_CONFIG_PATH,
                    "GIT_CRED_FILE": GIT_CRED_PATH,
                },
                cwd="/",
                timeout_s=30,
            )
        except SpritesError as exc:
            _logger.warning(
                "reconcile.git_setup_failed",
                sandbox_id=str(sandbox.id),
                error=_redact_token(str(exc), token)[:200],
            )
            return
        if res.exit_code != 0:
            _logger.warning(
                "reconcile.git_setup_nonzero",
                sandbox_id=str(sandbox.id),
                exit_code=res.exit_code,
                stderr=_redact_token(res.stderr, token)[-1000:],
                stdout=_redact_token(res.stdout, token)[-500:],
            )
            return
        sandbox.git_configured_token_fp = fp
        if sandbox.id is not None:
            await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
                {"$set": {"git_configured_token_fp": fp}}
            )
        _logger.info(
            "reconcile.git_setup_done",
            sandbox_id=str(sandbox.id),
            user=user.github_username,
        )

    async def _install_runtimes(
        self,
        sandbox: Sandbox,
        targets: list[tuple[str, str]],
    ) -> tuple[list[tuple[str, str]], dict[tuple[str, str], str]]:
        """Run `nvm install <ver>` / `pyenv install <ver>` / etc. once
        per target. Returns `(installed, errors)` — `errors` keys are the
        targets that failed (mapped to a short reason). Slice 7 #3.
        """
        installed: list[tuple[str, str]] = []
        errors: dict[tuple[str, str], str] = {}
        total = len(targets)
        for idx, (manager, version) in enumerate(targets, start=1):
            # Per-runtime activity update so the dashboard banner shows
            # which one is in flight (cpython compiles for 5-10 min;
            # without this the user sees "node 24, python 3.13.5" sit
            # there for the whole window even after Node finished).
            await _set_activity(
                sandbox,
                "installing_runtimes",
                f"{manager} {version} ({idx}/{total})",
            )
            template = _RUNTIME_INSTALL_CMDS[manager]
            argv = [part.format(version=version) for part in template]
            try:
                res = await self._provider.exec_oneshot(
                    _handle_of(sandbox),
                    argv,
                    env={},
                    cwd="/",
                    timeout_s=RUNTIME_INSTALL_TIMEOUT_S,
                )
            except SpritesError as exc:
                errors[(manager, version)] = str(exc)[:200]
                _logger.warning(
                    "reconcile.runtime_install_error",
                    sandbox_id=str(sandbox.id),
                    manager=manager,
                    version=version,
                    error=str(exc)[:200],
                )
                await _set_reconcile_error(
                    sandbox, f"{manager} {version}: {str(exc)[:200]}"
                )
                continue
            if res.exit_code == 0:
                installed.append((manager, version))
                _logger.info(
                    "reconcile.runtime_installed",
                    sandbox_id=str(sandbox.id),
                    manager=manager,
                    version=version,
                )
            else:
                errors[(manager, version)] = (
                    f"exit_code={res.exit_code}: {res.stderr[-200:].strip()}"
                )
                _logger.warning(
                    "reconcile.runtime_install_failed",
                    sandbox_id=str(sandbox.id),
                    manager=manager,
                    version=version,
                    exit_code=res.exit_code,
                    stderr=res.stderr[-500:],
                )
                await _set_reconcile_error(
                    sandbox,
                    f"{manager} {version} exit {res.exit_code}: {res.stderr.strip()[-200:]}",
                )
        return installed, errors

    async def _clone_one(self, sandbox: Sandbox, repo: Repo, token: str | None) -> bool:
        if not token:
            await _mark_clone_failed(repo, "github_reauth_required")
            return False

        repo.clone_status = "cloning"
        repo.clone_error = None
        await repo.save()

        target = f"{WORK_ROOT}/{repo.full_name}"
        url = f"https://github.com/{repo.full_name}.git"
        owner = repo.full_name.split("/", 1)[0]
        # Single exec for both `mkdir <owner>` and `git clone`. Each
        # `exec_oneshot` opens its own WebSocket; Sprites' Exec
        # endpoint flakes the handshake on rapid back-to-back connects,
        # so doing both steps in one shell halves the per-repo failure
        # surface. Plain HTTPS URL — auth comes from the credential
        # helper that `_ensure_git_setup` already configured.
        clone_script = (
            f'mkdir -p "{WORK_ROOT}/{owner}" && '
            f"git clone --depth 1 --branch "
            f'"{repo.default_branch}" "{url}" "{target}"'
        )
        argv = ["sh", "-c", clone_script]
        try:
            res = await self._provider.exec_oneshot(
                _handle_of(sandbox),
                argv,
                # HOME must match what `_ensure_git_setup` wrote credentials
                # to — otherwise git looks elsewhere and falls back to
                # terminal prompt → "could not read Username".
                env=GIT_ENV,
                cwd="/",
                timeout_s=CLONE_TIMEOUT_S,
            )
        except SpritesError as exc:
            await _mark_clone_failed(repo, _redact_token(str(exc), token or "")[:200])
            return False

        if res.exit_code != 0:
            full = _redact_token(res.stderr, token or "")
            full_lower = full[-500:].lower()
            if "401" in full_lower or "authentication failed" in full_lower:
                kind_prefix = "github_reauth_required"
            elif "couldn't find remote ref" in full_lower or "remote branch" in full_lower:
                kind_prefix = "branch_not_found"
            else:
                kind_prefix = f"clone_failed (exit {res.exit_code})"
            # Save the full stderr (truncated to 1500 chars to fit in
            # Mongo comfortably) so the user can see what actually broke.
            detail = full[-1500:].strip()
            reason = f"{kind_prefix}: {detail}" if detail else kind_prefix
            await _mark_clone_failed(repo, reason)
            return False

        repo.clone_status = "ready"
        repo.clone_path = target
        repo.clone_error = None
        await repo.save()
        return True


async def _set_activity(sandbox: Sandbox, activity: str | None, detail: str | None) -> None:
    """Update the sandbox's progress banner using an atomic per-field
    `$set`, NOT `sandbox.save()`. The reconciler may have loaded the
    sandbox doc minutes ago; a full `save()` here would overwrite a
    destroyed/failed/reset status set by a concurrent route handler.
    `$set` only touches the activity-related fields, leaving everything
    else intact.

    Slice 7: also stamps `activity_started_at` (UI shows elapsed time)
    and clears `last_reconcile_error` whenever the activity *name*
    changes (so the user sees the freshest error per stage rather than
    a stale one from earlier in the pass).

    Best-effort — a failed update is logged but doesn't abort
    reconciliation."""
    if sandbox.id is None:
        return
    # Refresh elapsed-time on EITHER a name change (installing_packages
    # → installing_runtimes) OR a detail change within the same name
    # (`node 24 (1/2)` → `python 3.13.5 (2/2)`). Without the detail
    # check the timer would show "time since the FIRST runtime" while
    # later runtimes ran. Clear `last_reconcile_error` only on a name
    # change so the user sees the latest error per stage, not per
    # detail-tick.
    name_changed = sandbox.activity != activity
    detail_changed = sandbox.activity_detail != detail
    sandbox.activity = activity  # keep in-memory copy in sync
    sandbox.activity_detail = detail
    update: dict[str, object] = {"activity": activity, "activity_detail": detail}
    if name_changed or detail_changed:
        # Stamp start time on transition into a phase OR a sub-step;
        # clear when activity goes None (end of pass).
        new_started_at: datetime | None = _now_utc() if activity is not None else None
        sandbox.activity_started_at = new_started_at
        update["activity_started_at"] = new_started_at
    if name_changed:
        # Phase change → drop any stale error so the banner reflects
        # the current stage. The stage's own failure path will set
        # `last_reconcile_error` again if it trips.
        sandbox.last_reconcile_error = None
        update["last_reconcile_error"] = None
    try:
        await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
            {"$set": update}
        )
    except Exception as exc:
        _logger.warning(
            "reconcile.set_activity_failed",
            sandbox_id=str(sandbox.id),
            activity=activity,
            error=str(exc),
        )


def _now_utc() -> datetime:
    return datetime.now(UTC)


async def _set_reconcile_error(sandbox: Sandbox, error: str | None) -> None:
    """Persist `Sandbox.last_reconcile_error` atomically. Same `$set`
    discipline as `_set_activity` so we don't clobber concurrent route
    writes. Best-effort."""
    if sandbox.id is None:
        return
    truncated = error[:300] if error else None
    sandbox.last_reconcile_error = truncated
    try:
        await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
            {"$set": {"last_reconcile_error": truncated}}
        )
    except Exception as exc:
        _logger.warning(
            "reconcile.set_error_failed",
            sandbox_id=str(sandbox.id),
            error=str(exc),
        )


def _redact_token(text: str, token: str) -> str:
    """Strip the OAuth token from any string before persisting/logging."""
    if not token or token not in text:
        return text
    return text.replace(token, "<redacted>")


async def _mark_clone_failed(repo: Repo, reason: str) -> None:
    repo.clone_status = "failed"
    # Mongo string field — truncate at 4KB to keep doc sizes sane.
    repo.clone_error = reason[:4000]
    await repo.save()
    _logger.warning(
        "reconcile.clone_failed",
        repo_id=str(repo.id),
        full_name=repo.full_name,
        reason=reason[:300],  # log preview; full reason on the doc
    )


def _runtime_targets_for(repo: Repo) -> list[tuple[str, str]]:
    """Effective runtimes for a repo (overrides win over detected). Each
    entry is `(manager_key, version_string)`. Drops entries we can't
    install (no version pinned, or runtime name unsupported by v1)."""
    runtimes: list[tuple[str, str]] = []
    intr = repo.introspection_detected
    ovr = repo.introspection_overrides
    src = (
        ovr.runtimes
        if ovr is not None and ovr.runtimes is not None
        else (intr.runtimes if intr is not None else [])
    )
    for r in src:
        if r.version is None:
            continue
        if r.name not in _RUNTIME_INSTALL_CMDS:
            continue
        runtimes.append((r.name, r.version))
    return runtimes


def _merge_runtime_targets(repos: list[Repo]) -> list[tuple[str, str]]:
    """Deduped union of every alive repo's runtime install targets,
    sorted for stable ordering across passes."""
    seen: set[tuple[str, str]] = set()
    for repo in repos:
        for target in _runtime_targets_for(repo):
            seen.add(target)
    return sorted(seen)


def _merge_system_packages(repos: list[Repo]) -> list[str]:
    """Union of detected + overrides across every alive repo, deduped."""
    pkgs: set[str] = set()
    for repo in repos:
        if repo.clone_status == "failed":
            # A failing repo's introspection is still a hint, but skip it
            # if it was a transient detection error (e.g. tree-fetch failed).
            pass
        intr = repo.introspection_detected
        if intr is not None:
            pkgs.update(intr.system_packages)
        ovr = repo.introspection_overrides
        if ovr is not None and ovr.system_packages is not None:
            pkgs.update(ovr.system_packages)
    return sorted(pkgs)
