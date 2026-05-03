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

import asyncio
import copy
import re
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Literal

from sandbox_provider.interface import (
    CheckpointId,
    ExecResult,
    FsEntry,
    FsEvent,
    ProviderName,
    ProviderStatus,
    ProxyDialInfo,
    PtyDialInfo,
    SandboxHandle,
    SandboxState,
    ServiceLogLine,
    ServiceStatus,
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
    # Slice 7 — modeled per-(manager,version) language runtime installs.
    # The mock records what the reconciler asked nvm/pyenv/rbenv to do
    # so tests can assert without a real shell. Tests can also seed
    # `runtime_install_failures` with `(manager, version) → exit_code`
    # to drive the failure path.
    runtimes_installed: set[tuple[str, str]] = field(default_factory=set)
    runtime_install_failures: dict[tuple[str, str], int] = field(default_factory=dict)
    # Slice 6 — modeled per-byte FS: { absolute_path: bytes }. Directories
    # are implicit (any prefix that has a child). Mode is tracked separately
    # since most tests don't care, but we keep it for fs_write round-trips.
    files: dict[str, bytes] = field(default_factory=dict)
    file_modes: dict[str, int] = field(default_factory=dict)
    # Slice 6 — canned git outputs per repo path. Tests fill these via
    # `set_git_status_output` / `set_git_show_output` test hooks. The
    # mock's `exec_oneshot` recognizes the matching argv shapes and
    # returns these as stdout.
    git_status_outputs: dict[str, str] = field(default_factory=dict)
    git_show_outputs: dict[tuple[str, str], str] = field(default_factory=dict)
    git_show_missing: set[tuple[str, str]] = field(default_factory=set)
    # Active fs_watch_subscribe queues. The mock fans events to every
    # queue whose `path_prefix` covers the event's path. Tests push events
    # via `_emit_fs_event`.
    watch_queues: list[tuple[str, bool, asyncio.Queue[FsEvent | None]]] = field(
        default_factory=list
    )
    # checkpoint_id -> deep-copied snapshot of (cloned_repos, apt_installed, files, file_modes).
    checkpoints: dict[str, tuple[set[str], set[str], dict[str, bytes], dict[str, int]]] = field(
        default_factory=dict
    )
    # Slice 8 service_proxy: declared services keyed by name.
    # Value tuple: (cmd, args, env, cwd, http_port, status, pid, started_at, error).
    services: dict[
        str,
        tuple[
            str,
            list[str],
            dict[str, str],
            str,
            int | None,
            str,
            int | None,
            str | None,
            str | None,
        ],
    ] = field(default_factory=dict)
    # Pending log lines per service. Tests can push lines with
    # `push_service_log` to drive the live-log streaming code path.
    service_log_queues: dict[str, list[asyncio.Queue[ServiceLogLine | None]]] = field(
        default_factory=dict
    )


def _now_ms() -> int:
    return int(time.time() * 1000)


def _list_dir(files: dict[str, bytes], path: str) -> list[FsEntry]:
    """Synthesize an `fs_list` response from the in-memory `files` dict.
    Anything whose absolute path starts with `path/` becomes either a
    file entry (if exactly one segment deeper) or a dir entry (if deeper)."""
    base = path.rstrip("/") + "/"
    direct_files: dict[str, int] = {}
    direct_dirs: set[str] = set()
    for full, content in files.items():
        if not full.startswith(base):
            continue
        rest = full.removeprefix(base)
        if not rest:
            continue
        head, _, tail = rest.partition("/")
        if tail:
            direct_dirs.add(head)
        else:
            direct_files[head] = len(content)
    out: list[FsEntry] = [FsEntry(name=name, kind="dir", size=0) for name in sorted(direct_dirs)]
    out.extend(
        FsEntry(name=name, kind="file", size=size) for name, size in sorted(direct_files.items())
    )
    return out


def _path_matches(prefix: str, recursive: bool, path: str) -> bool:
    if path == prefix:
        return True
    if not recursive:
        # Only direct children fire when recursive=False.
        return path.startswith(prefix.rstrip("/") + "/") and "/" not in path[len(prefix) + 1 :]
    return path.startswith(prefix.rstrip("/") + "/")


_GIT_CLONE_RE = re.compile(
    r"^(?:https?://[^@]*@)?(?:https?://)?[^/]*github\.com/(?P<full_name>[^/]+/[^/]+?)(?:\.git)?/?$"
)


class MockSandboxProvider:
    name: ProviderName = "mock"

    def __init__(self) -> None:
        self._sprites: dict[str, _SpriteRecord] = {}
        # Test override — point this at an in-process fake WS server URL
        # so the orchestrator's PTY broker has somewhere real to dial.
        self._pty_url: str | None = None

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
        # Slice 7: recognise `bash -lc "<manager> install [-s] <version> [|| (...)]"`
        # so reconciler runtime-install asserts hit a deterministic path.
        # Recorded by *runtime* name (node/python/ruby) — not manager name —
        # so tests can assert against the introspection vocabulary.
        _MANAGER_TO_RUNTIME = {"nvm": "node", "pyenv": "python", "rbenv": "ruby"}
        if argv[:2] == ["bash", "-lc"] and len(argv) >= 3:
            tokens = argv[2].split()
            if len(tokens) >= 3 and tokens[1] == "install":
                manager = tokens[0]
                # Real command shape: `<manager> install [-s] <version> [|| (...retry...)]`.
                # Skip the optional `-s` flag so the mock recognises both
                # the v1 raw form and the slice-7 retry-with-update form.
                version_idx = 3 if len(tokens) >= 4 and tokens[2] == "-s" else 2
                version = tokens[version_idx]
                runtime = _MANAGER_TO_RUNTIME.get(manager)
                if runtime is not None:
                    key = (runtime, version)
                    if key in rec.runtime_install_failures:
                        return ExecResult(
                            exit_code=rec.runtime_install_failures[key],
                            stdout="",
                            stderr=f"mock: {manager} install {version} failed",
                            duration_s=time.monotonic() - start,
                        )
                    rec.runtimes_installed.add(key)
                    return ExecResult(
                        exit_code=0,
                        stdout=f"installed {runtime} {version}",
                        stderr="",
                        duration_s=time.monotonic() - start,
                    )
            # Slice 8: python runtime now uses `uv python install` instead
            # of pyenv. Extract the version from the leading `V="..."`
            # assignment so the (runtime, version) key still matches what
            # the reconciler asked for.
            script = argv[2]
            if "uv python install" in script:
                version: str | None = None
                for tok in tokens:
                    if tok.startswith('V="') and tok.endswith('";'):
                        version = tok[3:-2]
                        break
                if version is not None:
                    key = ("python", version)
                    if key in rec.runtime_install_failures:
                        return ExecResult(
                            exit_code=rec.runtime_install_failures[key],
                            stdout="",
                            stderr=f"mock: uv python install {version} failed",
                            duration_s=time.monotonic() - start,
                        )
                    rec.runtimes_installed.add(key)
                    return ExecResult(
                        exit_code=0,
                        stdout=f"installed python {version} via uv",
                        stderr="",
                        duration_s=time.monotonic() - start,
                    )
        if argv[:3] == ["apt-get", "install", "-y"]:
            for pkg in argv[3:]:
                rec.apt_installed.add(pkg)
            return ExecResult(
                exit_code=0,
                stdout=f"Installed {len(argv) - 3} package(s)",
                stderr="",
                duration_s=0.0,
            )
        # Strip leading `-c <key=value>` pairs so we can match git argv
        # shapes regardless of whether the orchestrator passed
        # `-c safe.directory=*` etc. Then expect the canonical
        # `git -C <repo> <subcommand> ...` form.
        i = 1
        while i < len(argv) - 1 and argv[i] == "-c":
            i += 2
        # `git [-c k=v ...] -C <repo_path> status --porcelain=v1 -b -z`
        if (
            argv[0] == "git"
            and i + 2 < len(argv)
            and argv[i] == "-C"
            and argv[i + 2] == "status"
        ):
            repo = argv[i + 1]
            stdout = rec.git_status_outputs.get(repo, "")
            return ExecResult(exit_code=0, stdout=stdout, stderr="", duration_s=0.0)
        # `git [-c k=v ...] -C <repo_path> show <ref>:<rel>`
        if (
            argv[0] == "git"
            and i + 3 < len(argv)
            and argv[i] == "-C"
            and argv[i + 2] == "show"
        ):
            repo = argv[i + 1]
            spec = argv[i + 3]
            if (repo, spec) in rec.git_show_missing:
                return ExecResult(
                    exit_code=128,
                    stdout="",
                    stderr=f"fatal: path '{spec}' does not exist",
                    duration_s=0.0,
                )
            content = rec.git_show_outputs.get((repo, spec), "")
            return ExecResult(exit_code=0, stdout=content, stderr="", duration_s=0.0)
        return ExecResult(exit_code=0, stdout="", stderr="", duration_s=0.0)

    async def fs_list(self, handle: SandboxHandle, path: str) -> list[FsEntry]:
        rec = self._require(handle)
        # Slice 5b: top-level /work listing comes from cloned_repos so the
        # reconciler's diff can match Repo.full_name directly.
        # Slice 6: any other path looks at the modeled `files` dict so the
        # IDE file tree has something to render in tests.
        if path == "/work":
            entries: list[FsEntry] = [
                FsEntry(name=full_name, kind="dir", size=0)
                for full_name in sorted(rec.cloned_repos)
            ]
            # Files written directly under /work via fs_write also surface.
            entries.extend(_list_dir(rec.files, "/work"))
            # De-dup names (a cloned repo and a manually-written file shouldn't
            # collide in fixtures, but be defensive).
            seen: set[str] = set()
            out: list[FsEntry] = []
            for entry in entries:
                if entry.name in seen:
                    continue
                seen.add(entry.name)
                out.append(entry)
            return out
        return _list_dir(rec.files, path)

    async def fs_delete(self, handle: SandboxHandle, path: str, *, recursive: bool = False) -> None:
        rec = self._require(handle)
        prefix = "/work/"
        # Repo-directory removal under /work — keep the slice 5b behaviour
        # (drops the entry from cloned_repos) for the reconciler's wipe path.
        if path.startswith(prefix) and path.count("/") == 3:
            full_name = path.removeprefix(prefix).rstrip("/")
            rec.cloned_repos.discard(full_name)
        # File-level delete from the modeled FS.
        if path in rec.files:
            del rec.files[path]
            rec.file_modes.pop(path, None)
            self._emit_fs_event(
                rec,
                FsEvent(path=path, kind="delete", is_dir=False, size=None, timestamp_ms=_now_ms()),
            )
        elif recursive:
            # Directory-recursive delete — drop every file beneath `path`.
            sep_path = path.rstrip("/") + "/"
            doomed = [p for p in rec.files if p.startswith(sep_path)]
            for p in doomed:
                del rec.files[p]
                rec.file_modes.pop(p, None)
                self._emit_fs_event(
                    rec,
                    FsEvent(path=p, kind="delete", is_dir=False, size=None, timestamp_ms=_now_ms()),
                )

    async def snapshot(self, handle: SandboxHandle, *, comment: str) -> CheckpointId:
        _ = comment
        rec = self._require(handle)
        ckpt = f"ckpt-mock-{uuid.uuid4().hex[:12]}"
        rec.checkpoints[ckpt] = (
            copy.deepcopy(rec.cloned_repos),
            copy.deepcopy(rec.apt_installed),
            copy.deepcopy(rec.files),
            copy.deepcopy(rec.file_modes),
        )
        return CheckpointId(ckpt)

    async def restore(self, handle: SandboxHandle, checkpoint_id: CheckpointId) -> SandboxState:
        rec = self._require(handle)
        snap = rec.checkpoints.get(str(checkpoint_id))
        if snap is None:
            raise SpritesError(f"checkpoint {checkpoint_id!r} not found", retriable=False)
        cloned, apt, files, modes = snap
        rec.cloned_repos = copy.deepcopy(cloned)
        rec.apt_installed = copy.deepcopy(apt)
        rec.files = copy.deepcopy(files)
        rec.file_modes = copy.deepcopy(modes)
        rec.status = "warm"
        return SandboxState(status="warm", public_url=rec.public_url)

    # ── Slice 6 additions ────────────────────────────────────────────────

    async def fs_read(self, handle: SandboxHandle, path: str) -> bytes:
        rec = self._require(handle)
        if path not in rec.files:
            raise SpritesError(f"path {path!r} not found", retriable=False)
        return rec.files[path]

    async def fs_write(
        self,
        handle: SandboxHandle,
        path: str,
        content: bytes,
        *,
        mode: int = 0o644,
        mkdir: bool = True,
    ) -> int:
        _ = mkdir  # mock has no real directory state — writes always succeed
        rec = self._require(handle)
        existed = path in rec.files
        rec.files[path] = bytes(content)
        rec.file_modes[path] = mode
        self._emit_fs_event(
            rec,
            FsEvent(
                path=path,
                kind="modify" if existed else "create",
                is_dir=False,
                size=len(content),
                timestamp_ms=_now_ms(),
            ),
        )
        return len(content)

    async def fs_rename(self, handle: SandboxHandle, src: str, dst: str) -> None:
        rec = self._require(handle)
        if src not in rec.files:
            raise SpritesError(f"path {src!r} not found", retriable=False)
        rec.files[dst] = rec.files.pop(src)
        if src in rec.file_modes:
            rec.file_modes[dst] = rec.file_modes.pop(src)
        self._emit_fs_event(
            rec,
            FsEvent(
                path=dst,
                kind="rename",
                is_dir=False,
                size=len(rec.files[dst]),
                timestamp_ms=_now_ms(),
            ),
        )

    async def fs_watch_subscribe(
        self,
        handle: SandboxHandle,
        path: str,
        *,
        recursive: bool = True,
    ) -> AsyncIterator[FsEvent]:
        rec = self._require(handle)
        queue: asyncio.Queue[FsEvent | None] = asyncio.Queue()
        entry = (path.rstrip("/") or "/", recursive, queue)
        rec.watch_queues.append(entry)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield event
        finally:
            try:
                rec.watch_queues.remove(entry)
            except ValueError:
                pass

    # ── Slice 8 service_proxy stubs ──────────────────────────────────────

    async def upsert_service(
        self,
        handle: SandboxHandle,
        *,
        name: str,
        cmd: str,
        args: list[str],
        env: dict[str, str],
        cwd: str = "/",
        http_port: int | None = None,
    ) -> None:
        rec = self._require(handle)
        prev = rec.services.get(name)
        prev_status = prev[5] if prev is not None else "stopped"
        prev_pid = prev[6] if prev is not None else None
        prev_started = prev[7] if prev is not None else None
        rec.services[name] = (
            cmd, list(args), dict(env), cwd, http_port, prev_status, prev_pid, prev_started, None,
        )

    async def start_service(self, handle: SandboxHandle, *, name: str) -> None:
        rec = self._require(handle)
        if name not in rec.services:
            raise SpritesError(f"service {name!r} not declared", retriable=False)
        cmd, args, env, cwd, http_port, status, pid, started_at, _err = rec.services[name]
        if status == "running":
            return
        rec.services[name] = (
            cmd, args, env, cwd, http_port, "running", 4242, "1970-01-01T00:00:00Z", None,
        )

    async def restart_service(self, handle: SandboxHandle, *, name: str) -> None:
        await self.stop_service(handle, name=name)
        await self.start_service(handle, name=name)

    async def stop_service(self, handle: SandboxHandle, *, name: str) -> None:
        rec = self._require(handle)
        if name not in rec.services:
            return
        cmd, args, env, cwd, http_port, _status, _pid, _started, _err = rec.services[name]
        rec.services[name] = (cmd, args, env, cwd, http_port, "stopped", None, None, None)

    async def service_status(
        self, handle: SandboxHandle, *, name: str
    ) -> ServiceStatus:
        rec = self._require(handle)
        entry = rec.services.get(name)
        if entry is None:
            raise SpritesError(f"service {name!r} not found", retriable=False)
        _cmd, _args, _env, _cwd, _port, status, pid, started_at, error = entry
        # mypy/pyright: narrow the runtime str to the Literal.
        narrowed: Literal["stopped", "starting", "running", "stopping", "failed"] = (
            status  # type: ignore[assignment]
            if status in ("stopped", "starting", "running", "stopping", "failed")
            else "stopped"
        )
        return ServiceStatus(
            name=name, status=narrowed, pid=pid, started_at=started_at, error=error
        )

    async def service_logs(
        self, handle: SandboxHandle, *, name: str
    ) -> AsyncIterator[ServiceLogLine]:
        rec = self._require(handle)
        if name not in rec.services:
            raise SpritesError(f"service {name!r} not found", retriable=False)
        queue: asyncio.Queue[ServiceLogLine | None] = asyncio.Queue()
        rec.service_log_queues.setdefault(name, []).append(queue)
        try:
            while True:
                line = await queue.get()
                if line is None:
                    return
                yield line
        finally:
            try:
                rec.service_log_queues[name].remove(queue)
            except (KeyError, ValueError):
                pass

    async def proxy_dial_info(
        self,
        handle: SandboxHandle,
        *,
        host: str = "localhost",
        port: int,
    ) -> ProxyDialInfo:
        rec = self._require(handle)
        return ProxyDialInfo(
            url=f"ws://mock-proxy-unconfigured/{rec.name}/proxy",
            headers=[("X-Mock-Sprite", rec.name)],
            init_host=host,
            init_port=port,
        )

    async def pty_dial_info(
        self,
        handle: SandboxHandle,
        *,
        cwd: str = "/work",
        cols: int = 80,
        rows: int = 24,
        attach_session_id: str | None = None,
    ) -> PtyDialInfo:
        _ = cwd, cols, rows
        rec = self._require(handle)
        # Tests override `_pty_url` to point at a local fake echo server
        # spun up via pytest fixtures. Without an override, return a
        # placeholder URL the broker will fail to dial — clear signal that
        # PTY isn't supported on the bare Mock.
        url = self._pty_url or f"ws://mock-pty-unconfigured/{rec.name}/{attach_session_id or 'new'}"
        return PtyDialInfo(url=url, headers=[("X-Mock-Sprite", rec.name)])

    # ── Test hooks (not part of the Protocol) ────────────────────────────

    def _force_cold(self, handle: SandboxHandle) -> None:
        """Simulate Sprites' idle-hibernation transition for tests."""
        rec = self._require(handle)
        rec.status = "cold"

    def _emit_fs_event(self, rec: "_SpriteRecord", event: FsEvent) -> None:
        """Push `event` to every active fs_watch_subscribe consumer whose
        path covers it. Public test hook: callers may also pass a handle to
        `emit_fs_event` for fixture-driven event injection."""
        for prefix, recursive, queue in rec.watch_queues:
            if not _path_matches(prefix, recursive, event.path):
                continue
            queue.put_nowait(event)

    def emit_fs_event(self, handle: SandboxHandle, event: FsEvent) -> None:
        """Test hook — emit an arbitrary FsEvent into all matching watcher
        queues for the given sprite. Production code never calls this."""
        rec = self._require(handle)
        self._emit_fs_event(rec, event)

    def push_service_log(
        self, handle: SandboxHandle, name: str, line: ServiceLogLine
    ) -> None:
        """Test hook — push a `ServiceLogLine` to every active log
        consumer of `name`. Production code never calls this."""
        rec = self._require(handle)
        for queue in rec.service_log_queues.get(name, []):
            queue.put_nowait(line)

    def close_service_logs(self, handle: SandboxHandle, name: str) -> None:
        """Test hook — terminate every active log stream for `name`."""
        rec = self._require(handle)
        for queue in list(rec.service_log_queues.get(name, [])):
            queue.put_nowait(None)

    def services_declared(self, handle: SandboxHandle) -> dict[str, str]:
        """Test hook — `{service_name: status}` for every declared service."""
        rec = self._require(handle)
        return {name: entry[5] for name, entry in rec.services.items()}

    def runtimes_installed(self, handle: SandboxHandle) -> set[tuple[str, str]]:
        """Test hook — `(manager, version)` pairs the reconciler's
        `installing_runtimes` phase asked nvm/pyenv/rbenv to install."""
        return set(self._require(handle).runtimes_installed)

    def fail_runtime_install(
        self, handle: SandboxHandle, manager: str, version: str, *, exit_code: int = 1
    ) -> None:
        """Test hook — make the next `bash -lc '<manager> install <version>'`
        return a non-zero exit code so failure paths can be exercised."""
        self._require(handle).runtime_install_failures[(manager, version)] = exit_code

    def close_fs_watch(self, handle: SandboxHandle) -> None:
        """Test hook — signal every active watch consumer on the sprite to
        terminate cleanly (yields no more events; the iterator returns)."""
        rec = self._require(handle)
        for _prefix, _recursive, queue in list(rec.watch_queues):
            queue.put_nowait(None)

    def set_git_status_output(self, handle: SandboxHandle, repo_path: str, raw: str) -> None:
        """Test hook — canned `git status --porcelain=v1 -b -z` stdout
        returned for `repo_path`. Pass NUL-separated records exactly as
        git would emit them (the route's parser is what we want to test)."""
        self._require(handle).git_status_outputs[repo_path] = raw

    def set_git_show_output(
        self,
        handle: SandboxHandle,
        repo_path: str,
        spec: str,
        content: str,
    ) -> None:
        """Test hook — canned content for `git -C <repo> show <spec>`.
        `spec` is the `<ref>:<rel_path>` string passed to git show."""
        self._require(handle).git_show_outputs[(repo_path, spec)] = content

    def mark_git_show_missing(
        self, handle: SandboxHandle, repo_path: str, spec: str
    ) -> None:
        """Test hook — make `git show <spec>` exit non-zero (path not in
        ref). The route translates this to `exists=False`."""
        self._require(handle).git_show_missing.add((repo_path, spec))

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
