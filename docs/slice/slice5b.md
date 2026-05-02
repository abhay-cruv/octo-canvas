# Slice 5b — Cloning + reconciliation + checkpoint-based Reset

Slice 4 left us with a working sandbox per user but an empty `/work/`. Slice 5a gave us the wire to push events to the FE. **This slice puts code on the box.**

After this slice, when a user provisions a sandbox, every repo they've connected ends up checked out at `/work/<full_name>/`, system packages required by those repos are `apt-get install`ed, a `clean` checkpoint is taken, and Reset becomes `restore_checkpoint("clean")` — milliseconds instead of destroy+create. Disconnect removes the directory. Reconnect reverses it.

This slice **also widens slice 3's introspection contract** — additive, lands as a slice-3 correction in [progress.md](../progress.md). Two new fields on `RepoIntrospection` + matching overrides:

- `runtimes: list[Runtime]` — Node / Python / Go / Ruby / Rust / Java with version (when detectable). Recorded only; **runtime install is deferred to slice 6** (apt for runtimes is brittle on Ubuntu — slice 6 uses `nvm`/`pyenv`/etc).
- `system_packages: list[str]` — Ubuntu apt package names. **Installed by 5b's clone path**, deduped across all repos in the sandbox.

This slice ends at "**the sandbox is provisioned, populated, and resettable in milliseconds.**" It does **not** include agents, terminals, file-edit endpoints, PR creation, or the User Agent. Those need their own slices.

**Do not build features beyond this slice.** No agent runs (slice 6). No PTY broker (slice 8). No file ops REST endpoints (slice 8). No PR creation (slice 7). No periodic background reconciliation timer (event-driven only).

---

## Calls baked in (push back if any are wrong)

1. **Clone-only, no install step in 5b.** Plan.md mentioned "clone + install" but `npm install` / `pip install` / etc. is expensive, lockfile-sensitive, and version-fragile. Slice 5b clones; slice 6 runs install when the agent first needs it (informed by `Repo.introspection.package_manager`). Cuts scope, matches "the box has the code; the agent prepares its environment."

2. **Reconciliation is event-driven, not periodic.** Triggers: (a) sandbox `wake` (or transition into any alive state), (b) `POST /api/repos/connect`, (c) `DELETE /api/repos/{id}`, (d) sandbox `provision`. **No background timer.** Drift detection is a v1.1 followup if it bites.

3. **`clean` checkpoint refreshed only after a *mutating* reconciliation.** A reconciliation pass that performs at least one clone or remove takes a fresh snapshot and updates `Sandbox.clean_checkpoint_id`. No-op scans skip the snapshot. Avoids burning Sprites checkpoint storage on every wake.

4. **Reset prefers `restore_checkpoint(clean_checkpoint_id)`; falls through to slice 4's destroy+create if no checkpoint exists.** First reset after a fresh provision (no checkpoint yet) takes the slow path; every subsequent reset is fast. The state-machine transitions (`resetting → cold/warm/running`) and `reset_count++` are unchanged.

5. **Clones are serialized per sandbox.** Network-bound, simpler error handling. Concurrent-clone optimization is a v1.1 followup. Different sandboxes (different users) clone in parallel — that's the orchestrator instance's parallelism.

6. **Auth via `git -c http.extraheader='Authorization: Bearer <token>'`** at command time. Token comes from `User.github_access_token` minted into the env at clone time; never persisted into the cloned repo's `.git/config`. On 401: set `Repo.clone_status="failed"`, `Repo.clone_error="github_reauth_required"`. UI surfaces the same Reconnect button slice 2 already has.

7. **Provider Protocol additions in 5b** — exactly:
   - `exec_oneshot(handle, argv: list[str], *, env: dict[str,str], cwd: str, timeout_s: int) -> ExecResult{exit_code, stdout, stderr, duration_s}`
   - `fs_list(handle, path: str) -> list[FsEntry{name, kind: "file"|"dir", size}]`
   - `fs_delete(handle, path: str, *, recursive: bool) -> None`
   - `snapshot(handle, *, comment: str) -> CheckpointId` (`str` newtype)
   - `restore(handle, checkpoint_id: CheckpointId) -> SandboxState`

   **Out of scope: `fs_read` / `fs_write`.** Those land in slice 8 (file ops endpoint). Reconciliation only needs `fs_list` + `fs_delete`. Anything that wants per-byte FS access in 5b uses `exec_oneshot` (`cat`, `tee`, etc).

8. **`Sandbox.clean_checkpoint_id: str | None`** — new field on the doc. Slice 5b's reconciliation writes it; Reset reads it. `None` means "no checkpoint yet, fall through to destroy+create."

9. **Mock provider:** in-memory FS modeled as a `dict[str, set[str]]` keyed by sandbox name → set of cloned `full_name`s. `exec_oneshot` recognizes a few shapes:
   - `git clone https://x@github.com/<full_name>.git /work/<full_name>` → adds `<full_name>` to the set, returns `exit_code=0`.
   - `rm -rf /work/<full_name>` → removes from the set.
   - `apt-get install -y <pkgs>` → records into a separate `_apt_installed: set[str]` for assertion in tests.
   - Anything else → returns `exit_code=0, stdout="", stderr=""`.
   `fs_list`/`fs_delete`/`snapshot`/`restore` operate on the dict. Snapshots are deep-copies keyed by `f"ckpt-{uuid.uuid4().hex[:12]}"`; restore replaces current state with the snapshot.

10. **REST polling for clone status** (no live WS feed in 5b). The FE's existing `connectedReposQueryOptions` polls `/api/repos`; clone status pills (`pending → cloning → ready` / `failed`) update on next poll. Slice 6+ may surface a sandbox-level WS channel for live progress; not needed now.

11. **`Repo.sandbox_id` binding lifecycle:**
    - `POST /api/repos/connect` → if user has an alive sandbox: bind `sandbox_id`, set `clone_status="pending"`, kick off async clone. If no sandbox: `sandbox_id=null`, `clone_status="pending"`, clone runs on next sandbox provision.
    - On `POST /api/sandboxes` (provision): bulk-bind every `sandbox_id=null` `Repo` row owned by this user to the new sandbox, kick off reconciliation.
    - On `POST /api/sandboxes/{id}/destroy`: bulk-update repos previously bound to this sandbox → `sandbox_id=null`, `clone_status="pending"`. Clone state is owned by the sandbox; user can re-provision and re-clone fresh.
    - On `POST /api/sandboxes/{id}/reset`: repos stay bound (sandbox `_id` preserved); the `restore_checkpoint` path skips re-cloning entirely.

12. **Introspection deepening (folded into 5b, not a separate slice):**
    - Two new fields on `RepoIntrospection`:
      ```python
      class Runtime(BaseModel):
          name: Literal["node", "python", "go", "ruby", "rust", "java"]
          version: str | None        # None when no version file present
          source: str                # "package.json#engines.node", ".nvmrc", etc.

      class RepoIntrospection(BaseModel):
          # ... existing fields ...
          runtimes: list[Runtime]        # multiple supported (monorepo)
          system_packages: list[str]
      ```
    - Mirror on `IntrospectionOverrides`:
      ```python
      class IntrospectionOverrides(BaseModel):
          # ... existing fields ...
          runtimes: list[Runtime] | None
          system_packages: list[str] | None
      ```
    - Detection signals in `python_packages/repo_introspection/`:
      | Source | Detects |
      |---|---|
      | `package.json#engines.node`, `.nvmrc`, `.node-version` | Node + version |
      | `pyproject.toml#requires-python`, `.python-version`, `runtime.txt` | Python + version |
      | `go.mod` first line | Go + version |
      | `Gemfile`, `.ruby-version` | Ruby + version |
      | `Cargo.toml#package.rust-version` | Rust + version |
      | `Dockerfile` `apt-get install` lines (greedy regex) | system_packages |
      | `apt.txt` (Heroku/Render convention) | system_packages |
      | `package.json#dependencies` known-native modules (`sharp`→`libvips-dev`, `canvas`→`libcairo2-dev libpango1.0-dev`, `node-canvas`→same) | system_packages |
      | `requirements.txt` known wheels (`psycopg2`→`libpq-dev`, `lxml`→`libxml2-dev libxslt1-dev`, `pyodbc`→`unixodbc-dev`) | system_packages |
    - **Conservative detection.** False positives are worse than misses (a missed package can be added via override; a wrong package wastes clone time). Walk the top three depths only.
    - **No runtime install in 5b.** Slice 6 owns it via `nvm`/`pyenv`. Detected runtimes show on the dashboard repo card so the user knows what slice 6 will use.

13. **`apt-get install` runs once per sandbox per reconciliation pass**, deduped across every alive `Repo` in the sandbox. Long-running but cached after first install (Sprites' filesystem persists). On failure: log + emit an `ErrorEvent`-like signal into Mongo, but proceed with cloning — missing system packages aren't blocking for slice 5b's acceptance (the agent finds out later).

14. **Reconciliation is its own service** — `apps/orchestrator/src/orchestrator/services/reconciliation.py`. One public coroutine: `async def reconcile(sandbox_id) -> ReconciliationResult`. Idempotent. Acquires a per-sandbox in-memory lock so two concurrent triggers (e.g., simultaneous connect + wake) don't race; the second waits for the first to finish then runs another pass.

15. **No new HTTP endpoints in 5b.** Reconciliation is invoked from existing endpoints (`provision`, `wake`, `connect`, `disconnect`). Status flows through existing `GET /api/repos`. Only the schemas widen.

---

## Context from slice 5a

Slice 5a is signed off. Read it ([slice5a.md](slice5a.md)) before starting if you don't have it in conversation history. Key things now in place:

- `python_packages/sandbox_provider/src/sandbox_provider/interface.py` — `SandboxProvider` Protocol with `create / status / destroy / wake / pause`. **You will widen it** with the five methods listed in §7.
- [`apps/orchestrator/src/orchestrator/services/sandbox_manager.py`](../../apps/orchestrator/src/orchestrator/services/sandbox_manager.py) — `SandboxManager` class. **You will modify `reset` to prefer `restore_checkpoint` and add a hook to invoke reconciliation on relevant transitions.**
- [`apps/orchestrator/src/orchestrator/routes/sandbox.py`](../../apps/orchestrator/src/orchestrator/routes/sandbox.py) — provision/wake routes. **You will add a `reconcile()` call after each successful state transition that's "alive."**
- [`apps/orchestrator/src/orchestrator/routes/repos.py`](../../apps/orchestrator/src/orchestrator/routes/repos.py) — connect/disconnect routes. **You will add `reconcile()` calls.**
- [`python_packages/db/src/db/models/sandbox.py`](../../python_packages/db/src/db/models/sandbox.py) — `Sandbox` Document. **You will add `clean_checkpoint_id: str | None = None`.**
- [`python_packages/db/src/db/models/repo.py`](../../python_packages/db/src/db/models/repo.py) — `Repo` Document. Already has `sandbox_id: PydanticObjectId | None` and `clone_status: Literal["pending","cloning","ready","failed"]`. **You will populate these fields properly for the first time.**
- [`python_packages/repo_introspection/`](../../python_packages/repo_introspection/) — `introspect_via_github`. **You will add detector functions for runtimes + system_packages and populate the new fields.**
- [`python_packages/shared_models/src/shared_models/introspection.py`](../../python_packages/shared_models/src/shared_models/introspection.py) — `RepoIntrospection` + `IntrospectionOverrides`. **You will widen both with the new fields.**
- [`packages/api-types/generated/schema.d.ts`](../../packages/api-types/generated/schema.d.ts) — regenerate at the end (the `runtimes` + `system_packages` fields cross the wire).
- The `clone_status="cloning"` literal is new; widen the existing `clone_status` Literal.

---

## What "done" looks like

After this slice, a signed-in user can:

1. Connect three repos against an alive sandbox → all three transition `pending → cloning → ready`. `Repo.sandbox_id` is populated. `Repo.clone_path == "/work/<full_name>/"`. **The `clean` checkpoint exists** (`Sandbox.clean_checkpoint_id` set).
2. Disconnect one of those repos → its directory is removed via `provider.exec_oneshot(["rm","-rf",...])`. `Repo` row deleted. **A new `clean` checkpoint replaces the old one.**
3. Click **Reset** → sandbox transitions `resetting → warm`, takes ~1 second instead of ~30. The two remaining repos are still present (the checkpoint contained them). `Sandbox.reset_count++`. `provider_handle.id` rotates.
4. Click **Destroy** → sandbox doc → `destroyed`, all repos formerly bound to it → `sandbox_id=null`, `clone_status="pending"`. User provisions a new sandbox → repos re-clone.
5. Connect a repo whose `package.json` has `"sharp": "^0.33"` and a Dockerfile with `apt-get install -y libpq-dev` → `Repo.introspection.system_packages == ["libpq-dev", "libvips-dev"]`. After clone, `apt-get install -y libpq-dev libvips-dev` ran in the sandbox.
6. Open a connected repo's "Dependencies" UI affordance → see the detected runtimes (e.g. `node 20`, `python 3.12`) and system packages, plus an editable override list.
7. Revoke their GitHub OAuth grant → next clone fails 401 → repo card shows the existing Reconnect button. Reconnect → next reconciliation cycle picks up the previously-failed clone and succeeds.

A user who has NOT yet provisioned a sandbox:
- Can still connect repos (slice 2 behavior). `Repo.sandbox_id=null`, `clone_status="pending"`. On first sandbox provision, all pending repos get bound and cloned.

---

## What to build

### 1. Provider Protocol widening — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`

Add these to `SandboxProvider` (alongside existing `create / status / destroy / wake / pause`):

```python
class ExecResult(TypedDict):
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float

class FsEntry(TypedDict):
    name: str
    kind: Literal["file", "dir"]
    size: int

CheckpointId = NewType("CheckpointId", str)

class SandboxProvider(Protocol):
    # ... existing methods ...
    async def exec_oneshot(
        self, handle: SandboxHandle, argv: list[str], *,
        env: Mapping[str, str], cwd: str, timeout_s: int = 300,
    ) -> ExecResult: ...
    async def fs_list(self, handle: SandboxHandle, path: str) -> list[FsEntry]: ...
    async def fs_delete(self, handle: SandboxHandle, path: str, *, recursive: bool = False) -> None: ...
    async def snapshot(self, handle: SandboxHandle, *, comment: str) -> CheckpointId: ...
    async def restore(self, handle: SandboxHandle, checkpoint_id: CheckpointId) -> SandboxState: ...
```

Both `MockSandboxProvider` and `SpritesProvider` implement them. Sprites impl uses `sprite.command(...)` + `create_checkpoint` + `restore_checkpoint` from the SDK; for `fs_list`/`fs_delete` use the raw HTTP `_client` per the rc37/rc43 fs surface (same pattern as slice 4's `kill_session` workaround if the SDK doesn't expose them as methods).

### 2. Schema additions — `Sandbox`, `Repo`, `RepoIntrospection`, `IntrospectionOverrides`

- `Sandbox.clean_checkpoint_id: str | None = None`.
- `Repo.clone_status` widened to include `"cloning"`.
- `Repo.clone_error: str | None = None` for failure diagnostics.
- `RepoIntrospection.runtimes: list[Runtime]` and `.system_packages: list[str]` (default `[]`).
- `IntrospectionOverrides.runtimes` and `.system_packages` (`None | list[...]`).
- `Runtime` model in `shared_models/introspection.py`.

### 3. Reconciliation service — `apps/orchestrator/src/orchestrator/services/reconciliation.py`

```python
@dataclass
class ReconciliationResult:
    cloned: list[str]      # full_names
    removed: list[str]
    failed: list[tuple[str, str]]   # (full_name, error)
    apt_installed: list[str]
    checkpoint_taken: bool
    new_checkpoint_id: str | None

async def reconcile(sandbox_id: PydanticObjectId) -> ReconciliationResult: ...
```

Per-sandbox `asyncio.Lock` guards concurrent invocations; the second one waits then runs another pass.

Algorithm:
1. Load `Sandbox` + every `Repo` where `sandbox_id == this`.
2. `provider.fs_list(handle, "/work")` → set of currently-present `full_name`s.
3. Diff:
   - In `Repo` rows but not on disk → clone.
   - On disk but not in `Repo` rows → `provider.fs_delete(handle, "/work/<full_name>", recursive=True)`.
   - In both → no-op.
4. **Before any clone:** dedupe `system_packages` across all alive repos and run `apt-get install -y <pkgs>` once. Skip if zero packages.
5. For each clone target: serial loop, `provider.exec_oneshot(["git", "clone", "-c", f"http.extraheader=Authorization: Bearer {token}", url, target])`. Update `Repo.clone_status` → `"cloning"` before, `"ready"` or `"failed"` after.
6. **If any mutation happened:** `provider.snapshot(handle, comment="clean")` → write `Sandbox.clean_checkpoint_id`.

### 4. Wire reconciliation into existing routes/services

- `routes/sandbox.py:provision` → after `manager.create()` succeeds, bulk-bind pending repos and call `reconcile(sandbox_id)` in the background (`asyncio.create_task` — clone time shouldn't block the HTTP response).
- `routes/sandbox.py:wake` → after `manager.wake()` succeeds, schedule a `reconcile(sandbox_id)` if any repo for this sandbox is `pending` or `failed`. (Avoid no-op reconciliations on every wake.)
- `routes/sandbox.py:reset` → `manager.reset()` calls `provider.restore` if `clean_checkpoint_id` is set, else falls through to slice 4's destroy+create.
- `routes/sandbox.py:destroy` → bulk-update repos to `sandbox_id=null, clone_status="pending"`.
- `routes/repos.py:connect_repo` → after `Repo.create()`, if user has alive sandbox, bind + `reconcile(sandbox_id)` in background.
- `routes/repos.py:disconnect_repo` → before deleting the `Repo`, capture `sandbox_id`. After delete, schedule `reconcile(sandbox_id)`.

### 5. `SandboxManager.reset` — checkpoint path

```python
async def reset(self, sandbox: Sandbox) -> Sandbox:
    if sandbox.status not in _RESET_FROM:
        raise IllegalSandboxTransitionError(sandbox.status, "reset")
    sandbox.status = "resetting"
    await sandbox.save()

    if sandbox.clean_checkpoint_id is not None:
        try:
            state = await self._provider.restore(_handle_of(sandbox), CheckpointId(sandbox.clean_checkpoint_id))
            sandbox.status = state.status
            sandbox.public_url = state.public_url
            sandbox.reset_count += 1
            sandbox.last_reset_at = _now()
            await sandbox.save()
            await self._redis_write(sandbox)
            return sandbox
        except SpritesError as exc:
            # Checkpoint missing or corrupt — fall through to slow path.
            _logger.warning("sandbox.reset.checkpoint_failed", error=str(exc))

    # Slow path — slice 4's destroy+create.
    return await self._reset_slow(sandbox)
```

`_reset_slow` is the body of the current `reset` method renamed.

### 6. Introspection deepening — `python_packages/repo_introspection/`

New detector module(s). Reuse the existing Trees+Contents pattern:

- `detect_runtimes(tree, fetch_contents) -> list[Runtime]`
- `detect_system_packages(tree, fetch_contents) -> list[str]`

Both called from `introspect_via_github`. Conservative — never invent packages from heuristics weaker than the table above.

### 7. UI surface

- Repo card in [`apps/web/src/routes/_authed/dashboard.tsx`](../../apps/web/src/routes/_authed/dashboard.tsx) widens to show the cloned status, runtimes, and system packages from `Repo.introspection`. Existing override panel grows two more rows.
- New `clone_status="cloning"` pill copy: "Cloning…" with a spinner. `failed` shows the error and a "Retry" button that pokes a new reconciliation (REST: hit any endpoint that triggers reconciliation — e.g. `POST /api/sandboxes/{id}/refresh`).

### 8. Tests

- Provider unit tests for the five new methods (mock + sprites).
- `test_reconciliation.py`:
  - All three quadrants of the diff matrix (clone-needed, remove-needed, no-op).
  - Auth failure → `clone_status="failed"`.
  - Mutation → checkpoint taken; idempotent run → no checkpoint.
  - Two concurrent triggers → second one runs after first.
- `test_reset_checkpoint.py`: with checkpoint → fast path; without → slow path.
- `test_introspection_deepening.py`: each detector source produces the expected result; conservative behavior on ambiguous input.

### 9. Docs

- [`docs/progress.md`](../progress.md) — slice 5b row → in flight; introspection schema additions documented as a slice-3 correction post-freeze.
- [`docs/Contributions.md`](../Contributions.md) — entry at end of session.
- [`docs/agent_context.md`](../agent_context.md) — updated TL;DR when this slice ships.
- [`docs/Plan.md`](../Plan.md) — §8 `Repo` schema, §13 sandbox lifecycle (Reset uses checkpoint), §18 slice 5b entry → ✅ at sign-off.
- This file (slice5b.md) is frozen on sign-off.

---

## Out of scope (explicit)

- File ops endpoints (`GET/PUT /api/sandboxes/{id}/fs`). Slice 8.
- PTY broker. Slice 8.
- Live WS feed of clone progress. Possibly slice 6+.
- Periodic background reconciliation timer. v1.1 followup.
- Concurrent clones within one sandbox. v1.1 followup.
- Runtime installation (nvm/pyenv). Slice 6.
- Cross-sandbox checkpoint sharing. Never.
- A "rebuild from scratch" UI button. Use Destroy → Provision today.

---

## Risks

1. **Sprites checkpoint API at rc37 may not expose `create_checkpoint` / `restore_checkpoint` as Python methods** — fall back to raw HTTP via `self._client._client.post(...)` (same pattern as slice 4's `kill_session`). Document the version check; flip to SDK methods when they ship.
2. **Token leakage** — `git -c http.extraheader=...` should not write the token to `.git/config`. Verify by `cat .git/config` after clone in tests; the file should contain no `Authorization`.
3. **Concurrent reconciliation triggers** — a user clicking Connect twice in 100ms. Per-sandbox `asyncio.Lock` ensures serial; the second trigger sees the same sandbox state after the first completes and may no-op.
4. **Sprite cold during reconciliation** — Sprites auto-warms on exec; the SDK call blocks briefly then proceeds. No app-level intervention needed. Document.
5. **Reset-checkpoint race with in-flight clone** — if Reset fires while reconciliation is mid-clone, the in-progress `git clone` in the doomed sprite is cancelled when the sprite is restored to its pre-clone state. The Reset path waits for the reconciliation lock before issuing the restore — otherwise the post-restore state has half-cloned dirs.
6. **Detection false positives in `system_packages`** — a Dockerfile that installs `libpq-dev` for a build stage we don't need would trigger a wasted apt install. Mitigation: flag detected packages on the UI and let the user remove via override before the next reconciliation.
7. **`apt-get install` failure** — package name typo, mirror outage, dpkg lock. Don't block clones; log + continue. Slice 6's agent finds out when it tries to `import psycopg2` and the wheel can't link.
8. **Disk pressure from many checkpoints** — Sprites docs say copy-on-write keeps incremental checkpoints small, but a long-lived sandbox with frequent connect/disconnect cycles could stack many `clean` revisions. Mitigation: each new `clean` snapshot replaces the previous one — delete the old checkpoint after the new one is committed.
9. **Mongo schema migration** — existing `RepoIntrospection` rows have neither `runtimes` nor `system_packages`. Pydantic defaults handle reads (default empty list), but old rows on first write must be back-filled. Solution: when `introspect_via_github` runs again (on connect or via manual reintrospect), it overwrites `introspection_detected` wholesale — old rows naturally migrate as users touch them.

---

## Acceptance — copy-paste checklist

- [ ] `pnpm typecheck` clean.
- [ ] `pnpm lint` clean.
- [ ] `pnpm --filter @octo-canvas/api-types gen:api-types` regenerates `schema.d.ts` and `wire.d.ts`; both committed; `pnpm typecheck` still clean.
- [ ] `uv run pytest` clean (orchestrator + sandbox_provider + repo_introspection). New tests cover:
  - happy path: connect 3 repos against alive sandbox → all 3 cloned, checkpoint taken.
  - reset-checkpoint: with checkpoint → `provider.restore` called; without → slow path.
  - destroy → repos go back to `sandbox_id=null, clone_status="pending"`.
  - disconnect → directory removed, checkpoint refreshed.
  - clone 401 → `clone_status="failed", clone_error="github_reauth_required"`.
  - reconcile concurrency: two triggers in parallel → serialized, end-state correct.
  - introspection runtimes: `package.json#engines.node` + `pyproject.toml#requires-python` → both in `runtimes`.
  - introspection system_packages: Dockerfile `apt-get install -y libpq-dev` → present in `system_packages`.
- [ ] Manual smoke (mock provider): provision sandbox in browser, connect three repos, watch pills go pending → cloning → ready, click Reset, watch the fast path.
- [ ] Manual smoke (real Sprites): same flow against a real `SPRITES_TOKEN`. Confirm `/work/<full_name>/` exists via a one-shot exec, confirm `apt-get install` ran for at least one detected package.
- [ ] [`docs/progress.md`](../progress.md) row updated; introspection schema additions noted as slice-3 correction.
- [ ] [`docs/Contributions.md`](../Contributions.md) entry added.
- [ ] [`docs/agent_context.md`](../agent_context.md) status line updated.
- [ ] User signs off → this brief is frozen; corrections live in `progress.md`.
