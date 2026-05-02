# agent_context.md

Distilled context for any AI coding agent picking up work in this repo. Read this before reading any other doc.

> Sibling docs: [progress.md](progress.md) (active state) · [Contributions.md](Contributions.md) (who-did-what log) · [engineering.md](engineering.md) (change flow) · [Plan.md](Plan.md) (full design — heavy, only if needed) · [../AGENTS.md](../AGENTS.md) (rules — incl. §2.6 stack, §3.5 deviation protocol) · [../CLAUDE.md](../CLAUDE.md) (Claude Code entry-point pointer).

---

## TL;DR

- **Product**: a tool where a user connects GitHub repos, files chat-driven coding tasks, and a Claude Agent SDK process running in a Sprites sandbox makes the changes and opens a PR.
- **Sandbox model**: **one persistent Sprite per user**, holding *all* of that user's connected repos under `/work/<full_name>/`. One active agent run at a time per sandbox; rest queue.
- **Stack**: Python 3.12 + FastAPI + Beanie 2.x on `pymongo.AsyncMongoClient` (motor was retired) on the backend; Vite + React 18 + TanStack on the frontend; Turborepo across uv (Python) and pnpm (TS) workspaces.
- **Mongo access**: `from db import mongo` gives you the process singleton — `mongo.users`, `mongo.repos`, `mongo.sessions` for raw collection ops; Beanie ORM still works (`Repo.find_one(...)`). Lifecycle: `await mongo.connect(uri)` / `await mongo.disconnect()` (idempotent on same DB). `await mongo.ping()` for readiness checks. See [python_packages/db/src/db/mongo.py](../python_packages/db/src/db/mongo.py).
- **Status**: Slices 0–5b shipped. Slice 5b = clone + reconciliation + Reset-via-`/work`-wipe. Provider Protocol widened with `exec_oneshot` (retries Sprites Exec WS-handshake timeouts up to 6×, 1+2+4+8+16+32s backoff), `fs_list`, `fs_delete`, `snapshot`, `restore`. Reconciliation [`services/reconciliation.py`](../apps/orchestrator/src/orchestrator/services/reconciliation.py) is event-driven only (no timer), per-sandbox `asyncio.Lock`, with a top-level safety net + 15-min wall-clock timeout via `_kick_reconcile`. Git is configured once at fixed paths (`/etc/octo-canvas/gitconfig` + `…/git-credentials`) via `sudo -n` and read by every git op via `GIT_CONFIG_GLOBAL` env — HOME-independent. `apt-get update/install` uses `sudo -n` (sprite image must have passwordless sudo). Reset wipes `/work` via `rm -rf /work && mkdir -p /work` and lets reconcile re-clone (visible `pending → cloning → ready`); failed sandboxes fall back to destroy+create via `_reset_via_recreate`. **Every bulk `Repo` update goes through raw `mongo.repos.update_many`** — Beanie's `find().update()` chain silently no-ops in some configurations (don't use it). Introspection deepening: `RepoIntrospection.runtimes` + `.system_packages` + matching nullable `IntrospectionOverrides` lists; detectors at [`runtimes.py`](../python_packages/repo_introspection/src/repo_introspection/runtimes.py) and [`system_packages.py`](../python_packages/repo_introspection/src/repo_introspection/system_packages.py). Sandbox panel shows reconciler activity (configuring_git/installing_packages/cloning/checkpointing/pausing) with burst-poll-on-mutation. Next: slice 6 (Sandbox-Agent invocation; agent runs via `provider.exec_oneshot`).
- **Repo access uses the user's OAuth token, not a GitHub App.** The slice 2 brief was redesigned mid-build to drop the App/installation/webhook path in favor of expanding the slice 1 OAuth scope to `read:user user:email repo` and persisting the token on `User.github_access_token`. See [slice/slice2.md](slice/slice2.md), [Plan.md §12](Plan.md), and the redesign block in [Contributions.md](Contributions.md) for the rationale.

---

## Repo map (where things live)

```
apps/
  web/                  Vite SPA — React 18, TanStack Router/Query, Tailwind
  orchestrator/         FastAPI service — auth, DB, GitHub, WS gateway
  bridge/               Python entry point baked into the Sprite image
packages/
  api-types/            TS types generated from /openapi.json (do NOT hand-edit)
  tsconfig/             Shared TS configs
python_packages/        Reusable Python imported by both apps
  shared_models/        Pydantic models = wire-shape source of truth (HTTP + WS)
  db/                   Beanie models + connect/disconnect
  sandbox_provider/     Sprites Protocol + impl (slice 4)
  github_integration/   githubkit OAuth-token helpers + GithubReauthRequired (slice 2)
  repo_introspection/   GitHub Trees+Contents → RepoIntrospection (slice 3 — `introspect_via_github`); adapter pattern, slice 4 swaps to filesystem source
  agent_config/         System prompts, tool allowlists (slice 6)
docs/
  Plan.md               Full design — heavy, do NOT update without permission
  progress.md           Active state — UPDATE on every session
  agent_context.md      This file — UPDATE when repo "shape" changes
  engineering.md        Change flow & conventions — UPDATE when conventions evolve
  Contributions.md      Append-only log of who did what — UPDATE every session
  TESTING.md            Three-layer test strategy
  scaffold.md           Historical brief (slice 0)
  slice/slice1.md       Historical brief (slice 1)
  sprites/v0.0.1-rc43/  External SDK reference — Sprites Python SDK + raw HTTP/WSS docs (read python.md or http.md when touching the sandbox provider)
```

Top-level rules files: [`../AGENTS.md`](../AGENTS.md), [`../CLAUDE.md`](../CLAUDE.md), [`../.github/copilot-instructions.md`](../.github/copilot-instructions.md), [`../.antigravity/instructions.md`](../.antigravity/instructions.md). All point back to AGENTS.md as canonical.

---

## Mandatory mental model

**Two source-of-truth invariants. Never violate.**

1. **Pydantic models in `python_packages/shared_models/` are the wire shape.** FastAPI request/response schemas use them. WebSocket messages use them. Their TS twins are *generated* into `packages/api-types/generated/schema.d.ts` — never hand-edited.
2. **DB shape ≠ API shape.** `db.models.User` (Beanie `Document`) is internal. `shared_models.UserResponse` (`BaseModel`) is the wire shape. Convert at the route boundary; never reuse a Beanie doc as a `response_model`.

---

## Coding rules (compressed; full text in [`../AGENTS.md`](../AGENTS.md))

- **Reuse before writing.** `grep`/`rg` first. Never duplicate. Extend existing code; don't fork it.
- **Modular files.** One responsibility per file. Soft caps: Python 300 lines, TS 250 lines, function 50 lines.
- **Strict typing everywhere.** Pyright strict, TS `strict: true` + `noUncheckedIndexedAccess`. No `any` / `Any` outside generated code.
- **No defensive code for impossible cases.** No comments restating well-named code. No future-proofing scaffolding.
- **Always update `docs/progress.md`, `docs/Contributions.md`, and `docs/engineering.md`** when you ship code or set a new convention. **Do not** touch `docs/Plan.md`, `CLAUDE.md`, `README.md`, or `scaffold.md` unless the user explicitly says so.
- **Slice briefs are special.** The *active* slice's brief at `docs/slice/slice{n}.md` is editable — when you start a new slice, create it; when scope shifts or the brief diverges from reality, reconcile. Once the user signs off on a slice, its brief is frozen. See [../AGENTS.md](../AGENTS.md) §5.
- **Deviation protocol.** If your work contradicts [Plan.md](Plan.md), the active slice brief, or any other arch doc — *stop, surface the divergence to the user, and wait for direction on whether the plan should be updated*. Never silently edit Plan.md to justify code already written, and never build past a known plan conflict. See [../AGENTS.md](../AGENTS.md) §3.5.
- **Use graphify-out first** for relationship/architecture questions. If `graphify` isn't installed (`which graphify` fails), **ask the user before installing** (`pip install graphifyy`) — never silently. Read [../graphify-out/GRAPH_REPORT.md](../graphify-out/GRAPH_REPORT.md) for the audit summary, or run `/graphify query|path|explain` for targeted lookups — far cheaper than grepping the whole repo. Treat findings as hypotheses; verify by reading actual files. If clearly stale, run `/graphify --update` (incremental). Never load `graph.json` directly. Other capabilities worth knowing: `/graphify add <url>` (ingest external docs), `/graphify --wiki` (agent-crawlable Markdown), `/graphify --mcp` (expose as MCP tools), `graphify hook install` (auto-rebuild on commit). See [../AGENTS.md](../AGENTS.md) §2.7.
- **Frontend = light theme only.** White / `bg-gray-50` backgrounds, `bg-white/80 backdrop-blur` overlays, black text and CTAs (`bg-black text-white`), `border-gray-200` borders. **No `dark:` variants, no saturated colors on surfaces, no gradients, no custom hex colors in component code.** See [../AGENTS.md](../AGENTS.md) §2.8.

---

## Stack constraints (compressed; full rule in [`../AGENTS.md`](../AGENTS.md) §2.6, full inventory in [Plan.md §5](Plan.md))

- Python via **uv only** (`uv run <cmd>`). Never `pip install` directly.
- TypeScript via **pnpm only**. Never `npm` or `yarn`.
- Cross-language tasks via **Turborepo** (`pnpm <task>` from root).
- **Banned**: Hono, Express, tRPC, Drizzle, Bun, Next.js, Prisma, Clerk, Better Auth, Poetry, conda, rye, mypy, black, isort, flake8.

---

## Common commands

```bash
# Setup (first time)
docker compose up -d
cp .env.example .env                          # then fill in secrets
pnpm install
uv sync --all-packages --all-extras           # NOTE the flags — bare `uv sync` is wrong

# Develop
pnpm dev                                      # runs web (5173), orchestrator (3001), bridge

# Verify before "done"
pnpm typecheck && pnpm lint && pnpm test

# Single-package commands
pnpm --filter @octo-canvas/orchestrator test
pnpm --filter @octo-canvas/orchestrator typecheck
pnpm --filter @octo-canvas/web typecheck

# Single pytest test
uv run pytest apps/orchestrator/tests/test_auth.py::test_logout_clears_session -v

# Regenerate TS types after backend changes (orchestrator must be running)
pnpm --filter @octo-canvas/orchestrator dev   # terminal 1
pnpm --filter @octo-canvas/api-types gen:api-types   # terminal 2
```

---

## Gotchas (you will hit one of these — read them)

1. **`uv sync` flags** — bare `uv sync` only installs the root. Always `uv sync --all-packages --all-extras`.
2. **Vite envDir** — `.env` lives at repo root, not in `apps/web/`. `apps/web/vite.config.ts` sets `envDir: '../..'`. Without it, `import.meta.env.VITE_*` is undefined and the SPA renders blank because [../apps/web/src/lib/api.ts](../apps/web/src/lib/api.ts) throws at module load.
3. **One GitHub OAuth App, scope `read:user user:email repo`** — slice 1 + 2 both ride the same OAuth App. The token is persisted on `User.github_access_token` and used directly for `git clone`/`push` and all GitHub API calls. **There is no separate GitHub App, no installation token cache, no webhook server, no smee tunnel.** Anything you read in older docs about a GitHub App is a redesigned-out artifact — see [Plan.md §12](Plan.md).
4. **Beanie `init_beanie` registration** — adding a `Document` class without registering it in [../python_packages/db/src/db/connect.py](../python_packages/db/src/db/connect.py)'s `document_models` list silently fails to query.
5. **`datetime.utcnow()` is forbidden** — deprecated in 3.12, fails Pyright strict. Use `datetime.now(UTC)` via a `_now()` helper. See [engineering.md](engineering.md).
6. **DB shape vs API shape** — never reuse a Beanie `Document` as a FastAPI `response_model`.
7. **Pytest event loop** — DB-touching tests must use the `httpx.AsyncClient + ASGITransport` fixture. Don't add `TestClient`-based tests for DB-touching code; the event-loop wiring breaks.
8. **No hand-editing `packages/api-types/generated/schema.d.ts`** — regenerate via the codegen step in [engineering.md](engineering.md).
9. **OAuth token re-auth is a typed flow, not an exception** — every GitHub call from the orchestrator goes through `github_integration.call_with_reauth(fn)` (or catches `RequestFailed.status_code == 401` for paginators). On 401: clear `User.github_access_token`, return `403 {"detail": "github_reauth_required"}`. The web app turns that into a "Reconnect GitHub" CTA via `meQueryOptions.data.needs_github_reauth` + the `availableReposQueryOptions` reauth sentinel. Never let a 401 bubble as a 500.
10. **GitHub OAuth has no `prompt=consent`** — re-running OAuth refreshes the token but cannot force GitHub to re-show the consent screen for org-access changes. Direct users to the OAuth-app settings page via `GET /api/auth/github/manage` (302s to `https://github.com/settings/connections/applications/<client_id>`) so they can grant/request per-org access. The "Manage GitHub org access" button in the dashboard panel uses this.
11. **`/search/repositories` is unscoped by default** — without `user:`/`org:` qualifiers it searches all of public GitHub. The repos available endpoint scopes via `q="<query> in:name,full_name fork:true user:<me> org:<o1> org:<o2> ..."` after fetching `/user/orgs`. The web FE sends `scope_mine=true` by default but can flip it off.
12. **CORS `allow_methods` is an explicit allowlist** — when adding a new HTTP verb on any `/api/*` route, update [../apps/orchestrator/src/orchestrator/app.py](../apps/orchestrator/src/orchestrator/app.py)'s `CORSMiddleware(allow_methods=[...])` first. Slice 3 shipped `PATCH /api/repos/{id}/introspection` and missed this; preflight failed silently in the browser until caught by manual testing. Current allowlist: `GET, POST, PATCH, PUT, DELETE, OPTIONS`.
13. **Repo introspection — wire shape exposes three fields, not one.** `ConnectedRepo.introspection` is the merged-effective value (read this for "what test command to run"); `introspection_detected` is what GitHub-Trees-API detection produced; `introspection_overrides` is sparse user overrides. `PATCH /api/repos/{id}/introspection` is full replacement of overrides (send `{}` to clear). Re-introspect refreshes `detected` only; overrides survive. Detection is GitHub-API-only (no clone) — slice 4 will add a filesystem source for the same `introspect_via_github` orchestrator.
14. **`SANDBOX_PROVIDER` is explicit — no silent fallback.** `SANDBOX_PROVIDER=sprites` + empty `SPRITES_TOKEN` aborts orchestrator startup with a clear error. `SANDBOX_PROVIDER=mock` boots and emits a `sandbox_provider.mock_in_use` warning every time. CI/prod manifests must assert `SANDBOX_PROVIDER != "mock"`.
15. **Sprites SDK is the sandbox backend.** The `sprites-py` SDK ships only as rc tags (rc37 on PyPI as of 2026-05-01; rc43 docs at [sprites/v0.0.1-rc43/python.md](sprites/v0.0.1-rc43/python.md) and [sprites/v0.0.1-rc43/http.md](sprites/v0.0.1-rc43/http.md) — Python and raw HTTP examples respectively). Workspace pyproject sets `[tool.uv] prerelease = "allow"` so rc resolves. **Never import `sprites` outside `python_packages/sandbox_provider/sprites.py`** — the rest of the codebase goes through the `SandboxProvider` Protocol with an opaque `SandboxHandle(provider, payload)`.
16. **Sprites auto-hibernates; we do not.** No `hibernate` API verb, no idle-job, no Pause button. Live status (`cold | warm | running`) reflects Sprites server-side state. The "Pause" UX in earlier drafts was deleted because the SDK exposes no force-pause endpoint.
17. **`Sandbox` doc fields**: `provider_name` (`"sprites"` | `"mock"`) + `provider_handle: dict[str, str]` (opaque payload) + `public_url` (Sprites' per-sandbox URL). No `region`/`bridge_version`/`hibernated_at`/`sprite_id` — those were Fly-era invented fields.
18. **`Sandbox.status` is 7 states**: `provisioning → cold | warm | running` (Sprites' enum reflected directly), plus `resetting`, `destroyed`, and `failed` for app-level transitions. `IllegalSandboxTransitionError` raised by `SandboxManager` → HTTP 409 from routes. `SpritesError` from the provider → status flips to `failed` with sanitized `failure_reason`; route returns 502.
19. **Reset and Destroy are two operations, not one.** `POST /api/sandboxes/{id}/reset` destroys the sprite + respawns fresh on the *same* `Sandbox` doc (preserves `_id`, increments `reset_count`, rotates `provider_handle.id`). `POST /api/sandboxes/{id}/destroy` fully tears down and marks the doc destroyed; user must `POST /api/sandboxes` to provision a new one (new `_id`). Each has its own UI button + confirmation copy.
20. **`Sandbox` doc creation is lazy AND eager.** `POST /api/sandboxes` is idempotent: returns existing non-destroyed sandbox, or creates the doc *and* immediately calls `provider.create()` (which returns a `warm` sprite — there's no separate "spawn" step). Don't pre-create at signup.
21. **Single-running-per-user is enforced at the routing layer, not the index.** `SandboxManager.get_or_create` returns the user's most-recent non-destroyed sandbox. The Mongo index on `Sandbox.user_id` is non-unique so multi-sandbox per user is a config flip away ([Plan.md §4 forward-compat](Plan.md)).
22. **Sprites' built-in URL is the HTTP preview** ([slice 9 collapses](Plan.md)): `https://{name}-{org}.sprites.app`, configurable as `auth=sprite|public` via `update_url_settings`. Surface it on the dashboard; don't build a separate proxy.
23. **Reset uses checkpoints in slice 5b** (not slice 4). Slice 4's reset is sequential `provider.destroy → provider.create`. Once slice 5b lands, after the first successful clone+install we create a `clean` checkpoint and Reset switches to `restore_checkpoint("clean")` — milliseconds vs. recreate.

---

## Sandbox model — read this before touching slice 4+ work

- **One Sprite per user in v1, multiple-per-user is the design target.** v1 enforces "one per user" at the orchestrator routing layer; the schema, indexes, API paths (`/api/sandboxes/{sandbox_id}/...`), and Sprite naming (`octo-sbx-{sandbox_id}`) are multi-sandbox-ready. Never code "the user's sandbox" as a data-model invariant. See [Plan.md §4 forward-compat note](Plan.md).
- All of a sandbox's repos live in it under `/work/<full_name>/`. `Repo.sandbox_id` (added to schema for slice 4) binds a connected repo to a specific sandbox.
- Lifecycle states: `none → spawning → running → idle → hibernated → resumed → running …`. Destroyed only on explicit user request. Sign-out does **not** destroy.
- One active agent run at a time per sandbox; the rest queue in Redis (`sandbox:{user_id}:queue`).
- The bridge is **long-lived per sandbox**, not per task. It `cd`s into the relevant repo subdir per `StartRun` directive.
- Reconciliation: on `ClientHello`, the orchestrator diffs the user's connected `repos` against the bridge's reported `cloned_repos` and issues `EnsureRepoCloned` / `RemoveRepo` until they match.

Full design: [Plan.md §13–§15](Plan.md).

---

## Verification recipe (the "done" bar)

1. `pnpm typecheck` — Pyright strict + tsc, all green
2. `pnpm lint` — ruff + ESLint, all green
3. `pnpm test` — pytest (real Mongo, mocked GitHub) + Vitest, all green
4. If you touched a route or response model: regenerate api-types (see Common commands above)
5. If you touched UI: exercise the affected flow in a browser
6. Update [progress.md](progress.md) with what changed
7. Append a one-line entry to [Contributions.md](Contributions.md)
8. Update [engineering.md](engineering.md) if you set a new convention

---

## When in doubt, ask. Don't:

- Don't introduce a banned dependency (see [../AGENTS.md](../AGENTS.md) §2.6).
- Don't edit Plan.md, scaffold.md, slice briefs, README.md, or CLAUDE.md without explicit user direction.
- Don't refactor existing code structurally to fit your case — surface it and wait.
- Don't start work on slice N+1 before slice N is approved.
- Don't fix a problem outside the current slice's scope without surfacing it.
