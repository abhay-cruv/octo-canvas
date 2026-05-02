# agent_context.md

Distilled context for any AI coding agent picking up work in this repo. Read this before reading any other doc.

> Sibling docs: [progress.md](progress.md) (active state) · [Contributions.md](Contributions.md) (who-did-what log) · [engineering.md](engineering.md) (change flow) · [Plan.md](Plan.md) (full design — heavy, only if needed) · [../AGENTS.md](../AGENTS.md) (rules — incl. §2.6 stack, §3.5 deviation protocol) · [../CLAUDE.md](../CLAUDE.md) (Claude Code entry-point pointer).

---

## TL;DR

- **Product**: a tool where a user connects GitHub repos, files chat-driven coding tasks, and a `claude` CLI process (Claude Code) running inside a Sprites sandbox — driven by `claude-agent-sdk`, supervised by a long-lived `apps/bridge/` Python daemon over `/ws/bridge/{sandbox_id}` — makes the changes and opens a PR. `Task ↔ Claude session 1:1`; follow-ups use `--resume`.
- **Sandbox model**: **one persistent Sprite per user**, holding *all* of that user's connected repos under `/work/<full_name>/`. One active agent run at a time per sandbox; rest queue.
- **Stack**: Python 3.12 + FastAPI + Beanie 2.x on `pymongo.AsyncMongoClient` (motor was retired) on the backend; Vite + React 18 + TanStack on the frontend; Turborepo across uv (Python) and pnpm (TS) workspaces.
- **Mongo access**: `from db import mongo` gives you the process singleton — `mongo.users`, `mongo.repos`, `mongo.sessions` for raw collection ops; Beanie ORM still works (`Repo.find_one(...)`). Lifecycle: `await mongo.connect(uri)` / `await mongo.disconnect()` (idempotent on same DB). `await mongo.ping()` for readiness checks. See [python_packages/db/src/db/mongo.py](../python_packages/db/src/db/mongo.py).
- **Status**: Slices 0–6 shipped (**slice 6 signed off 2026-05-02** — full VS Code-style IDE: ActivityBar with Files/Git tabs, Monaco multi-tab editor + diff editor in Dark+, xterm multi-tab terminal landing in `/work` with auto-reconnect + 15s keepalive, Source Control panel with per-repo branch/ahead-behind/Staged/Modified/Untracked + colored M/A/U/D/R badges in the file tree, FS REST + PTY WS broker (Redis reattach) + fs-watch broker (cross-instance Redis pub/sub), `safe.directory=*` baked into system `/etc/gitconfig`); **slice 7 in flight 2026-05-02** (agent_config + bridge skeleton + image bake + reconciler `installing_runtimes` phase + `Sandbox.bridge_token_hash` minted at provision — slice 7 brief #4 corrected mid-slice: runtimes are reconciler-installed, not agent-installed); slice 8 brief authored, awaiting kickoff. Slice plan reorganized — slice 6 is now the **IDE shell** (FS panel + Monaco + terminal + dummy chat panel; pulls forward old slice 8 PTY+FS work), slice 7 is **sprite image bake + runtime install + `agent_config` bootstrap** (Node + pinned `claude` CLI + bridge wheel + nvm/pyenv/rbenv; bridge skeleton boots+idles), slice 8 is **chats + bridge + CLI driven by `claude-agent-sdk`** (`Task→Chat` rename; CLI stays alive while user connected — direct feed; `--resume` is cold-path fallback only after `IDLE_AFTER_DISCONNECT_S=300` grace; multi-chats per sandbox cap 5; multi-chats per repo via git worktrees at `/work/<repo>/.octo-worktrees/chat-<slug>/`; pluggable `ClaudeCredentials`, v1 = API key only). User Agent → slice 8b. Git push + PR → slice 9. HTTP preview controls → slice 10. S3 archive → slice 11. See [slice/slice6.md](slice/slice6.md), [slice/slice7.md](slice/slice7.md), [slice/slice8.md](slice/slice8.md). Slice 5b = clone + reconciliation + Reset-via-`/work`-wipe. Provider Protocol widened with `exec_oneshot` (retries Sprites Exec WS-handshake timeouts up to 6×, 1+2+4+8+16+32s backoff), `fs_list`, `fs_delete`, `snapshot`, `restore`. Reconciliation [`services/reconciliation.py`](../apps/orchestrator/src/orchestrator/services/reconciliation.py) is event-driven only (no timer), per-sandbox `asyncio.Lock`, with a top-level safety net + 15-min wall-clock timeout via `_kick_reconcile`. Git is configured once at fixed paths (`/etc/octo-canvas/gitconfig` + `…/git-credentials`) via `sudo -n` and read by every git op via `GIT_CONFIG_GLOBAL` env — HOME-independent. `apt-get update/install` uses `sudo -n` (sprite image must have passwordless sudo). Reset wipes `/work` via `rm -rf /work && mkdir -p /work` and lets reconcile re-clone (visible `pending → cloning → ready`); failed sandboxes fall back to destroy+create via `_reset_via_recreate`. **Every bulk `Repo` update goes through raw `mongo.repos.update_many`** — Beanie's `find().update()` chain silently no-ops in some configurations (don't use it). Introspection deepening: `RepoIntrospection.runtimes` + `.system_packages` + matching nullable `IntrospectionOverrides` lists; detectors at [`runtimes.py`](../python_packages/repo_introspection/src/repo_introspection/runtimes.py) and [`system_packages.py`](../python_packages/repo_introspection/src/repo_introspection/system_packages.py). Sandbox panel shows reconciler activity (configuring_git/installing_packages/cloning/checkpointing/pausing) with burst-poll-on-mutation. Next: slice 7 (sprite image bake + runtime install + `agent_config` bootstrap — in flight).
- **Repo access uses the user's OAuth token, not a GitHub App.** The slice 2 brief was redesigned mid-build to drop the App/installation/webhook path in favor of expanding the slice 1 OAuth scope to `read:user user:email repo` and persisting the token on `User.github_access_token`. See [slice/slice2.md](slice/slice2.md), [Plan.md §12](Plan.md), and the redesign block in [Contributions.md](Contributions.md) for the rationale.

---

## Repo map (where things live)

```
apps/
  web/                  Vite SPA — React 18, TanStack Router/Query, Tailwind
                         IDE shell at /_authed/sandbox uses Monaco (lazy)
                         + xterm.js (lazy) + react-resizable-panels (slice 6)
  orchestrator/         FastAPI service — auth, DB, GitHub, WS gateway
                         routes/sandbox_fs.py (slice 6 FS REST)
                         ws/pty.py + ws/fs_watch.py (slice 6 channels)
                         services/fs_watcher.py (per-sandbox subscribe broker)
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
  agent_config/         ClaudeCredentials Protocol, system prompts, tool allowlists (filled in slice 7; consumed in slice 8)
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
24. **Slice plan was reorganized 2026-05-02.** Old slice 6 ("Tasks + Agent SDK invocation") was split: IDE shell → new slice 6, sprite image bake + runtime install → new slice 7, agent runtime → new slice 8. PTY+FS pulled forward from old slice 8 into new slice 6. Old slice 7 (Git ops + PR) → slice 9. User Agent → slice 8b. HTTP preview controls → slice 10. S3 archive → slice 11. If a doc references "slice 6" with agent context, treat it as stale and check the date.
25. **Bridge daemon is back as of slice 8** (architectural pivot away from the slice-4-era subprocess-per-run-via-Sprites-Exec model). `apps/bridge/` is a long-lived Python process baked into the sprite image (slice 7 bakes; slice 8 dials home). `/ws/bridge/{sandbox_id}` with `BRIDGE_TOKEN` bearer auth. Multiplexes N concurrent `claude` CLI subprocesses driven by `claude-agent-sdk`. `Chat ↔ Claude session 1:1` (`Task` was renamed to `Chat` in slice 8). **CLI stays alive while user is connected** — bridge dispatches `proc.send(text)` directly; `--resume` is the cold-path fallback only when `proc.is_alive() == False` (CLI was killed: 5-min post-disconnect grace, archive, eviction, hibernation, crash). Cap = `MAX_LIVE_CHATS_PER_SANDBOX = 5` with LRU eviction (only chats with no live web subscriber are evictable). Multi-chats per repo via git worktrees at `/work/<repo>/.octo-worktrees/chat-<slug>/`. The orchestrator does NOT open Sprites Exec for agent work (still does for PTY in slice 6). Wire protocol lives at `python_packages/shared_models/src/shared_models/wire_protocol/bridge.py` (slice 8); see [Plan.md §10.4b](Plan.md), [§14](Plan.md).
26. **Claude credentials are pluggable; v1 ships API key only.** `ClaudeCredentials` Protocol at `python_packages/agent_config/src/agent_config/credentials.py` (created in slice 7). v1 implementation = `PlatformApiKeyCredentials` reading `ANTHROPIC_API_KEY` from sprite env (set at provision time in slice 7, NEVER baked into the image). `User.claude_auth_mode: Literal["platform_api_key","user_oauth","user_api_key"] = "platform_api_key"` exists in the schema (slice 8 migration) so OAuth and BYOK can land later as a Protocol impl + settings flip — not a schema migration. The reserved `SessionEnv` WSS frame is the future path for user-scoped credentials; declared in slice 8 wire schema, unused in v1.
27. **Slice 6 IDE — channel architecture, key gotchas.** `/_authed/sandbox` is the entry point. Three new orchestrator surfaces, all auth'd by session cookie + Sandbox ownership:
    - **`/api/sandboxes/{id}/fs*` REST** — `GET ?list=true|false`, `PUT` (with `If-Match: <sha>`, 412 on mismatch + 428 if missing for overwrites; new files create without it), `DELETE` (refuses `/work`), `POST ?op=rename`. Path validation via `_validate_path` is **server-side only** — never trust the FE; reject `..`/encoded `..`/non-`/work` prefixes/null bytes. UTF-8 only (415 on binary), 2 MiB cap (413).
    - **`/ws/web/sandboxes/{id}/pty/{terminal_id}`** — bytes pumped raw both ways + JSON `pty.resize` / `pty.close` (web → server) and `pty.session_info` / `pty.exit` (server → web). Redis caches `pty:{sandbox_id}:{terminal_id} → sprites_session_id` (24h TTL) for browser-refresh reattach (Sprites replays scrollback automatically on attach).
    - **`/ws/web/sandboxes/{id}/fs/watch`** — emits `FsWatchSubscribed` then `FileEditEvent` JSON frames. Single per-sandbox upstream `provider.fs_watch_subscribe`, lazy on first subscriber and dropped on last. `(path, kind)` events coalesced inside a 250ms window; on overflow the WS closes 1011.
    - **Wire types** for these channels live in `python_packages/shared_models/src/shared_models/wire_protocol/sandbox_channels.py` — kept off the slice-5a task-WS unions. `gen_wire_schema.py` dumps them; TS twins in `packages/api-types/generated/wire.d.ts`.
    - **Provider Protocol surface for slice 6**: `fs_read`, `fs_write`, `fs_rename`, `fs_watch_subscribe(path, recursive=True) -> AsyncIterator[FsEvent]`, `pty_dial_info(handle, *, cwd, cols, rows, attach_session_id=None) -> PtyDialInfo`. The orchestrator never imports Sprites directly for these channels — `pty_dial_info` returns the URL + auth headers and the orchestrator's broker dials with raw `websockets`. Mock impl exposes `_pty_url` test override + `emit_fs_event` test hook.
    - **Frontend layout sizes persist** under `localStorage` key `octo:layout` (`{left, right, bottom}` percentages). Terminal id is per-browser-session via `sessionStorage` key `octo:term:id` so a tab refresh reattaches.
    - **Reconciler vs IDE files**: the reconciler still tries to delete unrecognized `/work/<dir>` paths. Slice 6 tests cancel pending `reconcile-*` background tasks in their `_setup` helper as a workaround. Fix: scope reconciler cleanup to `Repo.full_name`-shaped names only. Followup at slice-6 sign-off.
28. **No sprite image bake** (slice 7 corrected mid-slice). Sprites is already a VM — the reconciler installs the bridge prerequisites directly via `exec_oneshot`. New `installing_bridge` phase ([`reconciliation.py`](../apps/orchestrator/src/orchestrator/services/reconciliation.py) `_ensure_bridge_setup`) runs a single `bash -lc` script: apt baseline + clone nvm/pyenv/rbenv at pinned tags + `/etc/profile.d/octo-runtimes.sh` + system Node 20 (NodeSource) + `npm install -g @anthropic-ai/claude-code@<pin>`. Idempotent at the shell level (`if [ ! -d ... ]` guards) and the reconciler level (skip when `Sandbox.bridge_setup_fingerprint == BRIDGE_SETUP_FINGERPRINT`). CLI pin lives at [`apps/bridge/CLAUDE_CLI_VERSION`](../apps/bridge/CLAUDE_CLI_VERSION); bumping it (or any nvm/pyenv/rbenv pin in `reconciliation.py`) rotates the fingerprint → reinstall on next reconcile. No Dockerfile, no CI image-build workflow, no `BRIDGE_IMAGE_TAG` env, no `image_tag` arg on `SandboxProvider.create()`.
29. **Bridge token wiring is slice 8 work.** Slice 7 ships `BridgeRuntimeConfig` in [`sandbox_manager.py`](../apps/orchestrator/src/orchestrator/services/sandbox_manager.py) with `env_for(sandbox_id, bridge_token)` + `mint_bridge_token()` + `_hash_bridge_token()` helpers, but `SandboxManager.get_or_create` does NOT mint tokens at provision (Sprites' rc37 SDK doesn't take env at create). Slice 8's bridge-launch path (alongside `/ws/bridge/{sandbox_id}`) mints fresh tokens, persists SHA-256 on `Sandbox.bridge_token_hash`, and overlays env via `exec_oneshot`. Bridge `--self-check` requires `BRIDGE_TOKEN` only when `ORCHESTRATOR_WS_URL` is set, so `pnpm dev` boots+idles cleanly with no env.
30. **Language-runtime install is reconciler-driven** (slice 7 — corrected mid-slice from "agent installs on first chat"). New `installing_runtimes` phase in [`reconciliation.py`](../apps/orchestrator/src/orchestrator/services/reconciliation.py) between `installing_bridge` and `cloning`. Deduped union of `(name, version)` across all alive repos; per-runtime exec via `bash -lc 'nvm install <ver>'` / `pyenv install -s <ver>` / `rbenv install -s <ver>` (only `node`/`python`/`ruby` wired in v1). Best-effort: failures set `Repo.runtime_install_error` (sanitized) but never block clones. Mock provider exposes `provider.runtimes_installed(handle)` + `provider.fail_runtime_install(...)` test hooks. Frontend dashboard shows a per-repo "Agent setup" banner driven by `runtime_install_error`.

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
