# Graph Report - .  (2026-05-02)

## Corpus Check
- 169 files · ~165,167 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1003 nodes · 2079 edges · 77 communities detected
- Extraction: 66% EXTRACTED · 34% INFERRED · 0% AMBIGUOUS · INFERRED: 716 edges (avg confidence: 0.71)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Orchestrator Core|Orchestrator Core]]
- [[_COMMUNITY_Sprites Checkpoint API|Sprites Checkpoint API]]
- [[_COMMUNITY_Sandbox Reconciliation|Sandbox Reconciliation]]
- [[_COMMUNITY_Sandbox Manager & Deps|Sandbox Manager & Deps]]
- [[_COMMUNITY_Persistence & Health|Persistence & Health]]
- [[_COMMUNITY_Project Conventions & Docs|Project Conventions & Docs]]
- [[_COMMUNITY_Repo Connection Flow|Repo Connection Flow]]
- [[_COMMUNITY_Sprites Exec Protocol|Sprites Exec Protocol]]
- [[_COMMUNITY_Provider Protocol Types|Provider Protocol Types]]
- [[_COMMUNITY_GitHub Repo Introspection|GitHub Repo Introspection]]
- [[_COMMUNITY_Wire Protocol Models|Wire Protocol Models]]
- [[_COMMUNITY_GitHub Auth Wrapper|GitHub Auth Wrapper]]
- [[_COMMUNITY_Sprites Provider Tests|Sprites Provider Tests]]
- [[_COMMUNITY_App Entrypoints|App Entrypoints]]
- [[_COMMUNITY_Command Detection|Command Detection]]
- [[_COMMUNITY_Auth Endpoints|Auth Endpoints]]
- [[_COMMUNITY_Package Manager Detection|Package Manager Detection]]
- [[_COMMUNITY_Sandbox Lifecycle Methods|Sandbox Lifecycle Methods]]
- [[_COMMUNITY_Runtime Detection|Runtime Detection]]
- [[_COMMUNITY_System Package Detection|System Package Detection]]
- [[_COMMUNITY_Language Detection|Language Detection]]
- [[_COMMUNITY_Smoke Tests|Smoke Tests]]
- [[_COMMUNITY_Wire Schema Generator|Wire Schema Generator]]
- [[_COMMUNITY_Task Stream Hook|Task Stream Hook]]
- [[_COMMUNITY_Login Page|Login Page]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]

## God Nodes (most connected - your core abstractions)
1. `MockSandboxProvider` - 42 edges
2. `Beanie models, raw collection access, and Mongo lifecycle helpers.` - 37 edges
3. `SandboxManager` - 35 edges
4. `Reconciler` - 34 edges
5. `SandboxHandle` - 34 edges
6. `SpritesError` - 33 edges
7. `TaskFanout` - 28 edges
8. `_seed_user_and_session()` - 26 edges
9. `_seed_user_and_session()` - 25 edges
10. `detect_commands()` - 25 edges

## Surprising Connections (you probably didn't know these)
- `_seed_user_and_session()` --calls--> `User`  [INFERRED]
  apps/orchestrator/tests/test_repos.py → python_packages/db/src/db/models/user.py
- `_seed_user_and_session()` --calls--> `Session`  [INFERRED]
  apps/orchestrator/tests/test_repos.py → python_packages/db/src/db/models/session.py
- `test_connect_propagates_reauth_from_introspection()` --calls--> `GithubReauthRequired`  [INFERRED]
  apps/orchestrator/tests/test_repos.py → python_packages/github_integration/src/github_integration/exceptions.py
- `test_reintrospect_clears_token_on_reauth()` --calls--> `GithubReauthRequired`  [INFERRED]
  apps/orchestrator/tests/test_repos.py → python_packages/github_integration/src/github_integration/exceptions.py
- `Stub `introspect_via_github` imported into the routes module.      Default: retu` --uses--> `RepoIntrospection`  [INFERRED]
  apps/orchestrator/tests/test_repos.py → python_packages/shared_models/src/shared_models/introspection.py

## Hyperedges (group relationships)
- **Pydantic → OpenAPI → TS type-bridge chain** — concept_pydantic_models, concept_fastapi, concept_openapi_fetch, plan_type_bridges, readme_api_types_regen [EXTRACTED 0.95]
- **Three-app topology: web SPA ↔ orchestrator ↔ bridge-in-Sprites** — concept_web_spa, concept_orchestrator, concept_bridge, sprites_sandbox_concept, concept_turborepo [EXTRACTED 1.00]
- **Agent cold-start doc-read order** — agent_context_primer, claude_md_entrypoint, agents_md, progress_state, contributions_log, plan_doc [EXTRACTED 1.00]
- **Sandbox lifecycle (create/checkpoint/restore/delete)** — sprites_python_management_create_sprite, sprites_python_checkpoints_create, sprites_python_checkpoints_restore, sprites_python_management_delete_sprite [INFERRED 0.90]
- **Service lifecycle (create/start/stop/restart)** — sprites_python_services_create, sprites_python_services_start, sprites_python_services_stop, sprites_python_services_restart [EXTRACTED 1.00]
- **Exec session lifecycle (start/list/attach/kill)** — sprites_python_exec_command, sprites_python_exec_list_sessions, sprites_python_exec_attach_session, sprites_python_exec_kill [EXTRACTED 1.00]
- **Checkpoint lifecycle: create -> list/get -> restore** —  [EXTRACTED 1.00]
- **Exec session lifecycle: start -> list/attach -> kill** —  [EXTRACTED 1.00]
- **Sprite policies: network, privileges, resources** —  [EXTRACTED 1.00]

## Communities

### Community 0 - "Orchestrator Core"
Cohesion: 0.05
Nodes (76): lifespan(), client(), Real Redis on the test DB (db 15). Flushes before AND after the test     so any, redis_client(), _allocate_seq(), append_event(), channel_for(), Persist + publish wire-protocol events on `/ws/web/tasks/{task_id}`.  Allocates (+68 more)

### Community 1 - "Sprites Checkpoint API"
Cohesion: 0.03
Nodes (79): Checkpoints section, Copy-on-write incremental snapshots, POST /v1/sprites/{name}/checkpoint (NDJSON stream), GET /v1/sprites/{name}/checkpoints/{checkpoint_id}, GET /v1/sprites/{name}/checkpoints, POST /v1/sprites/{name}/checkpoints/{checkpoint_id}/restore (NDJSON), Checkpoint schema (id, create_time, source_id, comment, health), POST /v1/sprites/{name}/exec/{session_id}/kill (NDJSON) (+71 more)

### Community 2 - "Sandbox Reconciliation"
Cohesion: 0.08
Nodes (47): MockSandboxProvider, _handle_of(), _lock_for(), _mark_clone_failed(), _merge_system_packages(), Per-sandbox reconciliation — slice 5b.  Diffs the sandbox's `/work` listing agai, One-time-per-token git setup inside the sandbox.          Writes:         - `~/., Update the sandbox's progress banner using an atomic per-field     `$set`, NOT ` (+39 more)

### Community 3 - "Sandbox Manager & Deps"
Cohesion: 0.08
Nodes (45): FastAPI dependencies that resolve request-scoped collaborators (provider, manage, _bad_provider_if_failed(), _cancel_pause_resync_for(), _cancel_reconcile_for(), _cancel_tasks_with_prefix(), _conflict(), destroy_sandbox(), get_or_create_sandbox() (+37 more)

### Community 4 - "Persistence & Health"
Cohesion: 0.04
Nodes (28): AgentEvent, Persisted agent event — the durable copy of every frame that goes out on `/ws/we, Settings, health(), Liveness + Mongo reachability. 503 if Mongo is down so load balancers     drop u, Collections, Single source of truth for Mongo collection names.  Every Beanie `Document.Setti, Canonical collection names. Use these instead of string literals. (+20 more)

### Community 5 - "Project Conventions & Docs"
Cohesion: 0.05
Nodes (59): Cold-start agent context primer, Banned dependencies (Hono, Express, tRPC, Drizzle, Bun, Next.js, Prisma, Clerk, Better Auth, Poetry, conda, rye, npm, yarn, mypy, black, isort, flake8), Dependency & tooling constraints, Deviation protocol — stop and ask, Documentation rules (always-update, frozen, deviation protocol), Frontend theme — light mode, black accents, mobile-first, Use graphify-out as your map, AGENTS.md canonical agent rules (+51 more)

### Community 6 - "Repo Connection Flow"
Cohesion: 0.07
Nodes (47): connectRepo(), GithubReauthRequiredError, reintrospectRepo(), destroySandbox(), getOrCreateSandbox(), pauseSandbox(), Per-user sandbox handle. v1 enforces "one running sandbox per user" at     the o, refreshSandbox() (+39 more)

### Community 7 - "Sprites Exec Protocol"
Cohesion: 0.04
Nodes (55): Bearer token (SPRITES_TOKEN) authentication, Command Execution section, WSS /v1/sprites/{name}/exec/{session_id} (Attach), Binary frame: Stream ID byte (0=stdin,1=stdout,2=stderr,3=exit,4=stdin_eof), ExitMessage (type=exit, exit_code), GET /v1/sprites/{name}/exec (List Sessions), PortNotificationMessage (port_opened|port_closed, port, address, pid), POST /v1/sprites/{name}/exec (HTTP exec, non-TTY) (+47 more)

### Community 8 - "Provider Protocol Types"
Cohesion: 0.14
Nodes (31): ExecResult, FsEntry, SandboxProvider Protocol — slice 4 (provisioning) + slice 5b (clone/exec/fs/chec, Provider-opaque sandbox identity. Persisted on `Sandbox.provider_handle`     in, What `status()` returns. `public_url` is None until the underlying     sandbox h, Return value of `exec_oneshot`. `stdout`/`stderr` are size-bounded by     the pr, One entry in a `fs_list` response., Wraps any error returned by the underlying provider. Sanitized — never     inclu (+23 more)

### Community 9 - "GitHub Repo Introspection"
Cohesion: 0.12
Nodes (36): RepoIntrospection, introspect_via_github(), Single entry point: turn (gh, owner, name, ref) into a RepoIntrospection., Repo, Settings, _patch_introspection(), _patch_user_client(), Non-401 introspection failures must not block the connection. (+28 more)

### Community 10 - "Wire Protocol Models"
Cohesion: 0.1
Nodes (25): BaseModel, ClientPing, ClientPong, Sent as the FIRST frame of every (re)connection. The orchestrator     streams ev, Resume, _WireCommand, BackpressureWarning, ErrorEvent (+17 more)

### Community 11 - "GitHub Auth Wrapper"
Cohesion: 0.1
Nodes (31): call_with_reauth(), Thin wrapper around githubkit for OAuth-token calls., Run a githubkit coroutine; convert HTTP 401 into GithubReauthRequired., user_client(), Exception, GithubReauthRequired, Raised when a GitHub call returns 401 — the stored OAuth token is no longer vali, fetch_blob_text() (+23 more)

### Community 12 - "Sprites Provider Tests"
Cohesion: 0.13
Nodes (23): _build_provider(), _FakeClient, _FakeCommand, _FakeHttpClient, _FakeHttpResponse, _FakeSession, _FakeSprite, _FakeSpriteWrapper (+15 more)

### Community 13 - "App Entrypoints"
Cohesion: 0.09
Nodes (17): BaseSettings, Settings, configure_logging(), get_logger(), main(), build_sandbox_provider(), Construct the right `SandboxProvider` based on `Settings.sandbox_provider`.  Exp, Process-singleton Redis handle.  Mirrors the `db.mongo` pattern: one instance pe (+9 more)

### Community 14 - "Command Detection"
Cohesion: 0.16
Nodes (28): detect_commands(), _js_commands(), _PkgJson, _python_test_command(), Web → orchestrator messages on `/ws/web/tasks/{task_id}`.  Slice 5a covers sessi, Return (test_command, build_command, dev_command) for the detected stack.      `, _stub_blobs(), test_bundler_with_rspec_in_gemfile() (+20 more)

### Community 15 - "Auth Endpoints"
Cohesion: 0.1
Nodes (18): _callback_url(), _cookie_kwargs(), _create_session(), _fetch_github_profile(), get_user_optional(), github_callback(), github_login(), github_manage() (+10 more)

### Community 16 - "Package Manager Detection"
Cohesion: 0.18
Nodes (25): detect_package_manager(), Detect package manager from filenames + (for ambiguous Python) a manifest blob., Filenames that sit at the repo root — package-manager signals only count     at, Return the project's package manager, or None.      `fetch_blob(path)` is the cu, _root_files(), _stub_blob(), test_build_gradle_means_gradle(), test_bun_lock() (+17 more)

### Community 17 - "Sandbox Lifecycle Methods"
Cohesion: 0.09
Nodes (13): Live status from the provider. Raises `SpritesError` if the         sandbox no l, Tear down the sandbox AND its filesystem. Idempotent: a 404 from         the pro, Force a `cold` sandbox to `warm`/`running`. Sprites auto-wakes on         any ex, Force the sandbox to release compute (target `cold`).          Sprites has no ex, Run `argv` inside the sandbox to completion. Captures stdout and         stderr., List entries in `path`. Raises `SpritesError(retriable=False)` if         the pa, Delete `path`. `recursive=True` for directories. Idempotent: a         404 from, Create a point-in-time checkpoint of the sandbox's filesystem.         Returns t (+5 more)

### Community 18 - "Runtime Detection"
Cohesion: 0.2
Nodes (19): Runtime, detect_runtimes(), _has_any(), _node_from_package_json(), _python_from_pyproject(), Detect runtimes (Node, Python, Go, Ruby, Rust, Java) from version files.  Heuris, Return all runtimes detected anywhere in the repo tree.      `paths` is the set, _read_first() (+11 more)

### Community 19 - "System Package Detection"
Cohesion: 0.22
Nodes (17): detect_system_packages(), _parse_dockerfile_apt(), Detect Ubuntu apt packages required by a repo.  Best-effort heuristics. False po, Extract apt-get install package names. Joins line continuations     (`\\\n`) bef, System-package detection — slice 5b introspection deepening., `psycopg2-binary` ships a wheel — no system dep needed., _stub(), test_apt_txt() (+9 more)

### Community 20 - "Language Detection"
Cohesion: 0.23
Nodes (12): detect_primary_language(), _is_vendor(), Pick the primary language by counting recognised file extensions., Pick the language with the most files. Tie → alphabetical.      Vendor-dir files, test_alphabetical_tiebreak(), test_ignores_dist_and_venv(), test_ignores_node_modules(), test_ignores_unknown_extensions() (+4 more)

### Community 21 - "Smoke Tests"
Cohesion: 0.29
Nodes (1): test_imports()

### Community 22 - "Wire Schema Generator"
Cohesion: 0.5
Nodes (4): _hoist(), main(), Dump the wire-protocol discriminated unions as JSON Schema.  Pipe the output to, Pydantic emits each variant under `$defs`; pull them up to a shared     top-leve

### Community 23 - "Task Stream Hook"
Cohesion: 0.5
Nodes (0): 

### Community 24 - "Login Page"
Cohesion: 0.67
Nodes (0): 

### Community 25 - "Community 25"
Cohesion: 1.0
Nodes (0): 

### Community 26 - "Community 26"
Cohesion: 1.0
Nodes (0): 

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (0): 

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (0): 

### Community 29 - "Community 29"
Cohesion: 1.0
Nodes (0): 

### Community 30 - "Community 30"
Cohesion: 1.0
Nodes (0): 

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (0): 

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (0): 

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (0): 

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (0): 

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (0): 

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (0): 

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (0): 

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (0): 

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (0): 

### Community 40 - "Community 40"
Cohesion: 1.0
Nodes (0): 

### Community 41 - "Community 41"
Cohesion: 1.0
Nodes (0): 

### Community 42 - "Community 42"
Cohesion: 1.0
Nodes (0): 

### Community 43 - "Community 43"
Cohesion: 1.0
Nodes (0): 

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (0): 

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (0): 

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (0): 

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (0): 

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (0): 

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (0): 

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (0): 

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (0): 

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (0): 

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (0): 

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (0): 

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (0): 

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (0): 

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (0): 

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (0): 

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (0): 

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (0): 

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (1): Common commands (pnpm dev/build/test/lint)

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (1): Read-before-write doc order

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (1): Modular and small (file/function caps)

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (1): Reuse before you write

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (1): Don't add what wasn't asked for

## Knowledge Gaps
- **175 isolated node(s):** `POST /api/_internal/tasks/{id}/events — slice 5a dev-only injector.`, `Unit tests for event_store: atomic seq allocation, persistence, replay.`, ``redis=None` is a valid slice 5a config (single instance, no fanout).     Persis`, `append_event with a real Redis publishes a JSON frame that round-trips     throu`, `Construct the right `SandboxProvider` based on `Settings.sandbox_provider`.  Exp` (+170 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 25`** (2 nodes): `SandboxPanel.tsx`, `SandboxPanel()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (2 nodes): `queries.ts`, `availableReposQueryOptions()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (2 nodes): `$taskId.tsx`, `inject()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (2 nodes): `test_smoke.py`, `test_bridge_imports()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (2 nodes): `test_health.py`, `test_health()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (1 nodes): `schema.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (1 nodes): `wire.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (1 nodes): `schema.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (1 nodes): `index.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (1 nodes): `tailwind.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (1 nodes): `vite.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (1 nodes): `postcss.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (1 nodes): `main.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (1 nodes): `vite-env.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (1 nodes): `routeTree.gen.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (1 nodes): `api.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (1 nodes): `wire.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (1 nodes): `index.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (1 nodes): `__root.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (1 nodes): `_authed.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (1 nodes): `index.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (1 nodes): `connect.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `main.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (1 nodes): `Common commands (pnpm dev/build/test/lint)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `Read-before-write doc order`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (1 nodes): `Modular and small (file/function caps)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `Reuse before you write`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `Don't add what wasn't asked for`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Beanie models, raw collection access, and Mongo lifecycle helpers.` connect `Wire Protocol Models` to `Orchestrator Core`, `Sandbox Reconciliation`, `Sandbox Manager & Deps`, `Persistence & Health`, `Provider Protocol Types`, `GitHub Repo Introspection`, `GitHub Auth Wrapper`, `Auth Endpoints`, `Sandbox Lifecycle Methods`, `Runtime Detection`?**
  _High betweenness centrality (0.176) - this node is a cross-community bridge._
- **Why does `introspect_via_github()` connect `GitHub Repo Introspection` to `GitHub Auth Wrapper`, `Command Detection`, `Package Manager Detection`, `Runtime Detection`, `System Package Detection`, `Language Detection`?**
  _High betweenness centrality (0.128) - this node is a cross-community bridge._
- **Why does `RepoIntrospection` connect `GitHub Repo Introspection` to `GitHub Auth Wrapper`, `Wire Protocol Models`, `Sandbox Reconciliation`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Are the 28 inferred relationships involving `MockSandboxProvider` (e.g. with `Beanie models, raw collection access, and Mongo lifecycle helpers.` and `ExecResult`) actually correct?**
  _`MockSandboxProvider` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `Beanie models, raw collection access, and Mongo lifecycle helpers.` (e.g. with `RepoIntrospection` and `GithubReauthRequired`) actually correct?**
  _`Beanie models, raw collection access, and Mongo lifecycle helpers.` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `SandboxManager` (e.g. with `Real Redis on the test DB (db 15). Flushes before AND after the test     so any` and `SandboxManager.reset — checkpoint fast path vs slow fallback.`) actually correct?**
  _`SandboxManager` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `Reconciler` (e.g. with `Real Redis on the test DB (db 15). Flushes before AND after the test     so any` and `Reconciliation service — slice 5b.`) actually correct?**
  _`Reconciler` has 27 INFERRED edges - model-reasoned connections that need verification._