# Plan.md — vibe-platform

End-to-end design and rollout plan for the platform. Source of truth for *what* we're building, *why* the boundaries are where they are, and *the order things ship in*. Live document — slice briefs override it where they conflict, but new design decisions land here first.

> Companion docs: [scaffold.md](scaffold.md) (skeleton), [slice1.md](slice1.md) (auth slice), [TESTING.md](TESTING.md) (verification), [CONTRIBUTING.md](CONTRIBUTING.md) (change flow), [CLAUDE.md](CLAUDE.md) (agent rules).

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
- ⬜ Install the **vibe-platform GitHub App** on one or more accounts/orgs
- ⬜ See repos the App has access to and **connect any number of them** to their personal sandbox
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
                        │  github_installations · tasks │
                        │  agent_runs · agent_events    │
                        └──────────────┬────────────────┘
                                       │ Beanie (Motor async)
                                       │
┌──────────────┐  HTTPS + WSS  ┌───────▼───────────────┐  Sprites API   ┌────────────────────────┐
│  apps/web    │ ◄───────────► │  apps/orchestrator    │ ─────────────► │   Fly.io Sprite        │
│  Vite SPA    │               │  FastAPI + uvicorn    │   (REST)       │   (one per user)       │
│  React 18    │               │                       │                │                        │
│  TanStack    │               │  - Auth (Authlib)     │                │  /work/                │
│  Tailwind    │               │  - GitHub App +       │ ◄── WSS ────►  │   ├── repo-a/  (clone) │
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

Why this shape:

- Sandbox isolation is non-negotiable — the agent runs untrusted-ish code (tests, package installs) and must not touch the orchestrator or other users' data.
- One sandbox per user means each user's repos live alongside each other — natural fit for cross-repo refactors later, and warm `node_modules` / `.venv` between tasks on the same repo.
- Single ingress (orchestrator) for auth, rate limiting, and secret management.
- WebSocket as the bidirectional channel means the orchestrator can push UI updates in real time AND issue control commands (pause, abort, send-follow-up-message) without the bridge polling.

---

## 5. Tech stack — locked in (see [CLAUDE.md](CLAUDE.md))

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

### Banned (do not introduce — see [CLAUDE.md](CLAUDE.md))

Hono, Express, tRPC, Drizzle, Bun, Next.js, Prisma, Clerk, Better Auth, Poetry, conda, rye, npm, yarn, mypy, black, isort, flake8.

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
├── README.md, CONTRIBUTING.md, TESTING.md, CLAUDE.md, scaffold.md, slice1.md
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

### `github_installations` (slice 2)
One per (user, GitHub App installation). Lets us hit the GitHub API on the user's behalf via the App.
```python
class GithubInstallation(Document):
    user_id: PydanticObjectId
    installation_id: Annotated[int, Indexed(unique=True)]
    account_login: str            # "torvalds" or "octo-org"
    account_type: Literal["User", "Organization"]
    repository_selection: Literal["all", "selected"]
    created_at: datetime
    updated_at: datetime
    class Settings: name = "github_installations"
```

### `repos` (slice 2)
A repo the user has connected. Lives inside their sandbox under `/work/<full_name>/` once cloned.
```python
class Repo(Document):
    user_id: PydanticObjectId
    installation_id: int          # → GithubInstallation.installation_id
    github_repo_id: Annotated[int, Indexed(unique=True)]
    full_name: str                # "octo-org/repo-name"
    default_branch: str
    private: bool
    introspection: RepoIntrospection | None  # filled by slice 3
    clone_status: Literal["pending","cloning","ready","failed"]  # state of the clone in sandbox
    clone_path: str | None        # "/work/octo-org/repo-name"
    last_synced_at: datetime | None  # last `git fetch` against origin
    connected_at: datetime
    class Settings: name = "repos"
```

### `sandboxes` (slice 4)

**One per user.** Holds the sandbox-side state that needs to survive orchestrator restarts (Redis is the hot cache; this is the source of truth).

```python
class Sandbox(Document):
    user_id: Annotated[PydanticObjectId, Indexed(unique=True)]  # 1:1 with User
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
A user-filed unit of work against one of the user's connected repos. Tasks always run in the user's single sandbox.
```python
class Task(Document):
    user_id: PydanticObjectId
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

- All `*_at` fields use `datetime.now(UTC)` via a `_now()` helper. Never `datetime.utcnow()` (deprecated, fails Pyright strict). See [CONTRIBUTING.md:99](CONTRIBUTING.md#L99).
- Every uniquely-keyed field uses `Annotated[T, Indexed(unique=True)]`.
- Every `Document` must be registered in [python_packages/db/src/db/connect.py](python_packages/db/src/db/connect.py)'s `init_beanie(document_models=[...])` list, or it will silently not be queryable.

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

### GitHub installation (slice 2)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/github/install-url` | Returns the GitHub App install URL with state. |
| POST | `/api/github/installations/refresh` | Re-fetches installations from GitHub for this user, upserts. |
| GET | `/api/github/installations` | `list[InstallationResponse]`. |
| POST | `/api/github/webhook` | Webhook endpoint for App events (installation, installation_repositories). HMAC-verified via `GITHUB_APP_WEBHOOK_SECRET`. **Public, signature-checked.** |

### Repos (slice 2 + 3)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/repos/available` | Repos accessible via any installation, not yet connected. |
| GET | `/api/repos` | Connected repos for this user (with `clone_status` per repo). |
| POST | `/api/repos/connect` | Body `{installation_id, github_repo_id}`. Creates `Repo`, ensures sandbox is up, **enqueues clone into the user's sandbox**, kicks off introspection (slice 3). |
| DELETE | `/api/repos/{repo_id}` | Disconnect: removes the clone from the sandbox (`rm -rf /work/<full_name>/`), deletes `Repo`, leaves the sandbox + other repos untouched. |
| POST | `/api/repos/{repo_id}/reintrospect` | Re-run introspection. (slice 3) |
| POST | `/api/repos/{repo_id}/sync` | `git fetch` against origin in the sandbox; updates `last_synced_at`. |

### Sandbox (slice 4)

The sandbox is per-user; these endpoints operate on `current_user`'s sandbox implicitly. No `{sandbox_id}` in the path.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/sandbox` | Returns `SandboxResponse` — status, sprite_id, last_active_at, region, list of cloned repo paths. |
| POST | `/api/sandbox/wake` | Spawn (if `none`/`destroyed`) or resume (if `hibernated`). Idempotent if already running. |
| POST | `/api/sandbox/hibernate` | Force hibernate now. |
| POST | `/api/sandbox/destroy` | Destroys the Sprite. Repos remain in `repos` collection but `clone_status="pending"` until next wake. |

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

Single endpoint per role:

- `/ws/web/tasks/{task_id}` — web client subscribes to a task. Auth via session cookie (FastAPI `Depends` on the WS handshake).
- `/ws/bridge/sandboxes/{sandbox_id}` — the bridge in a Sprite dials this **once per sandbox lifetime**. Auth via a long-lived **bridge token** issued at sandbox spawn (rotatable; not per-run).

All messages are Pydantic discriminated unions in `python_packages/shared_models/wire_protocol/`. Discriminator field: `type`. Most event messages now carry `run_id` since the bridge multiplexes runs over one connection.

### Bridge → orchestrator

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
Heartbeat                { type, last_active_at }
```

Orchestrator responsibilities on receive:

1. Persist `*Event` as `AgentEvent` keyed by `run_id` (monotonic `seq`).
2. Fan out to web subscribers on the same task.
3. Update parent `AgentRun.status` / `Task.status` on terminal events.
4. Update `Repo.clone_status` and `Sandbox.last_active_at` on `RepoCloneStatus` / `Heartbeat`.

### Orchestrator → bridge

```
ServerHello              { type, tool_allowlist, agent_defaults }
EnsureRepoCloned         { type, full_name, base_branch, install_token }
RemoveRepo               { type, full_name }
StartRun                 { type, run_id, task_id, repo_full_name, base_branch, prompt, follow_up, install_token }
UserFollowUpMessage      { type, run_id, content }
AbortRun                 { type, run_id, reason }
HibernateSandbox         { type }                                  # bridge flushes, exits cleanly
```

### Web → orchestrator → web

The orchestrator transcodes `AgentEvent`s into a UI-friendly schema (`TaskEventForUI`) and pushes them down. Web clients send only `SendFollowUp` and `CancelTask` over WS; everything else is HTTP.

### Reliability

- Both sides hold a **monotonic seq**. After reconnect, web sends `Resume{after_seq}` and the orchestrator replays from Mongo.
- 60s ping/pong; either side closes after 2 missed pings.
- Backpressure: orchestrator buffers up to 1000 events per (run, web subscriber); slow consumers get dropped with a warning.

---

## 11. Authentication & session model (slice 1 — implemented)

- **Provider**: GitHub OAuth only. No email/password, no other providers, no email transport.
- **Library**: Authlib `AsyncOAuth2Client` for the OAuth dance. Sessions are ours.
- **Session ID**: `secrets.token_urlsafe(32)`. Stored in `Session.session_id` and as the `vibe_session` cookie value. Nothing else in the cookie.
- **Cookie**: `httponly=True`, `secure=is_production`, `samesite="lax"`, `max_age=7d`, `path="/"`.
- **CSRF for OAuth flow**: a second short-lived cookie `vibe_oauth_state` (10 min, samesite=lax) holds a `secrets.token_urlsafe(32)` state token. Verified and cleared on callback.
- **Scope**: `read:user user:email`. **Not** `repo` — repo access comes via the GitHub App, not the OAuth App.
- **Lookup path**: every request → read cookie → load `Session` → check `expires_at` → load `User` → bump `last_used_at`. Implemented as the FastAPI dependency `require_user` in [apps/orchestrator/src/orchestrator/middleware/auth.py](apps/orchestrator/src/orchestrator/middleware/auth.py). Optional variant `get_user_optional` returns `None` instead of raising.

Hard rules (from [slice1.md:643-651](slice1.md#L643-L651)):

- No second auth library.
- No email transport, ever.
- No data in cookies — opaque session ID only.
- Never skip the `require_user` dependency on protected routes.

---

## 12. GitHub integration (slice 2)

Two distinct GitHub artifacts, easy to confuse:

| | OAuth App (slice 1) | GitHub App (slice 2) |
|---|---|---|
| Purpose | Identify the human | Act on repos |
| Scope | `read:user user:email` | Per-installation repo permissions |
| Install where | Auto on auth | User clicks "Install" per account/org |
| Acts as | The user (with their token) | The App itself (installation token) |

Slice 2 work:

1. Register a single platform-wide GitHub App with the user (manual, README docs the steps). Required permissions: **Contents (read/write), Pull requests (read/write), Metadata (read)**. Subscribe to `installation`, `installation_repositories` events.
2. Place credentials in `.env`: `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_WEBHOOK_SECRET`.
3. Install URL = `https://github.com/apps/<slug>/installations/new?state=<csrf>`.
4. Webhook handler validates HMAC, upserts `GithubInstallation` rows.
5. List "available repos" by minting an installation token per installation, calling `GET /installation/repositories`.
6. Connect: persist `Repo`, fire off introspection.

Tokens are never persisted long-term — installation tokens are 1-hour, minted per request via githubkit.

---

## 13. Sandbox lifecycle (slice 4)

**One persistent sandbox per user.** It hosts every connected repo of that user under `/work/<full_name>/` and serves every agent run. It outlives individual tasks; it does not outlive the user account.

[`SandboxProvider` Protocol](python_packages/sandbox_provider/src/sandbox_provider/interface.py) — currently has TODO methods. To implement:

```python
class SandboxProvider(Protocol):
    async def spawn(self, *, user_id: PydanticObjectId, env: dict[str,str]) -> SandboxHandle: ...
    async def resume(self, sprite_id: str) -> SandboxHandle: ...
    async def hibernate(self, sprite_id: str) -> None: ...
    async def destroy(self, sprite_id: str) -> None: ...
    async def exec(self, sprite_id: str, cmd: list[str], cwd: str | None = None) -> ExecResult: ...
    async def clone_repo(self, sprite_id: str, *, full_name: str, base_branch: str, install_token: str) -> None: ...
    async def remove_repo(self, sprite_id: str, *, full_name: str) -> None: ...
```

Concrete impl: `FlySpritesProvider`, calling Fly Sprites REST API with `SPRITES_API_KEY`. One Sprite **per user**, identified in Sprites by a deterministic name like `vibe-sbx-{user_id}`.

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
4. Reconcile clones: orchestrator compares `cloned_repos` to the user's `repos` collection and issues `EnsureRepoCloned` / `RemoveRepo` directives until the disk matches the desired state.
5. Enter the run loop.

### Run loop (per agent run)

1. Receive `StartRun{run_id, task_id, repo_full_name, base_branch, prompt, follow_up: bool, install_token}` from orchestrator.
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
- Repo bootstrap (slice 4 onward, on `EnsureRepoCloned`): `git clone --filter=blob:none https://x-access-token:<install_token>@github.com/<full_name>.git /work/<full_name>` — partial clone for fast first-pull on big repos. Then `git remote set-url origin https://github.com/<full_name>.git` to scrub the token.
- Branch naming: `vibe/task-{slug}` where `slug` is 8 chars of the task id. Run 1 creates it; follow-up runs check it out and add commits.
- Commit messages: agent generates them; bridge appends `Co-Authored-By: vibe-platform <bot@vibe.dev>`.
- Push: HTTPS with installation token via `git -c http.extraheader="AUTHORIZATION: bearer <install_token>" push`. Token never written to `.git/config`.
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

This rewrites [packages/api-types/generated/schema.d.ts](packages/api-types/generated/schema.d.ts). The frontend picks up the new types on next typecheck. **Auto-regen on backend change is intentionally deferred** — the manual two-terminal step is fine for v1.

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

## 17. Environment variables (full v1 set; see [.env.example](.env.example))

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

Vite gotcha: env file lives at the repo root, not [apps/web/](apps/web/). [apps/web/vite.config.ts](apps/web/vite.config.ts) sets `envDir: '../..'` so `import.meta.env.VITE_*` resolves correctly. Without that, [apps/web/src/lib/api.ts](apps/web/src/lib/api.ts) throws at module load and the page is blank.

---

## 18. Slice plan — ordered rollout

Each slice is end-to-end verifiable. Slices stack — never start N+1 until N is approved by the user.

### Slice 0 — Scaffolding  ✅ done
Skeleton repo, placeholders, build/dev/test plumbing. Acceptance: [scaffold.md:583-602](scaffold.md#L583-L602).

### Slice 1 — GitHub OAuth + user persistence  ✅ code done, ⬜ verifying
Sign-in flow + `User`/`Session` collections + protected route convention. Acceptance: [slice1.md:611-637](slice1.md#L611-L637).

**Active punch list to close it out:**
1. `uv sync --all-packages --all-extras`.
2. `docker compose up -d`.
3. `.env` populated (incl. real OAuth creds).
4. Restart `pnpm dev` (picks up Vite `envDir` fix + new env).
5. Walk the sign-in flow in a browser; verify `users` and `sessions` writes in Mongo.
6. `pnpm typecheck && pnpm lint && pnpm test` all green.
7. `pnpm --filter @vibe-platform/api-types gen:api-types` so [packages/api-types/generated/schema.d.ts](packages/api-types/generated/schema.d.ts) is real, not the stub.
8. User reviews and approves; *only then* slice 2 brief is written.

### Slice 2 — GitHub App + repo connection
**Adds:** GitHub App registration (manual), `GithubInstallation` + `Repo` documents, install/list/connect/disconnect endpoints, webhook handler with HMAC verification, web UI to install + pick **multiple** repos. Repos are persisted but not yet cloned anywhere — connection is a logical state, not yet a sandbox state.
**Files:** routes `repos.py`, `github.py`; `python_packages/github_integration/` filled in (App JWT minting, installation token cache, webhook signature verifier); web pages `/_authed/repos.tsx`, `/_authed/repos/connect.tsx`.
**Risks:** webhook delivery in local dev (use `smee.io` or ngrok; doc this in README). N-to-1 between repos and the user's eventual sandbox needs UI affordance — show "(connected, awaiting sandbox)" until slice 4 lands.
**Acceptance:** install App → see installation → see available repos → connect three → refresh → all three persist; webhook event for installation arrives and is logged; disconnect removes one without affecting the others.

### Slice 3 — Repo introspection
**Adds:** on connect (and on `/reintrospect`), the orchestrator hits the GitHub Trees API for the repo and detects language/package manager/test command from filename heuristics, embeds `RepoIntrospection` on the `Repo` doc.
**Files:** `python_packages/repo_introspection/` filled in with detector functions per language.
**Risk:** filename heuristics miss frameworks that need real file contents (e.g., test command in `package.json` `scripts.test`). Start with tree-based detection; fall back to fetching the manifest blob when the tree match is ambiguous.
**Acceptance:** connecting a known TS repo populates `primary_language="TypeScript"`, `package_manager="pnpm"`, `test_command="pnpm test"`. Re-introspection updates the row.

### Slice 4 — Sandbox provider (Sprites) — **per-user, multi-repo**

**Adds:** `FlySpritesProvider` implementing the `SandboxProvider` Protocol; `Sandbox` Mongo collection (1:1 with User); Redis-backed hot state; `/api/sandbox/{wake,hibernate,destroy}` and `/api/sandbox` endpoints; idle-hibernation job; reconciliation step on bridge `ClientHello` that diffs the user's connected `repos` against `cloned_repos` reported by the bridge and issues `EnsureRepoCloned`/`RemoveRepo`. Per-repo connection (slice 2) gains a clone enqueue when the sandbox is up.
**Files:** `python_packages/sandbox_provider/src/sandbox_provider/sprites.py`; orchestrator `services/sandbox_manager.py`; `routes/sandbox.py`; `jobs/hibernate_idle.py`.
**Risks:** Sprites SDK churn; Redis schema must survive orchestrator restarts (Mongo is the source of truth); ensuring the deterministic `vibe-sbx-{user_id}` Sprite name doesn't collide if a user is fully destroyed and re-created. Cap Sprite size early (CPU/RAM/disk) to keep cost predictable.
**Acceptance:** for a fresh user with zero repos, `POST /api/sandbox/wake` spawns a Sprite, the bridge dials WS, `Sandbox.status` becomes `"running"`. Connecting two repos triggers two `EnsureRepoCloned` directives; each becomes `clone_status="ready"` with a path under `/work/`. `POST /api/sandbox/hibernate` flips status to `"hibernated"`. `POST /api/sandbox/wake` resumes; `cloned_repos` in the next `ClientHello` lists both.

### Slice 5 — WebSocket transport (orchestrator ↔ bridge ↔ web)
**Adds:** WS server in orchestrator with two endpoints (`/ws/web/tasks/{task_id}`, `/ws/bridge/sandboxes/{sandbox_id}`), Pydantic discriminated unions for messages in `python_packages/shared_models/wire_protocol/`, replay-on-reconnect via `seq`, bridge token issuance and verification, ping/pong heartbeat. Bridge's `__main__.py` becomes a real WS client: long-lived, `ClientHello`-with-cloned-repos, ack of `EnsureRepoCloned`/`RemoveRepo` directives, dummy `StartRun` echo for the smoke test.
**Files:** `apps/orchestrator/src/orchestrator/ws/`; `apps/bridge/src/bridge/lifecycle/`; expanded `shared_models/wire_protocol/`.
**Risk:** keeping wire schemas in sync between Pydantic and TS — solve by codegen step running on schema change. Document the codegen exactly like for HTTP types. Bridge token rotation strategy needs to be settled (re-issue on every wake; bridge re-auths after every hibernate/resume cycle).
**Acceptance:** spawning a Sprite + connecting a repo + sending an internal-only `StartRun` to that sandbox shows the placeholder events streaming to a web subscriber on the matching task page; reconnect replays from `seq`.

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

### Slice 8 — Event log persistence (S3)
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

1. **`uv sync` flags** — bare `uv sync` only installs the root, not the workspace members. Always `uv sync --all-packages --all-extras`. Documented in [slice1.md:15](slice1.md#L15) and [TESTING.md](TESTING.md).
2. **Vite envDir** — `.env` lives at repo root; [apps/web/vite.config.ts](apps/web/vite.config.ts) must set `envDir: '../..'`. Without it, `import.meta.env.VITE_*` is undefined and [apps/web/src/lib/api.ts:4](apps/web/src/lib/api.ts#L4) throws → blank page.
3. **OAuth App ≠ GitHub App** — different artifacts, both in the "Developer settings" menu. Slice 1 needs only the OAuth App; slice 2 adds the GitHub App. ([slice1.md:643-646](slice1.md#L643-L646))
4. **Beanie `init_beanie` registration** — adding a `Document` class without registering it in [python_packages/db/src/db/connect.py](python_packages/db/src/db/connect.py)'s `document_models` list silently fails to query. ([CONTRIBUTING.md:94](CONTRIBUTING.md#L94))
5. **`datetime.utcnow()`** — deprecated in Python 3.12, fails Pyright strict. Use `datetime.now(UTC)` via a `_now()` helper. ([CONTRIBUTING.md:99](CONTRIBUTING.md#L99))
6. **DB shape vs API shape** — never reuse a Beanie `Document` as a FastAPI `response_model`. The split is intentional. ([CONTRIBUTING.md:33-38](CONTRIBUTING.md#L33-L38))
7. **`pytest` event loop** — DB-touching tests must use the `httpx.AsyncClient + ASGITransport` fixture, not FastAPI's `TestClient`. ([TESTING.md:165](TESTING.md#L165))
8. **Webhook delivery in local dev** — slice 2 needs a public URL for GitHub webhooks. Use smee.io or ngrok. Document in the slice 2 brief.
9. **Sprites SDK pinning** — slice 4 should pin the Sprites SDK version explicitly; SDK churn is a known supply-chain risk on early-stage providers.
10. **Bridge token (slice 5)** — long-lived per sandbox, not per run. Rotate on every wake; bridge re-auths after every hibernate/resume. Treat as signed JWTs with TTL ≤ sandbox idle window.
11. **Per-user sandbox = noisy-neighbor surface** — all of one user's tasks share one Sprite. v1 limits this to one active run at a time per sandbox (queue the rest). Hard cap Sprite CPU/RAM/disk early so a single user can't cost-spiral.
12. **Multi-repo install token scoping** — different repos in the same sandbox can be on different GitHub App installations (different orgs). Mint **per-repo, per-run** install tokens at `StartRun` time; never share a token across repos or persist it on the sandbox disk.
13. **Reconciliation correctness on `ClientHello`** — the diff between `Repo` rows in Mongo and `cloned_repos` reported by the bridge must converge: missing on disk → `EnsureRepoCloned`; on disk but not connected → `RemoveRepo`. Test the four-quadrant matrix explicitly in slice 4.
14. **Sandbox name collisions** — `vibe-sbx-{user_id}` is deterministic; if `/api/sandbox/destroy` is called and a new spawn happens immediately, Sprites may still hold the old name. Either wait for full destroy or include a salt suffix; decide in slice 4.
15. **`/work` quota and warm-cache bloat** — `node_modules` per repo plus `.venv` plus pip cache will grow. Slice 4 sets a per-sandbox disk cap and a `du`-based eviction job; don't ship without it or the first heavy user wedges their own sandbox.

---

## 20. Status snapshot (as of 2026-05-01)

- **Slice 0** ✅ scaffolding shipped
- **Slice 1** ✅ code shipped, ⬜ verification + first real `gen:api-types` pending
- **Slices 2–8** ⬜ not started; briefs to be authored slice-by-slice

Repo metrics (from latest `/graphify` run): 217 nodes, 200 edges, 64 communities. The graph confirmed the planned package layout is in place and slice 1's code crosses every boundary the architecture predicts (web routes ↔ FastAPI routes ↔ Beanie models ↔ Mongo).

---

## 21. Concrete next steps (do these in order)

1. **Close slice 1 verification** — punch list under §18 / Slice 1.
2. **Author `slice2.md`** following the same shape as [slice1.md](slice1.md): context, scope, what to build, hard rules, acceptance criteria, when-done summary template.
3. **Register the GitHub App** (manual) on GitHub developer settings; copy `GITHUB_APP_ID`, generate and store the private key, set the webhook secret. Add to `.env`.
4. **Implement slice 2** per the brief.
5. Repeat for slices 3 → 8.

Do **not** start slice 2 implementation before the brief exists and the user reviews it. The hard rule from [slice1.md:665](slice1.md#L665) — "do not start the next task automatically" — applies for every slice transition.
