# Plan.md — vibe-platform

End-to-end design and rollout plan for the platform. Source of truth for *what* we're building, *why* the boundaries are where they are, and *the order things ship in*. Live document — slice briefs override it where they conflict, but new design decisions land here first.

> Companion docs: [scaffold.md](scaffold.md) (skeleton), [slice1.md](slice/slice1.md) (auth slice), [TESTING.md](TESTING.md) (verification), [engineering.md](engineering.md) (change flow), [CLAUDE.md](../CLAUDE.md) (agent rules).

---

## 1. Product

A developer tool where the user:

1. Connects a GitHub repository they own/can write to.
2. Files coding tasks via a chat interface ("add a dark mode toggle", "fix the flaky test in `auth_spec.ts`").
3. Watches an AI agent — Claude Agent SDK — running inside an isolated remote sandbox (Fly.io Sprites) actually do the work: read the repo, edit files, run tests, iterate.
4. Reviews the result as a normal pull request on GitHub.

Two modes are envisioned long-term:

- **Dev mode** — work on an *existing* repo. **In scope for v1.**
- **Vibe mode** — generate a *greenfield* project from a prompt with multiple specialized agents (architect, frontend, backend, tests). **Deferred.** Architecture must leave headroom but no scaffolding now.

Boundary line for v1: a real human can sign in, connect a real repo, file a real task, and merge a real PR produced entirely by the agent.

---

## 2. Personas & primary use cases

| Persona | Use case in v1 |
|---|---|
| **Solo developer / indie hacker** | Offload mechanical changes (lint sweeps, dependency bumps, small features). Watch the run, merge the PR. |
| **Tech lead reviewing a PR** | Read the agent's transcript + diff, request changes via chat, get a follow-up commit. |
| **Engineer on a side project** | Quick "fix this bug" or "add this endpoint" without context-switching off mobile. |

Anti-personas (out of scope): teams with shared workspaces, enterprise SSO users, anyone needing audit trails beyond "agent did X at time Y" — those come post-v1.

---

## 3. Capabilities at v1 completion

A signed-in user can:

- ✅ Sign in with GitHub OAuth (read profile, primary email)
- ⬜ Authorize the OAuth App's `repo` scope (during slice 1 sign-in or via a "Reconnect GitHub" prompt for legacy sessions)
- ⬜ See repos accessible via that token and **connect any number of them** to their personal sandbox
- ⬜ See per-repo basic introspection (language, package manager, test command)
- ⬜ Have all connected repos cloned and kept warm in their **single per-user sandbox** under `/work/<repo_full_name>/`
- ⬜ Start a new **task** against any connected repo by chatting in plain English
- ⬜ Watch the agent's progress live: tool calls, file edits, test runs, terminal output, streamed thoughts
- ⬜ See the resulting **pull request** linked back to the GitHub repo
- ⬜ Send a follow-up message that produces an additional commit on the same PR
- ⬜ Hibernate / resume / destroy their sandbox; reconnecting wakes it and finds repos still cloned
- ⬜ Disconnect individual repos (removes the clone from the sandbox, leaves other repos intact)
- ⬜ Sign out; re-visit and find the task list, connected repos, and sandbox intact

The web app has exactly two long-lived surfaces in v1: a **repo list / dashboard** and a **task detail** page (chat + live agent stream + PR link).

Explicit non-features for v1: teams, billing, email notifications, Slack integration, admin panel, mobile app, multi-agent vibe mode, scheduled tasks, branch policies, custom agents, plugin marketplace.

---

## 4. System architecture

Three apps, three shared boundaries, one Pydantic source-of-truth.

```
                        ┌───────────────────────────────┐
                        │       MongoDB (Atlas)         │
                        │  users · sessions · repos     │
                        │  sandboxes · tasks            │
                        │  agent_runs · agent_events    │
                        └──────────────┬────────────────┘
                                       │ Beanie (Motor async)
                                       │
┌──────────────┐  HTTPS + WSS  ┌───────▼───────────────┐  Sprites API   ┌────────────────────────┐
│  apps/web    │ ◄───────────► │  apps/orchestrator    │ ─────────────► │   Fly.io Sprite        │
│  Vite SPA    │               │  FastAPI + uvicorn    │   (REST)       │   (one per user)       │
│  React 18    │               │                       │                │                        │
│  TanStack    │               │  - Auth (Authlib)     │                │  /work/                │
│  Tailwind    │               │  - GitHub OAuth +     │ ◄── WSS ────►  │   ├── repo-a/  (clone) │
│              │               │    githubkit          │                │   ├── repo-b/  (clone) │
└──────────────┘               │  - Sandbox manager    │                │   └── repo-c/  (clone) │
                               │  - WebSocket gateway  │                │                        │
                               │  - Redis (state)      │                │  ┌──────────────────┐  │
                               │  - S3 (event log)     │                │  │  apps/bridge     │  │
                               └───────────────────────┘                │  │  Python          │  │
                                                                        │  │  Agent SDK       │  │
                                                                        │  │  GitPython       │  │
                                                                        │  └──────────────────┘  │
                                                                        └────────────────────────┘
```

Three apps:

- **apps/web** — pure SPA. Vite-built static bundle hosted on Cloudflare Pages or similar. Talks only to the orchestrator. Cannot talk to GitHub or Sprites directly.
- **apps/orchestrator** — long-running FastAPI service on Fly.io. The brain. Holds all secrets. Owns the DB. Owns the WebSocket gateway. Brokers every interaction between web ↔ bridge.
- **apps/bridge** — Python entry point baked into the Sprite image. Boots once when the user's sandbox boots, dials home to the orchestrator over WebSocket, holds many repos cloned under `/work/<full_name>/`, runs the Claude Agent SDK per task against the relevant working copy, streams events back, opens PRs via githubkit.

### Sandbox model — one per user, many repos

Each user gets exactly **one** persistent sandbox. When the user connects a repo, the sandbox clones it into `/work/<repo_full_name>/` and keeps it warm. Tasks run inside this sandbox; the bridge `cd`s into the right repo subdir for each task. Disconnecting a repo removes the subdir but does not destroy the sandbox.

Lifecycle: `none → spawning → running → idle → hibernated → resumed → running …` (per user, not per task). Idle hibernation kicks in after 10 minutes of no active task; resume on next task. Destroyed only on explicit user action (sign-out does **not** destroy — connected repos and warm caches survive).

> **Alternative considered, not chosen:** sandbox-per-task with on-demand `git clone` each time. Simpler isolation, but cold-start cost (clone + dependency install) on every task. Per-user warm sandbox amortizes that cost across N tasks across N repos. If you wanted the simpler model, this is the section to flip.
>
> **Forward-compat note (current limitation, not a permanent constraint):** today the product enforces exactly one sandbox per user — the UI, API surface (`/api/sandbox` with no `{sandbox_id}`), and `Sandbox` collection (one doc per user) all assume singleton. The architecture should be built so this can grow to **multiple sandboxes per user** later (e.g. per-environment, per-team, or to isolate heavy/long-running workloads) without a rewrite. Practically: keep `sandbox_id` on `Task` / `AgentRun` (already the case — see §10), avoid hard-coding "the user's sandbox" in domain logic that could equally accept a sandbox handle, and treat the singleton as a routing/UI choice in the orchestrator rather than a data-model invariant. When we lift the limit, the change should be: add sandbox selection to the task-create flow + repo-connect flow, parameterize the sandbox endpoints by id, and drop the "one per user" uniqueness assumption — not reshape `Task`/`AgentRun`/`Repo`.

Why this shape:

- Sandbox isolation is non-negotiable — the agent runs untrusted-ish code (tests, package installs) and must not touch the orchestrator or other users' data.
- One sandbox per user means each user's repos live alongside each other — natural fit for cross-repo refactors later, and warm `node_modules` / `.venv` between tasks on the same repo.
- Single ingress (orchestrator) for auth, rate limiting, and secret management.
- WebSocket as the bidirectional channel means the orchestrator can push UI updates in real time AND issue control commands (pause, abort, send-follow-up-message) without the bridge polling.

---

## 5. Tech stack — locked in (rule lives in [AGENTS.md §2.6](../AGENTS.md))

### Backend (Python 3.12+)

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | Single language across orchestrator + bridge; Agent SDK has Python parity |
| Package manager | **uv** (workspaces) | Fast, modern, first-class workspace support |
| Web framework | FastAPI ≥ 0.115 (`fastapi[standard]`) | Async-native; auto OpenAPI → TS types |
| ASGI | uvicorn (dev), gunicorn + uvicorn workers (prod) | Standard |
| ODM | **Beanie** (Pydantic + Motor) | Pydantic-as-schema mirrors API layer |
| OAuth | **Authlib** | Just the OAuth dance; sessions are ours |
| HTTP client | httpx | Async, modern |
| GitHub | **githubkit** | Async, OpenAPI-generated, fully typed |
| WebSocket (server) | FastAPI built-in | No second framework |
| WebSocket (client) | `websockets` | Plain stdlib-shaped API |
| Agent | `claude-agent-sdk` | The product |
| Git ops | GitPython | Sufficient for clone/branch/commit/push |
| Logging | structlog | JSON in prod, pretty in dev |
| Settings | pydantic-settings | Strict env validation on boot |
| Lint + format | ruff (replaces black/isort/flake8) | One tool |
| Type check | Pyright **strict** | No untyped functions |
| Tests | pytest + pytest-asyncio | Standard |

### Frontend (TypeScript 5.x)

| Concern | Choice | Why |
|---|---|---|
| Language | TS 5.x with `strict: true`, `noUncheckedIndexedAccess: true` | Catches array `[i]` undefined cases |
| Package manager | **pnpm ≥ 9** | Fast, content-addressed |
| Framework | React 18 + Vite (SPA, no Next.js) | Login-walled product; no SSR value |
| Routing | TanStack Router (file-based) | Typed routes, auth guards via `beforeLoad` |
| Data fetching | TanStack Query | Caching, suspense, invalidation |
| API client | `openapi-fetch` (typed against generated `paths`) | Recovers Hono-RPC-level safety from FastAPI |
| Styling | Tailwind CSS | Utility-first |
| Components | shadcn/ui (initialized, no components yet) | Add per slice |
| Real-time | Native browser `WebSocket` | No socket.io |
| Lint + format | ESLint + Prettier | Standard |
| Tests | Vitest | Standard |

### Cross-language

| Concern | Choice |
|---|---|
| Monorepo orchestration | **Turborepo** — runs commands across pnpm + uv workspaces |
| Type bridge | `openapi-typescript` consumes FastAPI's `/openapi.json` → `packages/api-types/generated/schema.d.ts` |
| Local services | Docker Compose: MongoDB + Redis |

### Banned (do not introduce)

Hono, Express, tRPC, Drizzle, Bun, Next.js, Prisma, Clerk, Better Auth, Poetry, conda, rye, npm, yarn, mypy, black, isort, flake8.

The agent-facing rule version of this list lives in [AGENTS.md §2.6](../AGENTS.md).

---

## 6. Repo layout

```
.
├── apps/
│   ├── web/                       Vite SPA
│   ├── orchestrator/              FastAPI service
│   └── bridge/                    Bridge process for Sprites
├── packages/                      JS-side shared
│   ├── api-types/                 Generated TS types from /openapi.json
│   └── tsconfig/                  Shared TS configs (base / library / react-app)
├── python_packages/               Python-side shared
│   ├── shared_models/             Pydantic models (API + WS wire schemas)
│   ├── db/                        Beanie models + connect/disconnect
│   ├── sandbox_provider/          Sprites abstraction (Protocol + impl)
│   ├── github_integration/        githubkit + GitHub App helpers
│   ├── repo_introspection/        Detect language/framework/test cmd
│   └── agent_config/              System prompts, tool allowlists
├── docker-compose.yml             Mongo + Redis
├── turbo.json                     Cross-language pipeline
├── pnpm-workspace.yaml            apps/* + packages/* + python_packages/*
├── package.json                   Root JS dev tooling
├── pyproject.toml                 uv workspace root
├── tsconfig.json                  TS workspace root
├── pytest.ini, .ruff.toml, .prettierrc, .eslintrc.cjs, ...
├── .env / .env.example
├── README.md, CLAUDE.md, AGENTS.md (root)
├── docs/                                       Plan, engineering, progress, Contributions, agent_context, TESTING, scaffold, slice/
└── Plan.md  (this file)
```

Workspace rules:

- Python packages are uv workspace members AND have empty Turbo-glue `package.json` files (so Turbo discovers them).
- TS packages are pnpm workspace members.
- Reusable Python imported by both apps → `python_packages/`.
- Reusable TS imported by web → `packages/`.
- App-specific code → that app's `src/`.

---

## 7. Type bridges — the load-bearing invariant

```
       Pydantic models (python_packages/shared_models, db/models)
                              │
                              ▼  used as request/response schemas
       FastAPI routes (apps/orchestrator)
                              │
                              ▼  served at runtime
       /openapi.json
                              │
                              ▼  pnpm --filter @vibe-platform/api-types gen:api-types
       packages/api-types/generated/schema.d.ts
                              │
                              ▼  imported via openapi-fetch
       apps/web (typed paths/components/operations)
```

Two non-negotiables:

1. **Pydantic is the single source of truth.** TS types are derived. Never hand-edit `schema.d.ts`.
2. **DB shape ≠ API shape.** `db.models.User` is the Mongo document. `shared_models.UserResponse` is the wire shape. Routes convert at the boundary. Never reuse a Beanie `Document` as a FastAPI `response_model`.

Same principle for WebSocket: messages are Pydantic discriminated unions in `shared_models/wire_protocol/`; the web side gets matching TS via codegen (slice 5+).

---

## 8. Data model (planned, full v1 surface)

Collections in `vibe_platform` Mongo database, each Beanie `Document`. Slice annotation in parens.

### `users` (slice 1 — done)
```python
class User(Document):
    github_user_id: Annotated[int, Indexed(unique=True)]
    github_username: str
    github_avatar_url: str | None
    email: str
    display_name: str | None
    created_at: datetime
    updated_at: datetime
    last_signed_in_at: datetime
    class Settings: name = "users"
```

### `sessions` (slice 1 — done)
Server-side session state keyed by opaque cookie ID.
```python
class Session(Document):
    session_id: Annotated[str, Indexed(unique=True)]
    user_id: PydanticObjectId  # → User._id
    created_at: datetime
    expires_at: datetime          # 7 days from creation
    last_used_at: datetime
    class Settings: name = "sessions"
```

### `repos` (slice 2)

A repo the user has connected. Lives inside their sandbox under `/work/<full_name>/` once cloned.
```python
class Repo(Document):
    user_id: PydanticObjectId
    sandbox_id: PydanticObjectId | None  # set by slice 4 when the user picks a sandbox at connect time; null in slice 2
    github_repo_id: int           # NOT globally unique — same repo can be connected by many users, and same user can connect one repo to many sandboxes
    full_name: str                # "octo-org/repo-name"
    default_branch: str
    private: bool
    introspection: RepoIntrospection | None  # filled by slice 3
    clone_status: Literal["pending","cloning","ready","failed"]  # state of the clone in sandbox
    clone_path: str | None        # "/work/octo-org/repo-name"
    last_synced_at: datetime | None  # last `git fetch` against origin
    connected_at: datetime
    class Settings:
        name = "repos"
        # Compound unique on (sandbox_id, user_id, github_repo_id). user_id is
        # included so the slice-2 row (sandbox_id=null) still enforces "one
        # connection per (user, repo)"; once slice 4 populates sandbox_id, the
        # same repo can appear in N rows — one per sandbox the user attached
        # it to.
        indexes = [IndexModel([("sandbox_id",1),("user_id",1),("github_repo_id",1)], unique=True)]
```

> **Note on auth:** there is no `github_installations` collection. Repo access uses the user's OAuth access token (`User.github_access_token` from §11), not a GitHub App installation token. Cloning, fetching, and pushing all run with that single token.

### `sandboxes` (slice 4)

Holds the sandbox-side state that needs to survive orchestrator restarts (Redis is the hot cache; this is the source of truth). **In v1 the orchestrator enforces one sandbox per user as a routing/UI choice, not a data-model invariant** — the schema and indexes are multi-sandbox-ready (see §4 forward-compat note).

```python
class Sandbox(Document):
    user_id: Annotated[PydanticObjectId, Indexed()]  # NOT unique — see §4 forward-compat note
    name: str | None = None        # user-facing label; null for v1 singletons
    sprite_id: str | None         # Fly Sprite ID; null before first spawn
    status: Literal["none","spawning","running","idle","hibernated","destroyed","failed"]
    region: str                    # Fly region the sprite lives in
    bridge_version: str | None     # set on bridge ClientHello
    last_active_at: datetime | None
    spawned_at: datetime | None
    hibernated_at: datetime | None
    class Settings: name = "sandboxes"
```

### `repo_introspection` (embedded subdocument, slice 3)
```python
class RepoIntrospection(BaseModel):
    primary_language: str | None
    package_manager: Literal["pnpm","npm","yarn","uv","poetry","pip","cargo","go","bundler"] | None
    test_command: str | None
    build_command: str | None
    detected_at: datetime
```

### `tasks` (slice 6)
A user-filed unit of work against one of the user's connected repos. Each task runs in a specific sandbox; in v1 that's the user's singleton, in multi-sandbox future the user (or routing logic) picks one at create time.
```python
class Task(Document):
    user_id: PydanticObjectId
    sandbox_id: PydanticObjectId  # required — disambiguates which sandbox runs the task (multi-sandbox forward-compat per §4)
    repo_id: PydanticObjectId     # which connected repo this task targets
    title: str                    # first line of initial message, or LLM-summarized
    status: Literal["pending","running","awaiting_review","completed","failed","cancelled"]
    initial_prompt: str
    base_branch: str              # usually repo.default_branch at task creation
    work_branch: str | None       # set when bridge creates it
    pr_number: int | None         # set after first push
    pr_url: str | None
    created_at: datetime
    updated_at: datetime
    class Settings: name = "tasks"
```

### `agent_runs` (slice 6)
One run = one agent invocation inside the user's sandbox. A task can have multiple runs (initial + follow-ups). The sandbox is reused across runs (and across tasks across repos).
```python
class AgentRun(Document):
    task_id: PydanticObjectId
    sandbox_id: PydanticObjectId  # → Sandbox._id (the user's sandbox)
    repo_id: PydanticObjectId     # denormalized for fast event-log queries
    status: Literal["spawning","running","completed","failed","cancelled"]
    follow_up_prompt: str | None  # null on first run
    started_at: datetime
    ended_at: datetime | None
    input_tokens: int
    output_tokens: int
    class Settings: name = "agent_runs"
```

### `agent_events` (slice 6, with S3 archival in slice 8)
Append-only event log. Hot rows live in Mongo for the active run; archived to S3 once the run completes.
```python
class AgentEvent(Document):
    run_id: PydanticObjectId
    seq: int                      # monotonic per run
    type: Literal[
        "user_message","assistant_message","tool_call","tool_result",
        "file_edit","shell_exec","git_op","status_change","error",
    ]
    payload: dict[str, Any]       # type-specific JSON
    created_at: datetime
    class Settings:
        name = "agent_events"
        indexes = [[("run_id",1),("seq",1)]]
```

### Cross-doc rules

- All `*_at` fields use `datetime.now(UTC)` via a `_now()` helper. Never `datetime.utcnow()` (deprecated, fails Pyright strict). See [engineering.md:99](engineering.md#L99).
- Every uniquely-keyed field uses `Annotated[T, Indexed(unique=True)]`.
- Every `Document` must be registered in [python_packages/db/src/db/connect.py](../python_packages/db/src/db/connect.py)'s `init_beanie(document_models=[...])` list, or it will silently not be queryable.

---

## 9. HTTP API surface (full v1)

All under `/api`. Auth via `vibe_session` cookie except where noted. Bodies and responses are Pydantic; openapi-typescript generates TS shapes for the web app.

### Auth (slice 1 — done)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/auth/github/login` | 302 to GitHub authorize, sets `vibe_oauth_state` cookie. **Public.** |
| GET | `/api/auth/github/callback` | Validates state, exchanges code, upserts User, creates Session, sets `vibe_session`, 302 to `${WEB_BASE_URL}/dashboard`. **Public.** |
| POST | `/api/auth/logout` | Deletes Session, clears cookie, 204. |
| GET | `/api/auth/session` | Returns user (200) or 401 if no/invalid session. Uses `get_user_optional`. |

### User (slice 1 — done)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/me` | `UserResponse`. 401 if unauthenticated. |

### Repos (slice 2 + 3)

All repo endpoints use the user's stored OAuth access token (`User.github_access_token`). On any 401 from GitHub, the orchestrator clears the token and returns `403 {"detail": "github_reauth_required"}` — the web app uses that signal to send the user back through the OAuth flow.

**Repo connections are per-sandbox** (multi-sandbox forward-compat per §4). Different sandboxes for the same user can have different repo lists; the same `github_repo_id` may appear in N rows (one per sandbox the user attached it to). Slice 2 ships the `user_id`-scoped flat routes below; slice 4 introduces the sandbox-scoped variants and the singleton constraint becomes a routing-layer rule, not a data-model one.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/repos/available` | Repos accessible to the user via their OAuth token. `is_connected` is per-sandbox (slice 4) or per-user (slice 2). Backed by `GET /user/repos` or `GET /search/repositories` when `q` is set. |
| GET | `/api/repos` | Connected repos for this user (with `clone_status` per repo). Slice 4: also accepts `?sandbox_id=` to filter to one sandbox. |
| POST | `/api/sandboxes/{sandbox_id}/repos/connect` *(slice 4)* | Body `{github_repo_id, full_name}`. Verifies access, creates `Repo` with `sandbox_id` populated, enqueues clone, kicks off introspection (slice 3). Returns 409 if the repo is already connected to *this* sandbox. The same repo can be connected to a sibling sandbox without conflict. |
| POST | `/api/repos/connect` *(slice 2 only — deprecated by slice 4)* | Singleton form: body `{github_repo_id, full_name}`. Creates `Repo` with `sandbox_id=null`. Slice 4 will migrate existing rows by binding them to the user's first sandbox. |
| DELETE | `/api/repos/{repo_id}` | Disconnect: removes the clone from its sandbox (slice 4), deletes `Repo`. The repo's other sandbox-bindings (if any) are untouched. |
| POST | `/api/repos/{repo_id}/reintrospect` | Re-run introspection. (slice 3) |
| POST | `/api/repos/{repo_id}/sync` | `git fetch` against origin in the sandbox; updates `last_synced_at`. |

### Sandboxes (slice 4)

Endpoints are parameterized by `{sandbox_id}` from day one (multi-sandbox forward-compat per §4). v1 enforces one sandbox per user at the orchestrator layer — the web app calls `GET /api/sandboxes` to discover the user's singleton id, then uses that id transparently. No API rewrite when the limit lifts; the UI just gains a sandbox picker.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/sandboxes` | Returns `list[SandboxResponse]`. v1 always length-0 or length-1; future may be longer. |
| POST | `/api/sandboxes` | Create a new sandbox. v1: 409 if user already has one. Future: returns the new sandbox. |
| GET | `/api/sandboxes/{sandbox_id}` | Returns `SandboxResponse` — status, sprite_id, last_active_at, region, list of cloned repo paths. 404 if not the caller's. |
| POST | `/api/sandboxes/{sandbox_id}/wake` | Spawn (if `none`/`destroyed`) or resume (if `hibernated`). Idempotent if already running. |
| POST | `/api/sandboxes/{sandbox_id}/hibernate` | Force hibernate now. |
| POST | `/api/sandboxes/{sandbox_id}/destroy` | Destroys the Sprite. Repos bound to this sandbox remain in `repos` but `clone_status="pending"` until next wake. |

### Tasks (slice 6)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/repos/{repo_id}/tasks` | List tasks for a repo. |
| POST | `/api/repos/{repo_id}/tasks` | Body `{prompt}`. Creates Task + first AgentRun. **Wakes the user's sandbox if not already running**; the bridge `cd`s into `/work/<full_name>/` for the run. |
| GET | `/api/tasks/{task_id}` | Task + recent events (paginated). |
| POST | `/api/tasks/{task_id}/messages` | Body `{prompt}`. Creates a follow-up AgentRun on the same Task (same sandbox, same repo subdir). |
| POST | `/api/tasks/{task_id}/cancel` | Sends abort over WS, marks run cancelled. Does **not** hibernate the sandbox. |
| GET | `/api/tasks/{task_id}/events` | Paginated event log (after S3 archival, hits S3). |

### Health & meta
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{"status":"ok"}`. **Public.** |
| GET | `/openapi.json` | FastAPI-generated. **Public.** |

### HTTP error contract

- Auth failures: `401 {"detail":"unauthenticated"}`.
- Permission failures: `403 {"detail":"forbidden"}`.
- Missing resource: `404 {"detail":"not_found"}`.
- Validation: 422 (FastAPI default body).
- Server: `500 {"detail":"internal_error"}` — never leak stack traces or token info. structlog records the real error.

---

## 10. WebSocket protocol (slice 5+)

### 10.1 Transport choice — WS, multiple connections per concern

**Both legs of the system speak WebSocket.** Web↔orchestrator and orchestrator↔bridge share one transport so the codebase has one wire-protocol mental model, one set of reconnect/heartbeat code, and one type-bridge system (Pydantic discriminated unions → TS via codegen).

We **do not** use gRPC, even though HTTP/2 stream multiplexing would give per-channel back-pressure for free. Reasons:

- Browsers don't speak gRPC natively. FE↔BE stays WS regardless. If BE↔bridge were gRPC, the orchestrator would become a transport translator and we'd maintain two type-bridge systems (`.proto`→Python on the bridge link, Pydantic→TS on the web link).
- AGENTS.md §2.6 locks the stack. Adding `protoc` + `grpcio` is a heavier ask than the back-pressure win justifies for v1.
- Multi-WS-connections gets ~90% of gRPC's per-channel isolation with infra we already have.

Revisit the decision **only** if production telemetry shows we're routinely running 8+ concurrent streaming channels per sandbox.

### 10.2 The four channels

We split the wire into **four logical channels**, each on its own WS connection. They have very different latency/throughput/durability needs and would clobber each other if multiplexed onto one socket.

| Channel | Endpoint | Direction | Wire | Replay-able | Latency budget | Lifetime |
|---|---|---|---|---|---|---|
| **Control + events** | `/ws/web/tasks/{task_id}` (web side) and `/ws/bridge/sandboxes/{sandbox_id}` (bridge side) | bidi | JSON (Pydantic union) | yes — `seq`-replay from Mongo | ms | long-lived (sandbox lifetime on bridge side; task page lifetime on web side) |
| **PTY** | `/ws/web/sandboxes/{sandbox_id}/pty/{terminal_id}` (web) and `/ws/bridge/sandboxes/{sandbox_id}/pty/{terminal_id}` (bridge) | bidi | binary (xterm.js bytes) | no | <50 ms (keystroke→pixel) | terminal session lifetime, opened on demand |
| **File ops** | REST: `GET/PUT /api/sandboxes/{id}/fs?path=...` | req/resp | HTTP (binary or text body) | n/a | seconds OK for big files | per-request |
| **HTTP preview** | proxy at `https://sandbox-{id}.preview.<domain>/...` | bidi | HTTP/HTTPS | n/a | normal HTTP | per-request |

Why split:

- A 10 MB `pnpm install` log multiplexed onto the same WS as keystrokes induces head-of-line blocking — terminal feels janky. PTY needs its own socket.
- Big file reads/writes don't fight terminal traffic when they go REST.
- HTTP preview is its own concern (forwarding arbitrary localhost:N traffic to the user's browser); shoving it into a WS would force us to build a full HTTP-over-WS proxy.

PTY connections are **opened on demand** (when the user clicks "Open terminal") and closed when the tab/terminal closes — most active sandboxes have zero PTYs open at any moment. Average wire footprint per active sandbox: ~2 WS connections (one control on web, one control on bridge), ~3 if the user has a terminal open.

### 10.3 Endpoints + authentication

| Endpoint | Who connects | Auth |
|---|---|---|
| `/ws/web/tasks/{task_id}` | web client subscribes to a task's event stream | session cookie via FastAPI `Depends` on the WS handshake |
| `/ws/web/sandboxes/{sandbox_id}/pty/{terminal_id}` | web client opens a terminal | session cookie |
| `/ws/bridge/sandboxes/{sandbox_id}` | the bridge in a Sprite dials **once per sandbox boot** | long-lived **bridge token** (rotatable; re-issued on every wake) |
| `/ws/bridge/sandboxes/{sandbox_id}/pty/{terminal_id}` | bridge opens its end of a PTY when the orchestrator instructs it | bridge token |

All messages are Pydantic discriminated unions in `python_packages/shared_models/wire_protocol/`. Discriminator field: `type`.

### 10.4 Bridge → orchestrator (control + events channel)

```
ClientHello              { type, sandbox_id, bridge_version, cloned_repos: [{full_name, head_sha, last_synced_at}] }
RunStarted               { type, run_id }                          # bridge ack of StartRun
ToolCallEvent            { type, run_id, seq, tool_name, args }
ToolResultEvent          { type, run_id, seq, tool_name, ok, output }
FileEditEvent            { type, run_id, seq, path, before_sha, after_sha, summary }
ShellExecEvent           { type, run_id, seq, cmd, exit_code, stdout_tail, stderr_tail }
GitOpEvent               { type, run_id, seq, op, branch?, commit_sha?, pr_url? }
AssistantMessageEvent    { type, run_id, seq, content, finish_reason? }
StatusChangeEvent        { type, run_id, seq, new_status }
ErrorEvent               { type, run_id?, seq, kind, message }     # run_id absent for sandbox-level errors
TokenUsageEvent          { type, run_id, seq, input_delta, output_delta }
RepoCloneStatus          { type, full_name, status, error? }       # ack for EnsureRepoCloned / RemoveRepo
PtyOpened                { type, terminal_id }                     # bridge ack of OpenPty
PtyClosed                { type, terminal_id, exit_code? }
Heartbeat                { type, last_active_at }
Pong                     { type, nonce }
```

Orchestrator responsibilities on receive:

1. Persist `*Event` as `AgentEvent` keyed by `run_id` (monotonic `seq`).
2. Fan out to web subscribers on the same task.
3. Update parent `AgentRun.status` / `Task.status` on terminal events.
4. Update `Repo.clone_status` and `Sandbox.last_active_at` on `RepoCloneStatus` / `Heartbeat`.

### 10.5 Orchestrator → bridge (control channel)

```
ServerHello              { type, tool_allowlist, agent_defaults, resume_after_seq? }
EnsureRepoCloned         { type, full_name, base_branch, user_token }
RemoveRepo               { type, full_name }
StartRun                 { type, run_id, task_id, repo_full_name, base_branch, prompt, follow_up, user_token }
UserFollowUpMessage      { type, run_id, content }
AbortRun                 { type, run_id, reason }
OpenPty                  { type, terminal_id, cwd?, cols, rows }
ResizePty                { type, terminal_id, cols, rows }
ClosePty                 { type, terminal_id }
HibernateSandbox         { type }                                  # bridge flushes, exits cleanly
Ping                     { type, nonce }
```

### 10.6 Web → orchestrator (control channel)

The orchestrator transcodes `AgentEvent`s into a UI-friendly schema (`TaskEventForUI`) and pushes them down. Web clients send:

```
Resume                   { type, after_seq }                       # on (re)connect, request replay
SendFollowUp             { type, run_id, content }
CancelTask               { type, task_id }
RequestOpenPty           { type, terminal_id, cwd?, cols, rows }
RequestClosePty          { type, terminal_id }
ResizePty                { type, terminal_id, cols, rows }
Pong                     { type, nonce }
```

Everything else is HTTP.

### 10.7 PTY channel (binary)

Frames are raw bytes — what xterm.js sends/receives. No JSON envelope, no `seq`. Both directions are pure byte streams; the channel dies if either end disconnects, and the user reconnects via `RequestOpenPty` to start fresh (PTY history is *not* replay-able by design — the user got the bytes the first time, and the bridge already wrote them to the terminal subprocess).

PTY frames carry only one out-of-band signal: a **terminal close** (sent as a zero-length WS Close frame with status code `1000`). Resize is on the control channel, not inline.

### 10.8 Reliability — disconnects must be graceful and robust

The wire is the most-tested surface in production. **Every channel on every leg must survive**: orchestrator restarts, bridge restarts, network blips, NAT timeouts, Fly Sprite hibernate/resume, browser tab sleep, mobile-network handoffs. Rules:

#### Heartbeat

- Application-level `Ping`/`Pong` with `nonce`, every **30 seconds** in both directions.
- **Two missed pongs (~90 s)** → declare the peer dead and close with code `1011`.
- WS-protocol-level frames (`websockets` lib does these) run at TCP keepalive frequency; they detect dead TCP, not dead apps.

#### Sequence numbers + replay (control + events only)

- Server-side: every event the orchestrator persists into `agent_events` gets a monotonic `seq` per `run_id`.
- Client-side (web + bridge): track `last_seen_seq` per `run_id`; persist in memory only — survives short reconnects but not browser refresh (server replays from Mongo on reconnect anyway).
- On reconnect: client sends `Resume{after_seq}` as the first message; orchestrator streams missed events from Mongo, then resumes live.
- Mongo retains the last **24 hours** of events per run hot; older fetches go through the slice 8 S3 archive transparently.

#### Idempotency

- All bridge-bound directives (`EnsureRepoCloned`, `RemoveRepo`, `StartRun`, `OpenPty`, `HibernateSandbox`) are **idempotent**. The bridge re-applying the same directive after a reconnect must be safe.
  - `EnsureRepoCloned` re-checks disk; `git fetch` if already cloned.
  - `StartRun` checks `AgentRun.status` in Mongo before re-running; if `completed`, replays the terminal events instead.
  - `OpenPty` checks if `terminal_id` already exists; reuses if so.
- Each directive carries a server-issued **`directive_id`**. The bridge tracks the last 100 it acted on; duplicates within that window are ignored (returns the cached ack).

#### Reconnect flow — bridge side

1. WS closes. Bridge enters **reconnect loop**: exponential backoff `1, 2, 4, 8, 16, 30, 30, 30…` seconds with ±25% jitter, no cap on total retries.
2. On reconnect: send `ClientHello` with current `cloned_repos` and the bridge's last `seq` per known run.
3. Orchestrator replies `ServerHello{resume_after_seq}` and re-issues any directives the bridge hadn't acked. Reconciliation runs.
4. Active runs continue if the bridge still has the agent process alive; if the bridge **process** died and respawned, in-flight runs are marked `failed` with `ErrorEvent{kind: "bridge_restart"}` and the user can retry.

#### Reconnect flow — web side

1. WS closes. Web app shows a small "Reconnecting…" indicator (do not unmount the task page — keep all state).
2. Reconnect with **exponential backoff `0.5, 1, 2, 4, 8, 16, 30, 30…` seconds with ±25% jitter**. First retry is fast (likely network blip).
3. On reconnect, send `Resume{after_seq: last_seen_seq}`. Orchestrator replays from Mongo.
4. If the user is mid-PTY: that connection was binary and stateless, so the web app re-issues `RequestOpenPty` for each terminal that was open. The orchestrator recreates the PTY pair. **Terminal scrollback is the user's view; bridge does not replay PTY bytes.**

#### Backpressure

- Orchestrator buffers up to **1000 events per (run, web subscriber)**. If a slow web client overflows: drop intermediate events with a `BackpressureWarning` event, advance `seq`. Client will catch up via `Resume` on next reconnect. Never grow buffers unbounded.
- Bridge → orchestrator: bridge buffers up to **5 MB** of pending events; if it overflows (typically because the orchestrator side dropped its WS), the bridge **drops the oldest non-terminal events first**, keeping `StatusChangeEvent` and `ErrorEvent`. These are reconstruction-critical.
- PTY channel: **drop frames** under back-pressure (slow client). Terminal output may briefly garble; better than freezing keystrokes. Coalesce contiguous output frames bridge-side at ≤100 Hz.
- File-watch (`FileEditEvent` stream while the agent edits): **coalesce by `path`** — one event per path per ~250 ms window.

#### Fail-fast vs. fail-soft

- Auth failure on (re)connect: **fail fast** (close `4001`, no retry without manual reauth). Bridge token expired or invalid → orchestrator closes `4002`, bridge stops retrying and exits; the next `wake` will issue a fresh token.
- Schema mismatch (Pydantic validation fails): **fail soft** for the offending message (drop, log, increment metric); do **not** kill the connection. Schemas evolve.
- Orchestrator restart mid-task: bridge sees TCP close, reconnects via the exponential-backoff loop; web sees the same. Both replay via `seq`. **No data is lost** because every event was persisted to Mongo before the orchestrator acknowledged it.

### 10.9 Horizontal scale — sticky routing + Redis pub/sub fallback

The orchestrator is stateless (per [§4](#4-system-architecture)). Multiple instances run behind Fly's load balancer. WS connections need to land on the **right instance** so directives don't cross-talk.

#### Sticky-by-sandbox

- Both the bridge for sandbox X and the web client(s) watching sandbox X get pinned to the same orchestrator instance, keyed by `sandbox_id` hash.
- Mechanism: Fly `fly-replay` headers. On the WS upgrade request, the LB hashes `sandbox_id` (path param) and routes to a chosen instance; that instance's `instance_id` is recorded in Redis at `sandbox:{id}:owner` with a 60s TTL, refreshed on heartbeat.
- The web `/ws/web/tasks/{task_id}` handshake reads `task → sandbox_id` and replays the same hash so the web client lands on the same instance as the bridge.

#### Redis pub/sub — slow path fallback

- Channel: `sandbox:{id}`. Any orchestrator instance that receives a message for a sandbox it does **not** currently own (e.g., during a deploy when ownership flips) republishes the message via Redis pub/sub.
- The owning instance subscribes to `sandbox:{owned_id}` for each sandbox it owns; it picks up the republished message and forwards to the correct connected peer.
- Pub/sub is the fallback, not the primary path. Hot path stays in-process for ~99% of messages.

#### Capacity caps + shedding

- Each orchestrator instance advertises its current `(connections, sandboxes_owned)` to a Redis hash `orchestrator_capacity:{instance_id}`. Fly's LB checks before routing new sandboxes.
- Per-instance soft cap: **5000 WS connections** (control + PTY combined). Hot-shed beyond that — return 503 on new sandbox spawns until an instance with headroom is available. Don't degrade existing connections.

### 10.10 What we deliberately don't do (yet)

- **No FE↔bridge direct connection.** All web traffic to the sandbox goes through the orchestrator. Costs ~10–20 ms per hop, buys auth + audit + rate-limit + transparent reconnect when an orchestrator dies. Direct-to-bridge (e.g., WebRTC data channels) is a v2 latency optimization if PTY genuinely bites.
- **No multiplexing all four channels onto one WS.** See §10.2 — head-of-line blocking on PTY is the failure mode.
- **No SSE / long-poll fallback.** WS works on every supported browser and through every supported proxy; one transport is enough.
- **No protocol versioning beyond Pydantic schema evolution.** When we need a v2, add `version` to `ClientHello`/handshake and branch at the handler. Don't pre-build a versioning system before we need one.

---

## 11. Authentication & session model (slice 1 — implemented)

- **Provider**: GitHub OAuth only. No email/password, no other providers, no email transport.
- **Library**: Authlib `AsyncOAuth2Client` for the OAuth dance. Sessions are ours.
- **Session ID**: `secrets.token_urlsafe(32)`. Stored in `Session.session_id` and as the `vibe_session` cookie value. Nothing else in the cookie.
- **Cookie**: `httponly=True`, `secure=is_production`, `samesite="lax"`, `max_age=7d`, `path="/"`.
- **CSRF for OAuth flow**: a second short-lived cookie `vibe_oauth_state` (10 min, samesite=lax) holds a `secrets.token_urlsafe(32)` state token. Verified and cleared on callback.
- **Scope**: `read:user user:email repo`. The `repo` scope (added in slice 2) lets the orchestrator clone, fetch, and push on the user's behalf using their OAuth token. (We deliberately do **not** use a separate GitHub App — see §12.)
- **Token persistence**: the OAuth access token is stored on `User.github_access_token` (encrypted at rest in v1.1; plain in v1 dev — flagged as a followup). It is refreshed on every successful OAuth callback. On a 401 from GitHub the orchestrator clears it and the user must re-auth via the OAuth flow.
- **Lookup path**: every request → read cookie → load `Session` → check `expires_at` → load `User` → bump `last_used_at`. Implemented as the FastAPI dependency `require_user` in [apps/orchestrator/src/orchestrator/middleware/auth.py](../apps/orchestrator/src/orchestrator/middleware/auth.py). Optional variant `get_user_optional` returns `None` instead of raising.

Hard rules (from [slice1.md:643-651](slice/slice1.md#L643-L651)):

- No second auth library.
- No email transport, ever.
- No data in cookies — opaque session ID only.
- Never skip the `require_user` dependency on protected routes.

---

## 12. GitHub integration (slice 2)

**One GitHub-side artifact: the OAuth App from slice 1**, with the `repo` scope added. There is no separate GitHub App, no installation flow, no webhook server, no smee tunnel.

The decision: `repo` scope on the OAuth App gives the orchestrator everything it needs to clone, branch, push, and open PRs on the user's behalf using `githubkit.TokenAuthStrategy(user.github_access_token)`. We accept the tradeoffs (commits attributed to the user, all-or-nothing repo access at consent time, org SSO friction on enterprise orgs) for a much simpler setup story.

> **Alternative considered, not chosen:** a separate GitHub App with installation tokens. Pros: per-repo access selection, bot identity on commits, short-lived tokens. Cons: second GitHub-side registration, private key management, smee.io tunnel for local webhooks, two parallel auth code paths. We may revisit if/when org admins ask for "install per repo" granularity. To flip back, restore the App + installation model from `git log` around the slice 2 redesign.

Slice 2 work:

1. Expand slice 1's OAuth scope to `read:user user:email repo`. Existing users who signed in before the change have a token without `repo`; the web app shows a "Reconnect GitHub" CTA that re-runs the OAuth flow.
2. Persist the access token on `User.github_access_token` in the OAuth callback.
3. List "available repos" by calling `GET /user/repos?affiliation=owner,collaborator,organization_member` with the user's token (paginated via githubkit). Filter out repos already in `repos`.
4. Connect: re-fetch via `GET /repos/{owner}/{repo}` to verify access, persist `Repo`.
5. Disconnect: delete the `Repo` doc.
6. **401 handling**: any GitHub call returning 401 → clear `User.github_access_token`, return `403 {"detail":"github_reauth_required"}`. Web maps that to the reconnect CTA.

No installation tokens, no token cache (the user token is persisted; githubkit gets it directly), no webhook handler.

---

## 13. Sandbox lifecycle (slice 4)

**One persistent sandbox per user.** It hosts every connected repo of that user under `/work/<full_name>/` and serves every agent run. It outlives individual tasks; it does not outlive the user account.

[`SandboxProvider` Protocol](../python_packages/sandbox_provider/src/sandbox_provider/interface.py) — currently has TODO methods. To implement:

```python
class SandboxProvider(Protocol):
    async def spawn(self, *, user_id: PydanticObjectId, env: dict[str,str]) -> SandboxHandle: ...
    async def resume(self, sprite_id: str) -> SandboxHandle: ...
    async def hibernate(self, sprite_id: str) -> None: ...
    async def destroy(self, sprite_id: str) -> None: ...
    async def exec(self, sprite_id: str, cmd: list[str], cwd: str | None = None) -> ExecResult: ...
    async def clone_repo(self, sprite_id: str, *, full_name: str, base_branch: str, user_token: str) -> None: ...
    async def remove_repo(self, sprite_id: str, *, full_name: str) -> None: ...
```

Concrete impl: `FlySpritesProvider`, calling Fly Sprites REST API with `SPRITES_API_KEY`. Sprites are named by `Sandbox._id`: `vibe-sbx-{sandbox_id}`. v1 enforces exactly one Sandbox per user at the orchestrator routing layer; the multi-sandbox future (§4 forward-compat note) simply lifts that enforcement — no naming or schema change needed.

### Per-user state machine

```
                         user signs up
                              │
                              ▼
                       ┌────────────┐
                       │   none     │
                       └─────┬──────┘
                             │ first task / explicit /api/sandbox/wake
                             ▼
                       ┌────────────┐
              ┌──────► │  spawning  │
              │        └─────┬──────┘
              │              │ bridge dials WS, ClientHello accepted
              │              ▼
              │        ┌────────────┐ ◄────── follow-up / new task on any repo
              │        │  running   │ ─────► run agent in /work/<full_name>/
              │        └─────┬──────┘
              │              │ no active run for 10 min
              │              ▼
              │        ┌────────────┐
              │        │ hibernated │
              │        └─────┬──────┘
              │              │ next task / /api/sandbox/wake
              │              ▼
              │        ┌────────────┐
              └──────  │  resumed   │  (transient — collapses to running)
                       └────────────┘

              explicit /api/sandbox/destroy or fatal error:
              running | hibernated  ──►  destroyed
              (Repo rows survive; clone_status flips back to "pending")
```

### Concurrency model inside one sandbox

A user can have multiple tasks. v1 policy: **one active agent run at a time per sandbox**, others queue. Rationale: simpler reasoning about concurrent file system writes, simpler resource caps, simpler UX (one "live" task indicator). Pre-v2 we revisit; the bridge already speaks per-run WS so promoting to N concurrent runs is a code change, not a protocol change.

Queue lives in Redis: `sandbox:{user_id}:queue` (LIST of `run_id`). The bridge dequeues; the orchestrator monitors queue length and exposes it as `Sandbox.queue_depth` for the UI (slice 6 polish).

### State storage

- **Mongo `sandboxes`** — durable source of truth: `user_id`, `sprite_id`, `status`, `region`, `bridge_version`, timestamps.
- **Redis** — hot cache for the orchestrator hot path, so repeated reads on every request don't hit Mongo:
  - `sandbox:{user_id}` → hash of `{sprite_id, status, last_active_at}`
  - `sandbox:{user_id}:queue` → list of pending `run_id`s
  - `sandbox:{user_id}:active_run` → currently-running `run_id` (or unset)
- Mongo is updated on state transitions; Redis is updated on every heartbeat.

### Idle hibernation

A periodic job (`apps/orchestrator/src/orchestrator/jobs/hibernate_idle.py`) scans `sandboxes` where `status="running"` and `last_active_at < now - 10min` AND no active run; calls `provider.hibernate`. Resume happens lazily on the next task or explicit `/api/sandbox/wake`.

### Destroy semantics

`POST /api/sandbox/destroy` is destructive: warm caches (`node_modules`, `.venv`) are gone, repos go back to `clone_status="pending"`, but the `repos` collection rows survive. Next wake re-clones them. This is the user's "everything's weird, blow it away" button. Sign-out does **not** destroy.

---

## 14. Bridge & agent runtime (slices 5–7)

The bridge is **long-lived per sandbox** — boots once when the Sprite spawns, stays connected to the orchestrator over a single WS, services many tasks across many repos sequentially.

### On Sprite boot (once per sandbox lifetime, until hibernate)

1. Read env: `BRIDGE_TOKEN` (per-sandbox, long-lived but rotatable), `ORCHESTRATOR_BASE_URL`, `USER_ID`, `SANDBOX_ID`.
2. Connect WS to `/ws/bridge/sandboxes/{sandbox_id}`. Send `ClientHello{bridge_version, cloned_repos: [...]}` listing what's already on disk under `/work/`.
3. Receive `ServerHello{tool_allowlist, agent_defaults}`.
4. Reconcile clones: orchestrator compares `cloned_repos` (reported by *this* bridge for *this* sandbox_id) to the `Repo` rows where `sandbox_id == this.sandbox_id`, and issues `EnsureRepoCloned` / `RemoveRepo` directives until the disk matches the desired state. Reconciliation is **per-sandbox**, not per-user — each sandbox owns its own subset of the user's `Repo` rows (multi-sandbox forward-compat per §4).
5. Enter the run loop.

### Run loop (per agent run)

1. Receive `StartRun{run_id, task_id, repo_full_name, base_branch, prompt, follow_up: bool, user_token}` from orchestrator.
2. `cd /work/<repo_full_name>/`. If missing (race): clone now.
3. `git fetch origin` + `git checkout -B <work_branch> origin/<base_branch>` — the work branch is `vibe/task-{task_id_short}` for run 1, additional commits go on the same branch for follow-ups.
4. Invoke the Claude Agent SDK with:
   - System prompt from `agent_config.dev_agent` (templated with repo metadata, language, test command, and any in-repo `CLAUDE.md`)
   - The user's `initial_prompt` (or `follow_up_prompt`)
   - Tool allowlist: `read_file`, `write_file`, `apply_patch`, `run_shell` (sandboxed to `/work/<full_name>/`), `run_tests`
   - Streaming callback emitting `*Event` messages over WS
5. After the agent finishes (or a tool-budget cap hits): `git add -A && git commit -m "..."`, push to origin. On first run open a PR via githubkit; on follow-ups the PR auto-updates.
6. Send `StatusChangeEvent{run_id, new_status: "completed"}`. Loop back to (1) for the next `StartRun`.

### Why long-lived

- Skip WS reconnect + `ClientHello` round-trip per task.
- Keep warm caches: `node_modules`, `.venv`, downloaded test fixtures, `pip` and `pnpm` global stores.
- Single bridge process can short-circuit clones: if `/work/<full_name>/` exists and `last_synced_at` is recent, skip the `git fetch`.

### Cross-repo runs (post-v1 hook)

The bridge already has every connected repo on disk, so a future task model that names *multiple* repo paths in one run drops in cleanly: the agent's `read_file`/`write_file` tools accept any path under `/work/`, and the run-finalize step would push to N branches and open N PRs. Not in v1; the v1 task is single-repo and `run_shell` is jailed to one repo subdir.

### Tools

Tool implementations live in `apps/bridge/src/bridge/agent/tools/`. Each tool:
- Takes typed args (Pydantic).
- Emits a `ToolCallEvent` before execution, `ToolResultEvent` after.
- Has a budget check (`run_shell` capped at 5 minutes wall time, output truncated to 50 KB).
- Path arguments are validated to live under the run's repo subdir; absolute paths and `..` traversal are rejected.

### System prompt design (`python_packages/agent_config/`)

- Repo metadata injected (full_name, default_branch, language, test command).
- Project conventions injected if a `CLAUDE.md` exists in the repo.
- Hard rules: don't `rm -rf /`, don't push to base branch, don't expose secrets in commits, never reach outside the current repo subdir.

---

## 15. Git workflow inside the bridge (slice 7)

- All git ops happen inside `/work/<repo_full_name>/`. The bridge sets `cwd` per command; never `cd`s globally (so concurrent runs in the future stay isolated).
- Repo bootstrap (slice 4 onward, on `EnsureRepoCloned`): `git clone --filter=blob:none https://x-access-token:<user_token>@github.com/<full_name>.git /work/<full_name>` — partial clone for fast first-pull on big repos. Then `git remote set-url origin https://github.com/<full_name>.git` to scrub the token.
- Branch naming: `vibe/task-{slug}` where `slug` is 8 chars of the task id. Run 1 creates it; follow-up runs check it out and add commits.
- Commit messages: agent generates them; bridge appends `Co-Authored-By: vibe-platform <bot@vibe.dev>`.
- Push: HTTPS with the user's OAuth access token via `git -c http.extraheader="AUTHORIZATION: bearer <user_token>" push`. Token never written to `.git/config`.
- PR creation: githubkit `repos.create_pull_request` against `default_branch`. Body includes a deep link back to the platform task page.
- PR updates on follow-ups: just push more commits to the same branch — GitHub auto-updates the PR diff.
- Disconnect path: `RemoveRepo` → `rm -rf /work/<full_name>/`. Other repos in `/work/` are untouched.

---

## 16. Cross-cutting concerns

### 16.1 Observability

- **Logging**: structlog everywhere. JSON in production, pretty in dev. Standard event names: `auth.login`, `auth.callback_state_mismatch`, `db.connected`, `sandbox.spawn`, `agent.tool_call`, etc.
- **Request IDs**: middleware adds `request_id` to every log line and to the response header.
- **Metrics**: out of scope for v1. Stub a `/metrics` endpoint with placeholder Prometheus output if it becomes useful.
- **Error reporting**: out of scope for v1. (Sentry at v1.1.)

### 16.2 Security

- Cookies: `httponly`, `secure` in prod, `samesite="lax"`.
- CORS: only `WEB_BASE_URL` allowed, `allow_credentials=True`.
- Webhook HMAC verification on all GitHub webhook payloads.
- Secrets never in logs, never in error responses, never in commits.
- `claude-agent-sdk` invocation is sandboxed per Sprite; tools cannot reach the orchestrator filesystem.
- Run tokens are one-time, scoped to a single `run_id`, expire 30 minutes after issue.
- Rate limiting: out of scope for v1 outside obvious surfaces (login endpoint at 30 req/min/IP).

### 16.3 Type safety

- TS: `strict: true`, `noUncheckedIndexedAccess: true`. No `any` outside `*.gen.ts`.
- Python: Pyright strict. No untyped functions.
- `pnpm typecheck && pnpm lint` is part of "done" — see [TESTING.md:174](TESTING.md#L174).

### 16.4 Testing strategy ([TESTING.md](TESTING.md))

Three layers:

| Layer | Cost | What runs | When |
|---|---|---|---|
| 1 — Automated | cheap | `pnpm typecheck && pnpm lint && pnpm build && pnpm test` (Pyright, ruff, ESLint, vitest, pytest with real Mongo + mocked GitHub) | Every change |
| 2 — Probe orchestrator | cheap | `pnpm dev` + curl against `/health`, `/openapi.json`, login redirect, `/api/me` 401 | Every backend change |
| 3 — UI flow w/ real GitHub | manual | Real OAuth round-trip in browser; verify Mongo writes + sign-out | After auth/repo/task changes; before merging a slice |

Conventions:
- Pytest uses an `httpx.AsyncClient` + `ASGITransport` fixture. Don't add `TestClient`-based tests for DB-touching code (event-loop wiring breaks).
- Test DB is `vibe_platform_test`, dropped in a session-scoped fixture.
- GitHub API is mocked at the httpx layer in unit tests; layer 3 hits real GitHub.

### 16.5 Codegen pipeline

After any change to an orchestrator route or response model:

```bash
# Terminal 1
pnpm --filter @vibe-platform/orchestrator dev
# Terminal 2 (once orchestrator is up)
pnpm --filter @vibe-platform/api-types gen:api-types
```

This rewrites [packages/api-types/generated/schema.d.ts](../packages/api-types/generated/schema.d.ts). The frontend picks up the new types on next typecheck. **Auto-regen on backend change is intentionally deferred** — the manual two-terminal step is fine for v1.

### 16.6 Dev workflow (humans + agents)

```bash
docker compose up -d                          # Mongo (Redis is in compose for slice 4+)
cp .env.example .env                          # fill in secrets per .env.example
pnpm install
uv sync --all-packages --all-extras           # NOTE the flags — bare `uv sync` is wrong
pnpm dev                                      # turbo runs web (5173), orch (3001), bridge
```

Before considering work done: `pnpm typecheck && pnpm lint && pnpm test`.

---

## 17. Environment variables (full v1 set; see [.env.example](../.env.example))

| Var | Used by | Slice |
|---|---|---|
| `MONGODB_URI` | orchestrator | 1 |
| `REDIS_URL` | orchestrator | 4 |
| `AUTH_SECRET` | orchestrator | 1 |
| `GITHUB_OAUTH_CLIENT_ID` | orchestrator | 1 |
| `GITHUB_OAUTH_CLIENT_SECRET` | orchestrator | 1 |
| `GITHUB_APP_ID` | orchestrator + bridge | 2 |
| `GITHUB_APP_PRIVATE_KEY` | orchestrator + bridge | 2 |
| `GITHUB_APP_WEBHOOK_SECRET` | orchestrator | 2 |
| `SPRITES_API_KEY` | orchestrator | 4 |
| `ANTHROPIC_API_KEY` | bridge | 6 |
| `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | orchestrator | 8 |
| `ORCHESTRATOR_PORT` | orchestrator | scaffold |
| `WEB_BASE_URL` | orchestrator (CORS, redirects) | scaffold |
| `ORCHESTRATOR_BASE_URL` | orchestrator (callback URL) | scaffold |
| `VITE_ORCHESTRATOR_BASE_URL` | web (build-time) | scaffold |

Vite gotcha: env file lives at the repo root, not [apps/web/](../apps/web/). [apps/web/vite.config.ts](../apps/web/vite.config.ts) sets `envDir: '../..'` so `import.meta.env.VITE_*` resolves correctly. Without that, [apps/web/src/lib/api.ts](../apps/web/src/lib/api.ts) throws at module load and the page is blank.

---

## 18. Slice plan — ordered rollout

Each slice is end-to-end verifiable. Slices stack — never start N+1 until N is approved by the user.

### Slice 0 — Scaffolding  ✅ done
Skeleton repo, placeholders, build/dev/test plumbing. Acceptance: [scaffold.md:583-602](scaffold.md#L583-L602).

### Slice 1 — GitHub OAuth + user persistence  ✅ code done, ⬜ verifying
Sign-in flow + `User`/`Session` collections + protected route convention. Acceptance: [slice1.md:611-637](slice/slice1.md#L611-L637).

**Active punch list to close it out:**
1. `uv sync --all-packages --all-extras`.
2. `docker compose up -d`.
3. `.env` populated (incl. real OAuth creds).
4. Restart `pnpm dev` (picks up Vite `envDir` fix + new env).
5. Walk the sign-in flow in a browser; verify `users` and `sessions` writes in Mongo.
6. `pnpm typecheck && pnpm lint && pnpm test` all green.
7. `pnpm --filter @vibe-platform/api-types gen:api-types` so [packages/api-types/generated/schema.d.ts](../packages/api-types/generated/schema.d.ts) is real, not the stub.
8. User reviews and approves; *only then* slice 2 brief is written.

### Slice 2 — OAuth `repo` scope + repo connection
**Adds:** expand slice 1's OAuth scope to include `repo`; persist the access token on `User`; `Repo` document; list-available / connect / disconnect endpoints backed by the user's OAuth token; web UI to pick repos and reconnect when the token is invalid. Repos are persisted but not cloned — connection is a logical state, not yet a sandbox state.
**Files:** route `repos.py`; `python_packages/github_integration/` filled in (thin OAuth-token client helper + `GithubReauthRequired` exception); web pages `/_authed/repos.tsx`, `/_authed/repos/connect.tsx` and a "Reconnect GitHub" affordance on the dashboard.
**Risks:** existing slice-1 sessions hold tokens without `repo` scope — must drive them through reconnect. Org SSO will block the user's token from accessing org repos until the user clicks "Authorize" per-org on GitHub. Storing the OAuth token in plain text in dev is a v1.1 followup (encrypt at rest).
**Acceptance:** signed-in user sees available repos → connects three → refresh → all three persist with `clone_status="pending"`; revoking the OAuth grant on GitHub causes the next repo call to return `403 github_reauth_required` and the UI surfaces a Reconnect button; reconnecting restores the list without losing already-connected `Repo` rows.

### Slice 3 — Repo introspection
**Adds:** on connect (and on `/reintrospect`), the orchestrator hits the GitHub Trees API for the repo and detects language/package manager/test command from filename heuristics, embeds `RepoIntrospection` on the `Repo` doc.
**Files:** `python_packages/repo_introspection/` filled in with detector functions per language.
**Risk:** filename heuristics miss frameworks that need real file contents (e.g., test command in `package.json` `scripts.test`). Start with tree-based detection; fall back to fetching the manifest blob when the tree match is ambiguous.
**Acceptance:** connecting a known TS repo populates `primary_language="TypeScript"`, `package_manager="pnpm"`, `test_command="pnpm test"`. Re-introspection updates the row.

### Slice 4 — Sandbox provisioning (the box exists)

**Scope-narrow rewrite.** This slice ends at "the box exists, REST endpoints work, idle-hibernation works." It does **not** include WS, bridge runtime, cloning, or reconciliation — those need WS, which lands in slice 5.

**Adds:** `FlySpritesProvider` implementing the `SandboxProvider` Protocol; `Sandbox` Mongo collection (one per user enforced at the orchestrator routing layer, NOT at the index — see §4 forward-compat note); Redis hash for hot state (`sandbox:{id} → {sprite_id, status, last_active_at}` — no queue yet, no active_run); REST endpoints `POST /api/sandboxes`, `GET /api/sandboxes`, `POST /api/sandboxes/{id}/wake`, `POST /api/sandboxes/{id}/hibernate`, `POST /api/sandboxes/{id}/destroy` (all parameterized by id from day one); idle-hibernation job (no active-run check yet — purely time-based for now); deterministic naming `vibe-sbx-{sandbox_id}` with the destroy/respawn collision strategy resolved (see §19 #14).
**Files:** `python_packages/sandbox_provider/src/sandbox_provider/sprites.py`; orchestrator `services/sandbox_manager.py`; `routes/sandbox.py`; `jobs/hibernate_idle.py`.
**Risks:** Sprites SDK churn (pin version explicitly — see §19 #9); Sprite naming collisions; per-Sprite cost (cap CPU/RAM/disk early — see §16); Sandbox doc creation timing (lazy on first `POST /api/sandboxes`, not eager at signup, to avoid orphaned docs).
**Acceptance:** for a fresh user with zero repos, `POST /api/sandboxes` creates a `Sandbox` doc with `status="none"` (or spawns immediately, depending on the brief's call). `POST /api/sandboxes/{id}/wake` calls `provider.spawn`, the Sprite enters `running` in Fly, `Sandbox.status="running"` in Mongo. `POST /api/sandboxes/{id}/hibernate` flips `Sandbox.status="hibernated"`. Idle-hibernation job hibernates a `running` sandbox after 10 minutes of no `last_active_at` updates. `POST /api/sandboxes/{id}/destroy` removes the Sprite and flips status to `destroyed`; existing `Repo` rows for the user are untouched.
**Out of scope:** any WS endpoint, any bridge runtime work, any cloning, any reconciliation, `Repo.sandbox_id` binding logic. Connect endpoint (slice 2) is unchanged — `clone_status` stays `pending`.

### Slice 5 — WebSocket transport + bridge runtime + reconciliation (the wire works, clones land)

This slice carries the load. It lands the entire wire protocol from §10, the long-lived bridge runtime from §14, and per-sandbox clone reconciliation. Big slice but cohesive: after slice 5, repos are warm-cloned in `/work/`.

#### Slice 5a — Control + events WS

**Adds:** WS server in orchestrator: `/ws/web/tasks/{task_id}` and `/ws/bridge/sandboxes/{sandbox_id}` (control + events channel only — see §10.2). Pydantic discriminated unions in `python_packages/shared_models/wire_protocol/` covering the §10.4–§10.6 message types. Bridge token issuance + verification (rotated on every wake; see §19 #10). Bridge `__main__.py` becomes a real long-lived WS client: dial-home, `ClientHello`, `Heartbeat`, replay-on-reconnect via `seq`, exponential-backoff reconnect loop (§10.8). Sticky-by-sandbox routing via `fly-replay` headers + Redis pub/sub fallback for cross-instance (§10.9). Backpressure rules from §10.8.
**Files:** `apps/orchestrator/src/orchestrator/ws/` (handlers, registry, sticky routing helpers); `apps/bridge/src/bridge/lifecycle/` (boot, dial-home, reconnect loop); `python_packages/shared_models/wire_protocol/` (message types + codegen for TS).
**Risks:** keeping wire schemas in sync between Pydantic and TS — codegen step on schema change. Sticky routing is the load-bearing operational invariant — a regression here means cross-talk, not just slowness; integration test it explicitly with two orchestrator instances behind a fake LB.
**Acceptance:** spawned Sprite dials home; `Sandbox.bridge_version` populates; `Heartbeat` updates `last_active_at` every 30s; `ClientHello` is acked with `ServerHello`; killing the bridge process triggers the reconnect loop and a fresh `ClientHello` arrives. Killing the orchestrator instance routing a sandbox triggers `fly-replay` to land the bridge on a new instance, replay catches the web subscriber up via `seq`.

#### Slice 5b — Reconciliation + clone

**Adds:** `EnsureRepoCloned` / `RemoveRepo` directives + bridge handlers that clone into `/work/<full_name>/` using a per-repo install token minted at directive time (see §19 #12). Reconciliation logic on `ClientHello`: orchestrator diffs `Repo` rows where `sandbox_id == this.sandbox_id` against the bridge's reported `cloned_repos`, issues directives until convergent. Connect endpoint (slice 2) gains a clone enqueue when the user's sandbox is up; sets `Repo.sandbox_id` to the user's singleton sandbox id; `clone_status` flips `pending → cloning → ready`. Disconnect endpoint issues `RemoveRepo`. Disk-cap + eviction job (§16, §19 #15).
**Files:** `apps/bridge/src/bridge/clones/` (clone helpers, all path-scoped to `/work/<full_name>/`); `apps/orchestrator/src/orchestrator/services/reconciliation.py`; `apps/orchestrator/src/orchestrator/jobs/disk_eviction.py`.
**Risks:** reconciliation correctness — test the four-quadrant matrix explicitly (see §19 #13). Token leakage in `.git/config` — extraheader at command time, never persist (§19 #12). Race between connect and bridge boot — `EnsureRepoCloned` queued in Mongo until next `ClientHello`.
**Acceptance:** connect three repos against a running sandbox; all three end up cloned to `/work/<full_name>/`, `clone_status="ready"`, `Repo.sandbox_id` populated. Disconnect one → directory removed, row deleted. Force-restart the bridge → `ClientHello` reports two cloned repos, no directives issued (already convergent). Manually `rm -rf /work/<full_name>/` inside the Sprite + restart bridge → reconciliation issues `EnsureRepoCloned`, repo re-clones.

### Slice 6 — Tasks + Agent SDK invocation
**Adds:** `Task` + `AgentRun` + `AgentEvent` collections; task creation (against any connected repo) + follow-up endpoints; orchestrator queues runs into the user's sandbox (one active at a time per sandbox, queue depth surfaced in UI); bridge's real agent loop (`cd /work/<full_name>`, branch, Agent SDK with tool allowlist, stream events); web task page (chat, event stream, status, repo picker).
**Files:** `apps/orchestrator/src/orchestrator/routes/tasks.py`; `apps/bridge/src/bridge/agent/` (agent invocation + tools); `python_packages/agent_config/dev_agent/` (system prompts).
**Risks:** agent tool budgets and tight loops; cost cap per run; ensuring `run_shell` truly stays inside the *correct* repo subdir for the run (not the sandbox root); queue starvation if a single run loops forever.
**Acceptance:** with two connected repos, filing "add a top-level `HELLO.md` saying hi" against repo A produces `AgentEvent`s, a commit on a new branch *in repo A only*, and a `StatusChangeEvent("completed")`. `/work/<repo_b>/` is untouched. Filing a second task while the first is running queues; queue depth shows in the UI.

### Slice 7 — Git ops + PR creation
**Adds:** `git push` + `repos.create_pull_request` via githubkit; PR URL surfaced in `Task` + UI; subsequent follow-ups push more commits to the same branch in the same repo subdir.
**Files:** `apps/bridge/src/bridge/git/` (push helpers, all path-scoped to `/work/<full_name>/`); `apps/bridge/src/bridge/agent/finalize.py` (post-agent push + PR open).
**Risk:** auth token leakage in `.git/config` — set extraheader at command time, never persist. Different repos in the same sandbox can have different installation tokens (different orgs); the orchestrator must mint per-repo tokens at `StartRun` time and pass them in the `StartRun` message, not at sandbox spawn.
**Acceptance:** the slice 6 task ends with a real PR opened against the connected repo, linked from the task page. A follow-up message produces a second commit on the same PR.

### Slice 8 — Interactive coding surface (PTY + file ops)

**New slice — splits "interactive user actions" out of the agent-run loop.** After slice 7 the agent can ship PRs; this slice gives the user the direct-interaction surface that makes the product feel like an editor: open a terminal, edit a file, see live agent edits as they happen.

**Adds:** PTY WS endpoints `/ws/web/sandboxes/{id}/pty/{terminal_id}` + `/ws/bridge/sandboxes/{id}/pty/{terminal_id}` (binary, separate connections per §10.2). Bridge-side PTY spawn (`pty.openpty()` + subprocess in the relevant repo subdir). Web-side xterm.js terminal component. File ops REST endpoints (`GET/PUT /api/sandboxes/{id}/fs?path=...`) with bridge-side handlers. Live `FileEditEvent` stream from the agent's edits, surfaced in a diff view in the web task page (coalesced ≤4 Hz per path per §10.8).
**Files:** `apps/orchestrator/src/orchestrator/ws/pty.py`, `routes/sandbox_fs.py`; `apps/bridge/src/bridge/pty/`; `apps/web/src/components/Terminal.tsx`, `FileEditor.tsx`.
**Risks:** PTY back-pressure under bursty logs (drop frames per §10.8); path-traversal in file-ops (validate all paths under `/work/<full_name>/`); large file uploads (cap at 10 MB per request, stream); terminal scrollback expectations (we don't replay PTY history — document this).
**Acceptance:** open a terminal on a connected repo's subdir; type `pnpm test`, see streaming output at sub-100ms latency; close the tab and reopen — terminal is fresh (no scrollback). Open a file, edit it in the web editor, save → roundtrip works and is reflected on disk in the Sprite. Run an agent task that edits a file → live diff streams to the open file editor.

### Slice 9 — HTTP preview proxy

**Adds:** subdomain-based HTTP forwarder so a dev server running inside a Sprite at `localhost:3000` is reachable at `https://sandbox-{id}.preview.<domain>/...` from the user's browser. Auth-gated (only the sandbox's owner can reach the preview). Falls back to the orchestrator on demand for sandboxes whose Sprites aren't directly reachable from the public internet.
**Files:** `apps/orchestrator/src/orchestrator/routes/preview.py` (proxy handler); a small DNS / Fly route shim.
**Risks:** secrets in dev-server output; CSP/iframe issues if we want to embed the preview in our UI; cookie-domain leakage. Probably ship preview-in-new-tab first, embed later.
**Acceptance:** user runs `pnpm dev` in a sandbox terminal; clicks "Open preview" in the UI; new tab loads the dev server on the preview subdomain.

### Slice 10 — Event log persistence (S3)

**Adds:** archival job that, on `AgentRun` completion, writes the run's events to `s3://{S3_BUCKET}/runs/{run_id}.ndjson` and prunes from Mongo (keeping the last N for active UI hydration). `GET /api/tasks/{task_id}/events` paginates Mongo + S3 transparently.
**Files:** `apps/orchestrator/src/orchestrator/jobs/archive_run.py`; `services/event_store.py`.
**Risk:** S3 vs MinIO config drift — keep the client behind an interface.
**Acceptance:** completed run's events disappear from Mongo and reappear when paginating in UI; S3 object exists.

### Future / deferred (post-v1)

- Vibe mode (greenfield, multi-agent)
- Teams / orgs
- Billing
- Email + Slack notifications
- Mobile app
- Sentry / metrics
- Auto-regen of api-types on backend change
- Branch protection rules and review-gating

---

## 19. Risks & known gotchas

1. **`uv sync` flags** — bare `uv sync` only installs the root, not the workspace members. Always `uv sync --all-packages --all-extras`. Documented in [slice1.md:15](slice/slice1.md#L15) and [TESTING.md](TESTING.md).
2. **Vite envDir** — `.env` lives at repo root; [apps/web/vite.config.ts](../apps/web/vite.config.ts) must set `envDir: '../..'`. Without it, `import.meta.env.VITE_*` is undefined and [apps/web/src/lib/api.ts:4](../apps/web/src/lib/api.ts#L4) throws → blank page.
3. **OAuth App ≠ GitHub App** — different artifacts, both in the "Developer settings" menu. Slice 1 needs only the OAuth App; slice 2 adds the GitHub App. ([slice1.md:643-646](slice/slice1.md#L643-L646))
4. **Beanie `init_beanie` registration** — adding a `Document` class without registering it in [python_packages/db/src/db/connect.py](../python_packages/db/src/db/connect.py)'s `document_models` list silently fails to query. ([engineering.md:94](engineering.md#L94))
5. **`datetime.utcnow()`** — deprecated in Python 3.12, fails Pyright strict. Use `datetime.now(UTC)` via a `_now()` helper. ([engineering.md:99](engineering.md#L99))
6. **DB shape vs API shape** — never reuse a Beanie `Document` as a FastAPI `response_model`. The split is intentional. ([engineering.md:33-38](engineering.md#L33-L38))
7. **`pytest` event loop** — DB-touching tests must use the `httpx.AsyncClient + ASGITransport` fixture, not FastAPI's `TestClient`. ([TESTING.md:165](TESTING.md#L165))
8. **Webhook delivery in local dev** — slice 2 needs a public URL for GitHub webhooks. Use smee.io or ngrok. Document in the slice 2 brief.
9. **Sprites SDK pinning** — slice 4 should pin the Sprites SDK version explicitly; SDK churn is a known supply-chain risk on early-stage providers.
10. **Bridge token (slice 5a)** — long-lived per sandbox, not per run. Rotate on every wake; bridge re-auths after every hibernate/resume. Treat as signed JWTs with TTL ≤ sandbox idle window.
11. **Per-user sandbox = noisy-neighbor surface** — all of one user's tasks share one Sprite. v1 limits this to one active run at a time per sandbox (queue the rest). Hard cap Sprite CPU/RAM/disk early so a single user can't cost-spiral.
12. **Multi-repo install token scoping** — different repos in the same sandbox can be on different GitHub App installations (different orgs). Mint **per-repo, per-run** install tokens at `StartRun` time; never share a token across repos or persist it on the sandbox disk.
13. **Reconciliation correctness on `ClientHello`** — the diff between `Repo` rows where `sandbox_id == this.sandbox_id` and `cloned_repos` reported by the bridge must converge: missing on disk → `EnsureRepoCloned`; on disk but not bound to this sandbox → `RemoveRepo`. Reconciliation is per-sandbox, never per-user. Test the four-quadrant matrix explicitly in slice 4.
14. **Sandbox name collisions** — `vibe-sbx-{user_id}` is deterministic; if `/api/sandbox/destroy` is called and a new spawn happens immediately, Sprites may still hold the old name. Either wait for full destroy or include a salt suffix; decide in slice 4.
15. **`/work` quota and warm-cache bloat** — `node_modules` per repo plus `.venv` plus pip cache will grow. Slice 5b sets a per-sandbox disk cap and a `du`-based eviction job; don't ship without it or the first heavy user wedges their own sandbox.

16. **Transport choice — WS, not gRPC** — locked in §10.1. Don't reach for gRPC unless production telemetry shows ≥8 concurrent streaming channels per sandbox. The "obvious" gRPC win (HTTP/2 stream multiplexing) is dwarfed by the cost of running two type-bridge systems.

17. **One transport, multiple connections per concern** — control + events on a single WS; PTY on its own WS per terminal; file ops via REST. **Don't** multiplex PTY onto the control WS — head-of-line blocking on a 10 MB log will freeze keystrokes. See §10.2.

18. **Heartbeat is application-level, not TCP-level** — 30s `Ping`/`Pong` with `nonce` on every WS, 90s timeout. TCP keepalive only detects dead TCP, not dead app event loops. See §10.8.

19. **Idempotent directives or pain** — every bridge-bound directive (`EnsureRepoCloned`, `RemoveRepo`, `StartRun`, `OpenPty`, `HibernateSandbox`) carries a `directive_id` and is safe to re-deliver after reconnect. The bridge tracks the last 100 it processed and returns the cached ack on duplicates. See §10.8.

20. **Sticky-by-sandbox routing is load-bearing** — at multi-instance scale, both the bridge for sandbox X and the web client(s) watching X must land on the same orchestrator instance. Use Fly `fly-replay` keyed on `sandbox_id` hash; Redis pub/sub on `sandbox:{id}` is the slow-path fallback only. Test with two orchestrator instances behind a fake LB. See §10.9.

21. **Backpressure has explicit caps and an explicit drop policy** — orchestrator buffers ≤1000 events per (run, web subscriber); bridge buffers ≤5 MB pending events; PTY drops frames under back-pressure (terminals can drop, agent events can't because of `seq`-replay). Never grow buffers unbounded; alert on drops. See §10.8.

22. **Reconnect backoff has jitter** — bridge: `1, 2, 4, 8, 16, 30, 30…` seconds with ±25%; web: `0.5, 1, 2, 4, 8, 16, 30…` with ±25%. Without jitter, an orchestrator restart causes a thundering-herd reconnect spike. See §10.8.

23. **Capacity caps + hot-shedding** — each orchestrator instance soft-caps at 5000 WS connections. New sandbox spawns get 503 if no instance has headroom; existing connections aren't degraded. See §10.9.

---

## 20. Status snapshot (as of 2026-05-01)

- **Slice 0** ✅ scaffolding shipped
- **Slice 1** ✅ shipped (GitHub OAuth + user persistence)
- **Slice 2** ✅ shipped (OAuth `repo` scope + repo connection)
- **Slice 3** ✅ shipped (repo introspection — Trees + Contents detection, dev_command, per-field user overrides)
- **Slice 4** ⬜ next — sandbox provisioning (the box exists; no WS yet)
- **Slices 5a / 5b / 6 – 10** ⬜ not started; briefs to be authored slice-by-slice. Note the new split: §18 was rewritten on 2026-05-01 to peel transport+clone (slice 5a/5b) apart from provisioning (slice 4) and to add slice 8 (PTY + file ops) and slice 9 (HTTP preview proxy). The old slice 8 (event-log persistence) is now slice 10.

Repo metrics (from latest [`/graphify`](../graphify-out/GRAPH_REPORT.md) run, 2026-05-01): **107 files (~75k words) · 443 nodes · 633 edges · 89 communities**. Extraction quality: 76% EXTRACTED · 24% INFERRED (avg confidence 0.71) · 0% AMBIGUOUS. Top community hubs reflect the shipped slices 0–3: *Repo Introspection Architecture / Tests*, *Command Detection*, *Package Manager Detection*, *Primary Language Detection*, *FastAPI App & Health*, *GitHub OAuth Wrapper*, *Mongo Lifecycle & Collections*, *Repo Models & Sandbox API*, *Type Bridges (Pydantic→TS)*, *Frontend Repo API Client / Query Hooks*, *Project Docs & Slice Discipline*, *Risks & Gotchas*. Use `/graphify --update` (incremental, cheap) after every shipped slice; full rebuild only when the user asks. See [AGENTS.md §2.7](../AGENTS.md) for query workflow and verification rules.

---

## 21. Concrete next steps (do these in order)

1. **Close slice 1 verification** — punch list under §18 / Slice 1.
2. **Author `slice2.md`** following the same shape as [slice1.md](slice/slice1.md): context, scope, what to build, hard rules, acceptance criteria, when-done summary template.
3. **Register the GitHub App** (manual) on GitHub developer settings; copy `GITHUB_APP_ID`, generate and store the private key, set the webhook secret. Add to `.env`.
4. **Implement slice 2** per the brief.
5. Repeat for slices 3 → 8.

Do **not** start slice 2 implementation before the brief exists and the user reviews it. The hard rule from [slice1.md:665](slice/slice1.md#L665) — "do not start the next task automatically" — applies for every slice transition.
