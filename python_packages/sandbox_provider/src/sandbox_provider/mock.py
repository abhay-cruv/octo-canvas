"""In-memory `SandboxProvider` for local dev + tests.

Models Sprites' semantics:
- `create` returns a sprite in `warm` state with a fake public URL.
- `wake` forces `cold` → `running`.
- Idle hibernation is not modeled (Sprites does it with a real timer; for
  tests, we expose `_force_cold(handle)` so tests can simulate the transition
  deterministically).
- `destroy` is idempotent.

Slice 5b additions:
- An in-memory FS modeled as `dict[sprite_name, set[full_name]]` of cloned
  repo paths under `/work/`, plus a parallel `_apt_installed` set for
  asserting `apt-get install` calls.
- `exec_oneshot` recognizes a few command shapes (`git clone`, `rm -rf`,
  `apt-get install`) — anything else returns `exit_code=0` with empty I/O.
- `snapshot`/`restore` deep-copy/swap the FS dict + apt set under a fresh
  checkpoint id.

State is process-local. Restarting the orchestrator wipes it — fine because
Mongo's `Sandbox` doc is the source of truth and `MockSandboxProvider` is
*never* used in prod (see `provider_factory.build_sandbox_provider`).
"""

import copy
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from sandbox_provider.interface import (
    CheckpointId,
    ExecResult,
    FsEntry,
    ProviderName,
    ProviderStatus,
    SandboxHandle,
    SandboxState,
    SpritesError,
)


@dataclass
class _SpriteRecord:
    name: str
    sandbox_id: str
    status: ProviderStatus
    public_url: str
    destroyed: bool = False
    # Slice 5b — modeled FS: { "/work/<full_name>": True }. Tracked as a set
    # of full_names since slice 5b never reads file bytes.
    cloned_repos: set[str] = field(default_factory=set)
    apt_installed: set[str] = field(default_factory=set)
    # checkpoint_id -> deep-copied snapshot of (cloned_repos, apt_installed).
    checkpoints: dict[str, tuple[set[str], set[str]]] = field(default_factory=dict)


_GIT_CLONE_RE = re.compile(
    r"^(?:https?://[^@]*@)?(?:https?://)?[^/]*github\.com/(?P<full_name>[^/]+/[^/]+?)(?:\.git)?/?$"
)


class MockSandboxProvider:
    name: ProviderName = "mock"

    def __init__(self) -> None:
        self._sprites: dict[str, _SpriteRecord] = {}

    async def create(self, *, sandbox_id: str, labels: list[str]) -> SandboxHandle:
        _ = labels
        sprite_name = f"octo-sbx-{sandbox_id}"
        if sprite_name in self._sprites and not self._sprites[sprite_name].destroyed:
            raise SpritesError(f"sprite {sprite_name!r} already exists", retriable=False)
        self._sprites[sprite_name] = _SpriteRecord(
            name=sprite_name,
            sandbox_id=sandbox_id,
            status="warm",
            public_url=f"https://{sprite_name}-mock.sprites.app",
        )
        # Fresh UUID per create call so Reset (destroy+create with the same
        # `sandbox_id`) rotates the id, matching real Sprites behaviour where
        # the UUID is server-assigned per-sprite.
        return SandboxHandle(
            provider="mock",
            payload={"name": sprite_name, "id": f"sprite-mock-{uuid.uuid4().hex[:12]}"},
        )

    async def status(self, handle: SandboxHandle) -> SandboxState:
        rec = self._require(handle)
        return SandboxState(status=rec.status, public_url=rec.public_url)

    async def destroy(self, handle: SandboxHandle) -> None:
        name = handle.payload.get("name", "")
        rec = self._sprites.get(name)
        if rec is None or rec.destroyed:
            return  # idempotent
        rec.destroyed = True

    async def wake(self, handle: SandboxHandle) -> SandboxState:
        rec = self._require(handle)
        # Whatever state we were in, an exec session forces running.
        rec.status = "running"
        return SandboxState(status="running", public_url=rec.public_url)

    async def pause(self, handle: SandboxHandle) -> SandboxState:
        # Mock has no exec sessions to kill; just transition to cold to model
        # Sprites' idle-after-pause behaviour deterministically.
        rec = self._require(handle)
        rec.status = "cold"
        return SandboxState(status="cold", public_url=rec.public_url)

    # ── Slice 5b additions ───────────────────────────────────────────────

    async def exec_oneshot(
        self,
        handle: SandboxHandle,
        argv: list[str],
        *,
        env: Mapping[str, str],
        cwd: str,
        timeout_s: int = 300,
    ) -> ExecResult:
        _ = env, cwd, timeout_s  # mock doesn't care about these
        rec = self._require(handle)
        # Recognized shapes:
        #   ["git", "clone", "<flags...>", "<url>", "<dest>"]
        #   ["rm", "-rf", "/work/<full_name>"]
        #   ["apt-get", "install", "-y", *pkgs]
        # Anything else returns success with empty I/O — tests can extend by
        # subclassing or by reading `rec.cloned_repos` / `rec.apt_installed`
        # to assert intent without caring about the actual command shape.
        start = time.monotonic()
        # Recognize both bare `git clone …` and `sh -c "… git clone …"`
        # shapes — the reconciler combines `mkdir + git clone` into a
        # single `sh -c` script for fewer Sprites Exec round-trips.
        sh_script = argv[2] if argv[:2] == ["sh", "-c"] and len(argv) > 2 else None
        is_git_clone = (argv and argv[0] == "git" and "clone" in argv[1:]) or (
            sh_script is not None and "git clone" in sh_script
        )
        if is_git_clone:
            if sh_script is not None:
                # Pull last two positional tokens — url + target.
                tokens = sh_script.replace('"', "").split()
                url, target_path = tokens[-2], tokens[-1]
            else:
                url = argv[-2]
                target_path = argv[-1]
            match = _GIT_CLONE_RE.match(url)
            if match is None:
                return ExecResult(
                    exit_code=128,
                    stdout="",
                    stderr=f"mock: not a github clone url: {url}",
                    duration_s=time.monotonic() - start,
                )
            full_name = match.group("full_name")
            rec.cloned_repos.add(full_name)
            return ExecResult(
                exit_code=0,
                stdout=f"Cloning into '{target_path}'...",
                stderr="",
                duration_s=time.monotonic() - start,
            )
        if argv[:2] == ["rm", "-rf"] and len(argv) == 3:
            target = argv[2]
            prefix = "/work/"
            if target.startswith(prefix):
                full_name = target.removeprefix(prefix).rstrip("/")
                rec.cloned_repos.discard(full_name)
            return ExecResult(exit_code=0, stdout="", stderr="", duration_s=0.0)
        if argv[:3] == ["apt-get", "install", "-y"]:
            for pkg in argv[3:]:
                rec.apt_installed.add(pkg)
            return ExecResult(
                exit_code=0,
                stdout=f"Installed {len(argv) - 3} package(s)",
                stderr="",
                duration_s=0.0,
            )
        return ExecResult(exit_code=0, stdout="", stderr="", duration_s=0.0)

    async def fs_list(self, handle: SandboxHandle, path: str) -> list[FsEntry]:
        rec = self._require(handle)
        # Mock only models /work/<full_name> directories; anything else
        # returns empty. Sufficient for reconciliation's diff path.
        if path != "/work":
            return []
        # Each `<full_name>` becomes one or more entries — owner dir + repo
        # subdir. We surface just the top-level "owner/repo" form so the
        # reconciler's diff can match `Repo.full_name` directly.
        return [
            FsEntry(name=full_name, kind="dir", size=0) for full_name in sorted(rec.cloned_repos)
        ]

    async def fs_delete(self, handle: SandboxHandle, path: str, *, recursive: bool = False) -> None:
        _ = recursive
        rec = self._require(handle)
        prefix = "/work/"
        if path.startswith(prefix):
            full_name = path.removeprefix(prefix).rstrip("/")
            rec.cloned_repos.discard(full_name)

    async def snapshot(self, handle: SandboxHandle, *, comment: str) -> CheckpointId:
        _ = comment
        rec = self._require(handle)
        ckpt = f"ckpt-mock-{uuid.uuid4().hex[:12]}"
        rec.checkpoints[ckpt] = (
            copy.deepcopy(rec.cloned_repos),
            copy.deepcopy(rec.apt_installed),
        )
        return CheckpointId(ckpt)

    async def restore(self, handle: SandboxHandle, checkpoint_id: CheckpointId) -> SandboxState:
        rec = self._require(handle)
        snap = rec.checkpoints.get(str(checkpoint_id))
        if snap is None:
            raise SpritesError(f"checkpoint {checkpoint_id!r} not found", retriable=False)
        cloned, apt = snap
        rec.cloned_repos = copy.deepcopy(cloned)
        rec.apt_installed = copy.deepcopy(apt)
        rec.status = "warm"
        return SandboxState(status="warm", public_url=rec.public_url)

    # ── Test hooks (not part of the Protocol) ────────────────────────────

    def _force_cold(self, handle: SandboxHandle) -> None:
        """Simulate Sprites' idle-hibernation transition for tests."""
        rec = self._require(handle)
        rec.status = "cold"

    def _require(self, handle: SandboxHandle) -> _SpriteRecord:
        if handle.provider != "mock":
            raise SpritesError(
                f"MockSandboxProvider received handle for {handle.provider!r}",
                retriable=False,
            )
        name = handle.payload.get("name", "")
        rec = self._sprites.get(name)
        if rec is None or rec.destroyed:
            raise SpritesError(f"sprite {name!r} not found", retriable=False)
        return rec
