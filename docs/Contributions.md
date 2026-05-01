# Contributions.md

Append-only log of **who did what** in this repo. Every human contributor and every AI coding agent appends one or more entries per session.

This file is for **attribution and history**. It is *not* the project state (that lives in [progress.md](progress.md)) and it is *not* design context (that lives in [Plan.md](Plan.md) and [agent_context.md](agent_context.md)).

---

## Entry format

```markdown
### YYYY-MM-DD — Author / agent identifier

- One-line summary of the change. Reference files with [path](path) where useful.
- Another change in the same session.
```

Rules:

- **One block per session.** A session = one continuous working stretch by one author. If you come back later, add a new dated block.
- **Author identifier**:
  - Humans: your name or GitHub handle (`Abhay`, `@abhay-dutt`).
  - AI agents: model + tool, e.g. `Claude Opus 4.7 via Claude Code`, `GPT-4 via Codex CLI`, `Copilot inline`.
- **One bullet per logical change.** A bullet is one short sentence; if you need a paragraph, write it in [progress.md](progress.md) under "Recent changes" and reference it from here.
- **Newest at the top.** Prepend new blocks; don't append.
- **No editing past entries.** This is append-only. If a past entry is wrong, add a new bullet in the current session correcting it.
- **No noise.** Don't log "ran tests" or "read the docs" — log only changes that touched the repo.

---

## Why this file exists

- Humans get credit; agents get auditability.
- Future contributors can see the texture of how the project evolved (cadence, who owned what) without grepping `git log`.
- AI agents picking up cold can read the last few entries to infer "what's the team's working style right now."

For *what changed structurally*, read [progress.md](progress.md). For *who and when*, read this file.

---

## Log

### 2026-05-02 — Claude Opus 4.7 via Claude Code (Plan.md — User Agent two-agent design)

- Added the **User Agent** (orchestrator-side, opt-in MITM between FE and Sandbox Agent) to [Plan.md](../docs/Plan.md): §8 `User` doc gains `user_agent_enabled` + `user_agent_mode`; §9 adds `PATCH /api/me/user-agent`; §10 web protocol gains `PromptEnhancedEvent` / `AskUserClarification` / `AgentAnsweredClarification` (with `override_window_ms`) / `AnswerClarification` / `OverrideAgentAnswer`; §14 rewritten as two-agent architecture with combined data-flow diagram, the `AskUserClarification` blocking-stdin protocol, User Agent tool list + system-prompt rules; §17 adds `USER_AGENT_DAILY_USD_CAP`; §18 splits old slice 6 into slice 6 (sandbox-agent passthrough) + slice 6b (User Agent layer); §19 adds risks #25–29 (visibility, override race, two-LLM coherence, LLM cost cap, clarification timeout); §20 snapshot updated.
- Three-position user control: **toggle** (off by default), **mode** when on (`user_answers_all` vs `agent_handles`), **always-on prompt enhancement** when toggle is on. Every User-Agent action is surfaced to the FE with override affordance — no silent decisions.
- No code yet. Implementation lands in slice 6 (passthrough) followed by slice 6b (User Agent layer with toggle UI + override flow).

### 2026-05-02 — Claude Opus 4.7 via Claude Code (Plan.md rewrite + Sprites docs converted to Markdown)

- Replaced the Sprites SDK PDFs in [docs/sprites/v0.0.1-rc43/](../docs/sprites/v0.0.1-rc43/) with [python.md](../docs/sprites/v0.0.1-rc43/python.md) + [http.md](../docs/sprites/v0.0.1-rc43/http.md). Deleted the `python/` and `http/` PDF subdirs. Updated all references — slice4.md, agent_context.md, progress.md, sprites.py module docstring, sandbox_provider/pyproject.toml — to point at the markdown files.
- Added the Sprites docs to discoverability surfaces: new row in [CLAUDE.md](../CLAUDE.md) "where things live" table; new line in [agent_context.md](../docs/agent_context.md) docs/ map.
- Rewrote [Plan.md](../docs/Plan.md) to match post-rc43 Sprites architecture: §8 sandbox doc (drop sprite_id/region/bridge_version, add provider_name/provider_handle/public_url), §10 transport (web↔orchestrator WS only; Sprites SDK is the sandbox leg), §13 lifecycle (Sprites status enum, auto-hibernation delegated, reset via checkpoints), §14 agent runtime (subprocess-per-run via Sprites Exec, no daemon), §15 git workflow (drop EnsureRepoCloned/RemoveRepo directive language), §17 env vars (drop GITHUB_APP_*, switch SPRITES_API_KEY → SPRITES_TOKEN/SANDBOX_PROVIDER/SPRITES_BASE_URL), §18 slice plan (5a web-WS-only, 5b adds clone+checkpoints, 8 mostly Sprites-handled, 9 collapses to surfacing the built-in URL), §19 risks (replaced bridge-WS gotchas with Sprites realities), §20 snapshot (slice 4 🟡 awaiting sign-off), §21 next steps.
- First substantive Plan.md edit since the 2026-05-01 transport-architecture rewrite. Permitted under explicit user direction per [AGENTS.md §3.3](../AGENTS.md).

### 2026-05-01 — Claude Opus 4.7 via Claude Code (slice 4 — Sprites SDK rewrite + cleanup)

- Rewrote slice 4 onto the `sprites-py` SDK (rc43 docs, rc37 on PyPI; `[tool.uv] prerelease = "allow"` in workspace root). Provider Protocol made opaque via `SandboxHandle(provider, payload)`; `SpritesProvider` and `MockSandboxProvider` are the only impls and are easily replaceable.
- Deleted [`apps/orchestrator/src/orchestrator/jobs/hibernate_idle.py`](../apps/orchestrator/src/orchestrator/jobs/hibernate_idle.py), [`apps/orchestrator/tests/test_hibernate_idle_job.py`](../apps/orchestrator/tests/test_hibernate_idle_job.py), [`python_packages/sandbox_provider/src/sandbox_provider/fly.py`](../python_packages/sandbox_provider/src/sandbox_provider/fly.py), [`python_packages/sandbox_provider/tests/test_fly.py`](../python_packages/sandbox_provider/tests/test_fly.py). Sprites manages idle hibernation; Fly impl was based on the wrong API.
- Dropped env vars: `FLY_REGION`, `SPRITE_CPU`, `SPRITE_RAM_MB`, `SPRITE_DISK_GB`, `BRIDGE_IMAGE`, `SANDBOX_IDLE_MINUTES`, `SPRITES_API_BASE`, `SPRITES_ORG`. Renamed `SPRITES_API_KEY` → `SPRITES_TOKEN`; `SANDBOX_PROVIDER=fly` → `sprites`. Updated `.env.example` to match.
- `Sandbox` Beanie doc: dropped `region`/`bridge_version`/`hibernated_at`/`sprite_id`; added `provider_name` (discriminator) + `provider_handle: dict[str, str]` (opaque payload) + `public_url`. Status enum: 7 states matching Sprites' `cold/warm/running` plus our app-level `provisioning/resetting/destroyed/failed`.
- `SandboxManager` lost the `hibernate` transition and `_resume` helper; `wake` now issues a no-op exec to force `cold→warm/running`. New `refresh_status` resyncs from the provider for the upcoming Refresh endpoint.
- Routes: dropped `POST .../hibernate`; added `POST .../refresh`. Web UI dropped the Pause button, added the public-URL link and Refresh button.
- Tests: 56 orchestrator + 17 provider all green; mock provider rotates handle-id per create so reset semantics match Sprites' real UUID rotation.

### 2026-05-01 — Claude Opus 4.7 via Claude Code (slice 4 — sandbox provisioning shipped)

- Filled in [python_packages/sandbox_provider/](../python_packages/sandbox_provider/) with `SandboxProvider` Protocol, `SpawnResult`, `SpritesError(retriable)`, `FlySpritesProvider` (httpx wrapper over Fly Machines API), `MockSandboxProvider` (in-memory). Persistent volume at `/work` baked into `spawn`. 15 unit tests via `httpx.MockTransport`.
- Added `Sandbox` Beanie doc with the 8-state machine + `reset_count` / `last_reset_at`. Registered in `_DOCUMENT_MODELS`. Wire shape `SandboxResponse` in `shared_models`.
- `SandboxManager` at [../apps/orchestrator/src/orchestrator/services/sandbox_manager.py](../apps/orchestrator/src/orchestrator/services/sandbox_manager.py) owns the matrix; `IllegalSandboxTransitionError` → HTTP 409. Provider failures mark the doc `failed` rather than crash the request. `reset` is sequential `provider.destroy → provider.spawn` on the same `Sandbox._id`.
- 5 REST endpoints at [../apps/orchestrator/src/orchestrator/routes/sandbox.py](../apps/orchestrator/src/orchestrator/routes/sandbox.py) (list, get-or-create, wake, hibernate, reset, destroy). All path-parameterized.
- Explicit provider selection at [../apps/orchestrator/src/orchestrator/lib/provider_factory.py](../apps/orchestrator/src/orchestrator/lib/provider_factory.py) — `SANDBOX_PROVIDER=fly` + empty `SPRITES_API_KEY` aborts startup; `mock` emits a loud warning. **No silent fallback.**
- Redis client singleton + idle-hibernation job (2 min tick, `spawned_at` fallback when `last_active_at` is null). Cancel-clean.
- Web: new [SandboxPanel](../apps/web/src/components/SandboxPanel.tsx) above the repos section. Distinct **Reset** + **Delete sandbox** buttons, both with confirmation dialogs. Pause is non-destructive, no confirmation. Polling at 2s for transient states.
- New env vars wired through `Settings` and `.env.example`. API types regenerated.
- Tests: 61 orchestrator + 15 provider, all green. State-machine matrix parameterized; two-user isolation verified.

### 2026-05-01 — Claude Opus 4.7 via Claude Code (slice 4 brief authored)

- Authored [slice/slice4.md](slice/slice4.md) — sandbox provisioning, scope-narrow ("the box exists"). Six open decisions resolved inline (Sprites SDK behind a wrapper, `iad` default region, no salt suffix needed, 20 GB disk cap, three Redis keys per active sandbox, lazy `Sandbox` doc creation).
- Brief covers: `FlySpritesProvider` + `MockSandboxProvider` behind a single Protocol; `Sandbox` Beanie doc with 7-state machine; `services/sandbox_manager.py` enforcing single-running-per-user at the routing layer (not the index); five REST endpoints all path-parameterized; idle-hibernation job using `spawned_at` fallback so it works without slice-5a heartbeat data; Redis hot cache keys defined now so slice 5a's sticky routing has a settled schema; dashboard "Sandbox" panel with status polling.
- Hard rules: no WS, no clone, no `Repo.sandbox_id` binding, no DELETE for destroy. Out-of-scope list explicitly defers WS + bridge runtime to 5a, clone + reconciliation to 5b.
- Acceptance includes a two-user isolation check and both mock-mode + real-Sprites-mode end-to-end flows.

### 2026-05-01 — Claude Opus 4.7 via Claude Code (Plan.md rewrite — transport architecture + slice resplit)

- Rewrote [Plan.md §10](Plan.md) end-to-end with explicit user authorization. New architecture: WS for both legs, four logical channels on separate WS connections (control+events, PTY, file ops, HTTP preview), sticky-by-sandbox routing via Fly `fly-replay` with Redis pub/sub fallback, per-instance soft cap of 5000 WS connections with hot-shedding. gRPC considered and rejected; reasoning recorded in §10.1.
- Added §10.8 Reliability subsection covering disconnects: 30s/90s heartbeat with `Ping`/`Pong` nonces, `seq`-replay via `Resume{after_seq}`, idempotent directives with `directive_id` dedup, jittered exponential-backoff reconnect on bridge and web, explicit backpressure caps and drop policies, fail-fast on auth, fail-soft on schema mismatch.
- Resplit [Plan.md §18](Plan.md): slice 4 narrowed to provisioning-only (no WS, no clone); slice 5 split into 5a (control+events WS + bridge runtime + sticky routing) and 5b (clone + reconciliation + disk-cap eviction); new slice 8 (PTY + file ops) and slice 9 (HTTP preview proxy); old slice 8 (event-log S3) renumbered to 10.
- Updated [Plan.md §19](Plan.md) with 8 new transport-design risks (#16–23) and retagged #10 / #15 to the new slice numbers. Updated §20 snapshot.
- First edit to Plan.md since slice 0; permitted by explicit user direction per [AGENTS.md §3.3](../AGENTS.md).

### 2026-05-01 — Claude Opus 4.7 via Claude Code (slice 3 sign-off + CORS fix)

- **User signed off slice 3.** [slice/slice3.md](slice/slice3.md) is frozen per AGENTS.md §3.2/§5; corrections move to [progress.md](progress.md). Slice status table flipped 3 → ✅ shipped, 4 → ⬜ awaiting brief.
- **CORS slice-3 correction**: added `PATCH` (and `PUT`) to the `CORSMiddleware` `allow_methods` allowlist in [../apps/orchestrator/src/orchestrator/app.py](../apps/orchestrator/src/orchestrator/app.py). The new `PATCH /api/repos/{id}/introspection` failed preflight on the web client without it — caught only after the user tested Save in the override panel. Recorded as a slice-3 post-freeze correction in progress.md.

### 2026-05-01 — Claude Opus 4.7 via Claude Code (slice 3 — scope amendment: dev_command + overrides)

- Added `dev_command` field to `RepoIntrospection`; detected per-pm in [../python_packages/repo_introspection/src/repo_introspection/commands.py](../python_packages/repo_introspection/src/repo_introspection/commands.py) (JS: `scripts.dev` → `scripts.start`; cargo run; go run; gradle run).
- Added `IntrospectionOverrides` ([../python_packages/shared_models/src/shared_models/introspection.py](../python_packages/shared_models/src/shared_models/introspection.py)) and split `Repo` storage into `introspection_detected` + `introspection_overrides`. `ConnectedRepo` wire shape now exposes both raw fields plus a merged-effective `introspection` field.
- New `PATCH /api/repos/{repo_id}/introspection` endpoint in [../apps/orchestrator/src/orchestrator/routes/repos.py](../apps/orchestrator/src/orchestrator/routes/repos.py) (full replacement; send `{}` to clear; re-introspect preserves overrides — only `detected` refreshes).
- UI: 5th pill for dev_command, "(overridden)" rendered as black-filled pill with `•`, new "Edit fields" panel ([../apps/web/src/routes/_authed/dashboard.tsx](../apps/web/src/routes/_authed/dashboard.tsx)) with placeholder = detected, helper text, Clear-all/Cancel/Save buttons. New `updateIntrospectionOverrides` mutation in [../apps/web/src/lib/repos.ts](../apps/web/src/lib/repos.ts).
- Brief updated in-flight (per AGENTS.md §3.2) — added §0 *Scope amendment*. New tests: 5 override-endpoint cases in `test_repos.py` (set/clear, no-detection, 422 on unknown pm, reintrospect-preserves-overrides) and 4 dev_command cases in `test_commands.py`. Suite green: orchestrator 35, introspection 50.

### 2026-05-01 — Claude Opus 4.7 via Claude Code (slice 3 — repo introspection)

- Authored [slice/slice3.md](slice/slice3.md): GitHub-API-only detection (Trees + Contents), inline-on-connect best-effort, explicit `POST /api/repos/{id}/reintrospect`. Adapter pattern in [../python_packages/repo_introspection/src/repo_introspection/github_source.py](../python_packages/repo_introspection/src/repo_introspection/github_source.py) so slice 4 can swap to a filesystem source without rewriting detectors.
- Implemented `repo_introspection/` package: `language.py`, `package_manager.py`, `commands.py`, `orchestrate.py`, `github_source.py`. `RepoIntrospection` shared model + `PackageManager` literal extended to `bun`/`maven`/`gradle`/`other` (user-edited during draft).
- Wired into [../apps/orchestrator/src/orchestrator/routes/repos.py](../apps/orchestrator/src/orchestrator/routes/repos.py): `_introspect_into` runs on connect (best-effort, 401 propagates as `github_reauth_required`); new reintrospect endpoint reuses the same helper.
- Web UI in [../apps/web/src/routes/_authed/dashboard.tsx](../apps/web/src/routes/_authed/dashboard.tsx): four-pill row (`null` → muted `—`) + Re-introspect button. New `reintrospectRepo` mutation in [../apps/web/src/lib/repos.ts](../apps/web/src/lib/repos.ts).
- 46 unit tests in [../python_packages/repo_introspection/tests/](../python_packages/repo_introspection/tests/), 8 new integration tests in [../apps/orchestrator/tests/test_repos.py](../apps/orchestrator/tests/test_repos.py). `pnpm typecheck && lint && test && build` all green.
- Regenerated [../packages/api-types/generated/schema.d.ts](../packages/api-types/generated/schema.d.ts) by piping `app.openapi()` through `openapi-typescript` (no running orchestrator needed).

### 2026-05-01 — Claude Opus 4.7 via Claude Code (slice 2 sign-off + collection registry)

- **User signed off slice 2.** [slice/slice2.md](slice/slice2.md) is now frozen per AGENTS.md §3.2/§5; corrections move to [progress.md](progress.md). Slice status table flipped 2 → ✅ shipped, 3 → ⬜ awaiting brief.
- **Centralized collection-name registry** [db/collections.py](../python_packages/db/src/db/collections.py): single `Collections` class with `USERS` / `SESSIONS` / `REPOS` constants (plus reserved `SANDBOXES` / `TASKS` / `AGENT_RUNS` / `AGENT_EVENTS` for slice 4+) and an `ALL` tuple. Imports nothing from models — no circular-import risk.
- All Beanie models now read `Settings.name = Collections.X` instead of literal strings ([user.py](../python_packages/db/src/db/models/user.py), [session.py](../python_packages/db/src/db/models/session.py), [repo.py](../python_packages/db/src/db/models/repo.py)). `Mongo` typed accessors (`mongo.users`, `mongo.sessions`, `mongo.repos`) use `Collections.X` too. Added `mongo.drop_all_collections()` and `mongo.collection(name)` escape hatch. Re-exported `Collections` + `ALL_COLLECTIONS` from `db/__init__.py`.
- Test conftest reduced to `connect → drop_all_collections → reconnect` — no more hand-listed model tuples drifting out of sync. 22 pytest tests still green; pyright + ruff + tsc + eslint all clean.

### 2026-05-01 — Claude Opus 4.7 via Claude Code (motor → pymongo migration + Mongo singleton)

- **Driver swap.** Beanie 1.30 (motor-based) → Beanie 2.1 (pymongo's new `AsyncMongoClient`). Motor uninstalled. Pinned `beanie>=2.0,<3.0`, `pymongo>=4.11,<5.0` in [python_packages/db/pyproject.toml](../python_packages/db/pyproject.toml) and the orchestrator's pyproject.
- **New singleton class** [db/mongo.py](../python_packages/db/src/db/mongo.py): `Mongo` exposes `client`, `db`, typed collection accessors (`mongo.users`, `mongo.sessions`, `mongo.repos`), `connect(uri, *, database=None, register_models=True)`, `disconnect()`, and `ping()`. Enforces single-process singleton; `connect` is idempotent if called twice with the same DB so the FastAPI lifespan and the test fixture can both call it without tripping over each other. Backwards-compat thin wrappers `connect()` / `disconnect()` re-exported.
- Deleted [db/connect.py](../python_packages/db/src/db/connect.py) — superseded.
- **Beanie document_models registration** centralized in [db/mongo.py](../python_packages/db/src/db/mongo.py)'s `_DOCUMENT_MODELS` list — adding a new `Document` class is a one-line edit there, no longer scattered.
- **`/health` upgraded** to a real readiness probe: returns `{"status":"ok","mongo":true}` on success, **503** with `{"status":"degraded","mongo":false}` if Mongo is unreachable. Load balancers will drop the instance out of rotation cleanly.
- **Test fixture** ([apps/orchestrator/tests/conftest.py](../apps/orchestrator/tests/conftest.py)) now uses the singleton: connects, drops collections, re-connects (so Beanie rebuilds indexes against empty collections), runs the test through `httpx.ASGITransport`, then disconnects. Catches the case where stale unique indexes from a prior schema would block valid writes.
- All 22 pytest tests green; pyright strict clean; ruff clean; orchestrator boots end-to-end and `/health` returns the new readiness payload.

### 2026-05-01 — Claude Opus 4.7 via Claude Code (per-sandbox repo binding + global-unique bug fix)

- User clarified: "different sandboxes can have different repos" — i.e. repo connection is per-sandbox and the same repo can be in multiple sandboxes. Audited and fixed the schema accordingly.
- **Bug fix in shipped slice 2:** [Repo](../python_packages/db/src/db/models/repo.py) had `github_repo_id: Annotated[int, Indexed(unique=True)]` — globally unique. Two different users could not connect the same GitHub repo. Changed to a compound unique index on `(sandbox_id, user_id, github_repo_id)` via `IndexModel`. Also added `sandbox_id: PydanticObjectId | None = None` to the model so slice 4 can populate it without a schema migration.
- [Repos route](../apps/orchestrator/src/orchestrator/routes/repos.py) duplicate check rescoped from `Repo.github_repo_id == X` to `(user_id, github_repo_id)`. Slice 4 will further scope to sandbox.
- [Test conftest](../apps/orchestrator/tests/conftest.py) now drops collections (not just `delete_many`) so Beanie rebuilds indexes cleanly each test run — without this, the stale `github_repo_id_1` unique index from the old schema kept blocking writes that the new schema allows. **Dev Mongo (not test) still has the old index** — followup: drop manually with `db.repos.dropIndex("github_repo_id_1")` once.
- New regression test [test_connect_allows_same_repo_for_different_users](../apps/orchestrator/tests/test_repos.py) exercises the cross-user case explicitly. 22 pytest tests total, all green.
- **Plan.md §8 Repo**: dropped global unique on `github_repo_id`, added compound `(sandbox_id, user_id, github_repo_id)` unique index, documented the rationale.
- **Plan.md §9 Repos API**: added per-sandbox connect endpoint `POST /api/sandboxes/{sandbox_id}/repos/connect` (slice 4) alongside the slice-2 flat `POST /api/repos/connect`. `GET /api/repos` will accept `?sandbox_id=` filter in slice 4. Disconnect copy now notes that other sandbox-bindings of the same repo are untouched.
- API types regenerated.

### 2026-05-01 — Claude Opus 4.7 via Claude Code (multi-sandbox forward-compat audit + Plan.md fixes)

- Audit triggered by user adding a §4 forward-compat note ("multiple sandboxes per user, future"). Audited shipped slices 0–2 + the planned slice 4–6 schemas/APIs for hard one-sandbox-per-user assumptions. **Shipped code is clean** — no sandbox refs outside two UI strings. Six Plan.md spots needed surgery to make slice 4+ land multi-sandbox-ready without a rewrite.
- **§8 `Sandbox`**: dropped `Indexed(unique=True)` on `user_id` (now plain `Indexed()`); added optional `name: str | None = None` for future per-sandbox labels. v1 enforces "one per user" at the orchestrator routing layer, NOT at the index.
- **§8 `Repo`**: added `sandbox_id: PydanticObjectId | None` (set by slice 4 when bound; null in slice 2). Forward-compat per the §4 note about repo-connect flow gaining sandbox selection.
- **§8 `Task`**: added `sandbox_id: PydanticObjectId` (required). Resolves an inconsistency where the §4 note claimed "sandbox_id already on Task" but the model only had `user_id` + `repo_id`.
- **§9 Sandbox API**: renamed all routes from `/api/sandbox/*` (singleton) → `/api/sandboxes/{sandbox_id}/*` (parameterized) plus `GET /api/sandboxes` (list — length-0/1 in v1) and `POST /api/sandboxes` (create — 409 if user already has one in v1). UI resolves the singleton id transparently; multi-sandbox future just adds a picker.
- **§13 Sprite naming**: `vibe-sbx-{user_id}` → `vibe-sbx-{sandbox_id}` (collision-free with N sandboxes per user).
- **§13–14 reconciliation**: clarified everywhere as **per-sandbox** (`Repo.sandbox_id == this.sandbox_id`), never per-user. Updated slice-4 brief in §18 + acceptance test in §19 (four-quadrant matrix is per-sandbox).
- **§18 slice 4 brief** rewritten to reflect the new schema + API shape; acceptance test calls the parameterized endpoints.
- **No shipped-code changes** — adding `sandbox_id` to `Repo` today would be dead-field scaffolding (no `Sandbox` model exists in slice 2). Per AGENTS.md §2.3 (no future-proofing), defer until slice 4 binds it. `AgentRun.sandbox_id` was already correct; WS endpoint `/ws/bridge/sandboxes/{sandbox_id}` was already parameterized.

### 2026-05-01 — Claude Opus 4.7 via Claude Code (slice 2 polish — pagination, server-side search, scope toggle, manage-orgs)

- **Fix: `/repos/connect` was unreachable.** Parent `_authed/repos.tsx` was a TanStack Router parent route to `_authed/repos/connect.tsx` but didn't render `<Outlet />`, so clicking "Browse repositories" navigated to `/repos/connect` while the parent's UI stayed put. Moved `repos.tsx` → [_authed/repos/index.tsx](../apps/web/src/routes/_authed/repos/index.tsx) so they're siblings; route id changed from `/_authed/repos` → `/_authed/repos/`.
- **Server-side pagination on `/api/repos/available`** — added `page`, `per_page` (1–100, default 30) query params; backend now hits a single GitHub page directly instead of aggregating all pages. Response is now an envelope `AvailableReposPage { repos, page, per_page, has_more }` with `is_connected: bool` per repo so already-connected ones can be marked instead of filtered out. Returned repos are sorted `pushed:desc`.
- **Server-side search via `/search/repositories`** — added `q` query param; backend switches from `/user/repos` to GitHub's `/search/repositories` when present. Web FE replaced the client-side current-page filter with a debounced (350ms) search box that hits the backend and resets to page 1 on query change.
- **Search-scope toggle** — `/search/repositories` doesn't have a "my access" filter, so by default the backend appends `user:<me>` + `org:<o>` qualifiers (fetched from `/user/orgs`) to scope to the user's repos and orgs. Added `scope_mine: bool = True` query param so the FE can opt out — checkbox under the search input ("Limit to my repos and orgs"). Always visible regardless of search state.
- **"Manage GitHub org access" button** in the profile panel + new orchestrator endpoint `GET /api/auth/github/manage` that 302s to `https://github.com/settings/connections/applications/<client_id>`. Solves the "I want to authorize an org I previously denied" case — GitHub OAuth has no `prompt=consent` so re-running OAuth alone can't grant new org access; the user has to manage it on GitHub directly. New `manageGithubAccessUrl()` helper in `apps/web/src/lib/auth.ts`.
- **"Reconnect GitHub" button** also visible in the profile panel (re-runs `startGithubLogin()` to refresh the token).
- **Scroll-to-top on page change** — `useRef` + `useEffect` watching `page` calls `scrollIntoView({behavior:'smooth'})` so users land back at the page header when paginating.
- **Pagination test added** — `test_available_returns_paginated_with_is_connected` exercises page/per_page query params and verifies `is_connected` flag mapping. Total: 21 pytest tests, all green.
- **API types regenerated** to reflect `AvailableReposPage`, `is_connected`, `q`, `scope_mine`, and `/api/auth/github/manage`.
- **Dashboard redesign** ([apps/web/src/routes/_authed/dashboard.tsx](../apps/web/src/routes/_authed/dashboard.tsx)) — 2-column layout: left collapsible profile panel (avatar, username, email, account fields, manage-orgs link, Reconnect, Sign out — open state persisted via `localStorage`); center area shows connected repos with disconnect actions and a "Browse repositories" CTA, or a Reconnect card when `needs_github_reauth`. Adheres to AGENTS.md §2.8 light theme.

### 2026-05-01 — Claude Opus 4.7 via Claude Code (slice 2 redesign — OAuth `repo` scope)

- **Slice 2 architecture flipped** from "GitHub App + installation tokens + smee webhook" to "OAuth App with `repo` scope + persisted user access token + 401-driven re-auth flow." User-driven decision; full rewrite.
- **Plan.md updated** ([../docs/Plan.md](../docs/Plan.md)): §3 capabilities bullet, §4 architecture diagram, §8 (removed `github_installations` collection, simplified `Repo` to drop `installation_id`, added auth note), §9 (removed `/api/github/*` table, simplified Repos table), §11 (scope expanded to `read:user user:email repo`, added token-persistence + 401-clear behavior), §12 (replaced GitHub App walkthrough with OAuth-`repo`-scope rationale + "alternative considered, not chosen" pointer to git history), §15 push command (`install_token` → `user_token` repo-wide), §18 slice 2 rewritten.
- **slice2.md rewritten** ([slice/slice2.md](slice/slice2.md)) with the new scope: token persistence on `User.github_access_token`, `GithubReauthRequired` exception, `_on_reauth` flow, `needs_github_reauth` flag on `UserResponse`, "Reconnect GitHub" UI affordance.
- **Code shipped (20/20 pytest tests green; pyright strict + ruff + tsc + eslint all clean):**
  - **Removed:** `db/models/github_installation.py`, `python_packages/github_integration/{auth,webhook,client}.py` (App JWT + token cache + HMAC verifier), `apps/orchestrator/src/orchestrator/lib/github.py` (App client singleton), `apps/orchestrator/src/orchestrator/routes/github.py` (install-url, installations, refresh, webhook), `tests/test_github_routes.py`, `tests/test_webhook.py`, `Repo.installation_id`, `GITHUB_APP_*` Settings + `.env.example` entries, `pyjwt` from `github_integration` deps, `smee-client` root devDep, `pnpm dev:webhook` script.
  - **Added:** `User.github_access_token` field; new [github_integration](../python_packages/github_integration/src/github_integration/) modules — `exceptions.py` (`GithubReauthRequired`), `client.py` (`user_client(token)` + `call_with_reauth(fn)` wrapping 401→exception); rewritten [routes/repos.py](../apps/orchestrator/src/orchestrator/routes/repos.py) using `gh.rest.repos.async_list_for_authenticated_user` + `async_get(owner,repo)` with both `GithubReauthRequired` and bare `RequestFailed` 401 handling that clears the token and returns `403 github_reauth_required`; `needs_github_reauth: bool` on [UserResponse](../python_packages/shared_models/src/shared_models/user.py) computed at the API boundary in `/api/me` and `/api/auth/session` so the raw token never leaves the server.
  - **Slice 1 OAuth scope expanded** to `read:user user:email repo` and the access token is persisted on the `User` doc in the [callback handler](../apps/orchestrator/src/orchestrator/routes/auth.py).
  - **Web rewritten:** `lib/queries.ts` returns a `{reauth: true}` sentinel on 403 instead of throwing; `lib/repos.ts` exports a typed `GithubReauthRequiredError`; [/_authed/repos.tsx](../apps/web/src/routes/_authed/repos.tsx) and [/_authed/repos/connect.tsx](../apps/web/src/routes/_authed/repos/connect.tsx) drop the entire installations section and render a Reconnect card on the reauth sentinel; [dashboard.tsx](../apps/web/src/routes/_authed/dashboard.tsx) shows an inline reconnect banner above the profile card when `needs_github_reauth` is true.
  - **Tests:** new [test_repos.py](../apps/orchestrator/tests/test_repos.py) covers token-missing 403, RequestFailed 401 → token cleared + 403 `github_reauth_required`, happy-path connect, duplicate 409, id-mismatch 400, disconnect 204/404. Extended [test_auth.py](../apps/orchestrator/tests/test_auth.py) to assert token persistence on callback and that `/api/me` reports `needs_github_reauth` correctly.
  - **API types regenerated** against live orchestrator on port 3099; `schema.d.ts` no longer contains any `/api/github/*` paths and `UserResponse` now exposes `needs_github_reauth: boolean`.
- **README rewritten:** removed "Setting up the GitHub App" + "Webhook delivery in local dev" + "Connecting repositories (App flow)" sections; replaced with single combined "Setting up GitHub OAuth (local dev)" (scope `read:user user:email repo`), an updated "Connecting repositories" section, and a "When your token expires or is revoked" subsection explaining the Reconnect flow + org SSO friction note.
- **progress.md punch list rewritten** for slice 2 verification (typecheck/lint/test ✅, regen ✅, manual OAuth scope-update + token-revocation walk ⬜).

### 2026-05-01 — Claude Opus 4.7 via Claude Code (slice 2 build)

- **Slice 2 shipped end-to-end.** Authored [slice/slice2.md](slice/slice2.md) (GitHub App + repo connection brief, scoped to logical state — no clone, no introspection, no sandbox). Built against it:
  - Filled [../python_packages/github_integration/](../python_packages/github_integration/): App JWT minting (PyJWT RS256), `InstallationTokenCache` with per-id `asyncio.Lock`, webhook signature verifier, githubkit `app_client` / `installation_client` factories.
  - Added Beanie models [GithubInstallation](../python_packages/db/src/db/models/github_installation.py) + [Repo](../python_packages/db/src/db/models/repo.py); registered both in `init_beanie`.
  - Added Pydantic API models in [shared_models/github.py](../python_packages/shared_models/src/shared_models/github.py): `InstallationResponse`, `AvailableRepo`, `ConnectedRepo`, `InstallUrlResponse`, `ConnectRepoRequest`, `RefreshInstallationsRequest`.
  - Extended [orchestrator Settings](../apps/orchestrator/src/orchestrator/lib/env.py) with `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_WEBHOOK_SECRET`, `GITHUB_APP_SLUG` + `\n` PEM unescape validator. Updated [.env.example](../.env.example) and [conftest.py](../apps/orchestrator/tests/conftest.py).
  - Implemented orchestrator routes [github.py](../apps/orchestrator/src/orchestrator/routes/github.py) (install-url, installations, installations/refresh with state-cookie CSRF, webhook with HMAC verification + Pydantic-validated `installation` payloads, cascading delete on `installation.deleted`) and [repos.py](../apps/orchestrator/src/orchestrator/routes/repos.py) (available, list, connect with `repos.async_get` access verification, disconnect). Mounted both in [app.py](../apps/orchestrator/src/orchestrator/app.py).
  - Process-singleton [lib/github.py](../apps/orchestrator/src/orchestrator/lib/github.py) wires the App client + token cache with githubkit's `apps.async_create_installation_access_token` minter.
  - Added `smee-client` as root devDep + `pnpm dev:webhook` script.
  - Web: `installationsQueryOptions` / `availableReposQueryOptions` / `connectedReposQueryOptions` in [queries.ts](../apps/web/src/lib/queries.ts), mutations in new [lib/repos.ts](../apps/web/src/lib/repos.ts). New routes [_authed/repos.tsx](../apps/web/src/routes/_authed/repos.tsx) (installations + connected list, post-install refresh fallback) and [_authed/repos/connect.tsx](../apps/web/src/routes/_authed/repos/connect.tsx) (filterable available-repo picker). Added "Connect repositories" CTA to [dashboard.tsx](../apps/web/src/routes/_authed/dashboard.tsx).
  - 19 new tests across [test_github_routes.py](../apps/orchestrator/tests/test_github_routes.py), [test_webhook.py](../apps/orchestrator/tests/test_webhook.py), [test_repos.py](../apps/orchestrator/tests/test_repos.py). All 28 pytest tests green; pyright strict clean; ruff clean; openapi-typescript regen against live orchestrator produced real types for all 8 new endpoints.
  - README sections added: "Setting up the GitHub App (local dev)", "Webhook delivery in local dev", "Connecting repositories".
- Earlier same session: redesigned [../apps/web/src/routes/login.tsx](../apps/web/src/routes/login.tsx) (centered card, GitHub icon, loading state, scope reassurance) and [dashboard.tsx](../apps/web/src/routes/_authed/dashboard.tsx) (profile view: avatar, @username link, email, member-since, last-signed-in, IDs).

### 2026-05-01 — Claude Opus 4.7 via Claude Code

- **Removed Account section from sidebar** — dropped Member-since / Last-signed-in / GitHub user ID / Account ID per user. Also removed the now-unused `Field`, `formatDate`, `formatRelative` helpers (no dead code).
- **Dashboard sidebar polish v2** — restored brand visibility when collapsed (just the `BrandMark` square, no text) in a sticky header strip; reorganized expanded panel into proper sidebar regions: header (brand + close-X), scrollable nav body with `Profile` and `Account` section labels and tighter spacing, and a footer Sign out button styled as a subtle text-button (no card-within-card chrome). Smaller avatar (h-10) and section dividers via `border-b border-gray-200` make it feel native rather than "card pasted into a panel".
- **Dashboard UI polish** — fixed three issues called out by the user: (1) removed the page-level header that was creating an L-shape with the sidebar; sidebar now runs full-height from the top; (2) GitHub icon now appears **only when the panel is collapsed** (functions as the expand-toggle); when expanded, the brand `vibe-platform` lockup sits at the top of the panel with a small close-X to collapse — no more redundant GitHub icon; (3) the brand logo no longer renders in the collapsed state, so the tiny black-square placeholder isn't visible there. Added inline `CloseIcon` SVG (no new deps). Web typecheck + lint clean.
- **Dashboard UI reshape** ([../apps/web/src/routes/_authed/dashboard.tsx](../apps/web/src/routes/_authed/dashboard.tsx)): 2-column layout — left collapsible profile panel (GitHub icon trigger, persisted in localStorage, contains avatar/username/email/account fields/Sign out), center repos list with Disconnect + "Browse repositories" CTA, Reconnect card when `needs_github_reauth`. Made [../apps/web/src/routes/_authed/repos.tsx](../apps/web/src/routes/_authed/repos.tsx) a redirect to `/dashboard` since dashboard absorbs its role; `/repos/connect` (the picker) stays. Reused existing `meQueryOptions` / `connectedReposQueryOptions` / `disconnectRepo` per the reuse-before-write rule. Light-theme adherent (AGENTS.md §2.8). Web typecheck + lint clean.
- **Surfaced Plan.md ↔ slice2.md deviation** to user (per AGENTS.md §3.5): Plan.md §18 + §8 still describe slice 2 as GitHub App with installations/webhooks/smee, but shipped code chose OAuth `repo` scope expansion. User authorized starting slice 2 implementation work; Plan.md update awaits explicit approval — not silently rewritten.
- Expanded [../AGENTS.md](../AGENTS.md) §2.7 with a Step 0 *install-check* rule (ask user before `pip install graphifyy`, fall back to grep/Read if declined) and a second usage table covering `/graphify add <url>`, `/graphify --wiki`, `/graphify --mcp`, `graphify hook install`, `--watch`, `--cluster-only`, `--mode deep`, `--directed`, and the export modes (`--svg`, `--graphml`, `--neo4j`). Mirrored both additions in [agent_context.md](agent_context.md), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md).
- Added [../AGENTS.md](../AGENTS.md) **§2.7 Use graphify-out first** — codified the "consult the pre-built graph for relationship questions before grepping" workflow with a usage table (`/graphify query|path|explain`, `GRAPH_REPORT.md`), staleness handling (`--update` not full rebuild), and "never load `graph.json` directly" rule. Mirrored in [agent_context.md](agent_context.md), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md).
- Added [../AGENTS.md](../AGENTS.md) **§2.8 Frontend theme** — light mode only, no `dark:` variants, white / `bg-gray-50` / `bg-white/80 backdrop-blur` surfaces, black text/CTAs, no saturated colors on backgrounds, no gradients, no custom hex in component code. Mirrored as one-liners in agent_context, Copilot, Antigravity. Added pointers in CLAUDE.md "where things live" table.
- Added **deviation protocol** as [../AGENTS.md](../AGENTS.md) §3.5: when work contradicts Plan.md, the active slice brief, or any arch doc, the agent must *stop, surface the divergence, and wait for direction* before editing arch docs or building past the conflict. Mirrored as a bullet in [agent_context.md](agent_context.md), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), and [../.antigravity/instructions.md](../.antigravity/instructions.md).
- Swept remaining stale "CLAUDE.md as stack-rules home" references in [../AGENTS.md](../AGENTS.md) (§3.3 description and §6 per-tool list), [agent_context.md](agent_context.md) (Stack constraints heading + banned-deps cross-ref), and [engineering.md](engineering.md) (doc-update policy table description). All now correctly identify CLAUDE.md as a thin entry-point pointer and route stack questions to AGENTS.md §2.6 or Plan.md §5.
- Fixed stale "Stack constraints are in `CLAUDE.md`" pointers in [../.github/copilot-instructions.md](../.github/copilot-instructions.md) and [../.antigravity/instructions.md](../.antigravity/instructions.md). Both now point at [../AGENTS.md](../AGENTS.md) §2.6 for stack/package-manager/banned-deps rules and [Plan.md §5](Plan.md) for stack rationale. The "see CLAUDE.md for the banned list" reference in copilot-instructions.md was also corrected to point at AGENTS.md §2.6.
- Restored the verbatim "Stack — locked in, do not change without explicit approval" app-tier list (Backend / Bridge / Frontend / Tooling) at the top of [../AGENTS.md](../AGENTS.md) §2.6. The earlier trim left only the concern-by-concern Plan.md tables; the original four-bullet, app-tier framing wasn't preserved anywhere despite being the policy-shaped form of the rule. Now §2.6 leads with that list, followed by package managers, banned deps, and the add-a-dep checklist.
- Fixed stale header in [../AGENTS.md](../AGENTS.md) that still said "Stack rules live in CLAUDE.md" after the trim. Now correctly states stack inventory lives in [Plan.md §5](Plan.md) and the rule version lives in AGENTS.md §2.6.
- Trimmed [../CLAUDE.md](../CLAUDE.md) to a thin pointer file: read-order, "where things live" table, what-to-update-when-you-ship checklist. Moved banned dependencies + package-manager rules into [../AGENTS.md](../AGENTS.md) §2.6 ("Dependency & tooling constraints") so they live with the other agent rules. Stack inventory stays in [Plan.md §5](Plan.md); cross-refs updated.
- Trimmed [../CLAUDE.md](../CLAUDE.md) to stack rules only — moved "Source-of-truth bridges" and "Where things go" out (they were arch, not stack) and replaced with a pointer block to [Plan.md](Plan.md), [../AGENTS.md](../AGENTS.md), [agent_context.md](agent_context.md), [progress.md](progress.md), and [engineering.md](engineering.md).
- Established slice-brief authoring workflow in [../AGENTS.md](../AGENTS.md) §3.2 and §5.2: agents *create* `docs/slice/slice{n}.md` when starting a new slice, *edit* it while the slice is active, and treat it as *frozen* once the user signs off. Mirrored a one-liner in [agent_context.md](agent_context.md).
- Renamed `docs/CONTRIBUTING.md` → [engineering.md](engineering.md) since the file documented engineering change-flow, not contribution process. Swept references across [../AGENTS.md](../AGENTS.md), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md), [agent_context.md](agent_context.md), [progress.md](progress.md), [TESTING.md](TESTING.md), [Plan.md](Plan.md).
- Created this file ([Contributions.md](Contributions.md)) and wired it into the always-update list in AGENTS.md, agent_context.md, progress.md, copilot-instructions.md, antigravity instructions.md, and engineering.md.
- Established agent-rules architecture: created [../AGENTS.md](../AGENTS.md) (canonical), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md), [agent_context.md](agent_context.md), [progress.md](progress.md). Pointed [../CLAUDE.md](../CLAUDE.md) at AGENTS.md.
- Updated [Plan.md](Plan.md) sandbox model to one persistent Sprite per user holding all of that user's connected repos under `/work/<full_name>/`. Affected §3, §4, §8 (added `sandboxes` collection), §9 (`/api/sandbox/*`), §10 (WS endpoint moved to `/ws/bridge/sandboxes/{sandbox_id}`), §13–§15, §18, §19.
- Moved most documentation into `docs/`. Rewrote internal links in [Plan.md](Plan.md) for the new location.
- Fixed Vite environment loading: [../apps/web/vite.config.ts](../apps/web/vite.config.ts) now sets `envDir: '../..'` so the repo-root `.env` is read (was causing a blank page because [../apps/web/src/lib/api.ts](../apps/web/src/lib/api.ts) threw at module load when `import.meta.env.VITE_ORCHESTRATOR_BASE_URL` was undefined).
