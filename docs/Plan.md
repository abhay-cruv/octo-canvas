# Plan.md — octo-canvas

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
┌──────────────┐  HTTPS + WSS  ┌───────▼───────────────┐  Sprites API   ┌──────────────────────────────┐
│  apps/web    │ ◄───────────► │  apps/orchestrator    │ ─────────────► │   Fly.io Sprite              │
│  Vite SPA    │               │  FastAPI + uvicorn    │   (REST/WSS)   │   (one per user)             │
│  React 18    │               │                       │                │                              │
│  TanStack    │               │  - Auth (Authlib)     │ ◄── WSS ────── │  apps/bridge (long-lived)    │
│  Tailwind    │               │  - GitHub OAuth +     │   (bridge      │   ├─ session mux (N CLIs)    │
│              │               │    githubkit          │    dials home) │   ├─ MCP: ask_user_clarif    │
└──────────────┘               │  - Sandbox manager    │                │   └─ ClaudeCredentials       │
                               │  - WS gateway (web +  │                │       │                      │
                               │    bridge)            │                │       ▼                      │
                               │  - Redis (state +     │                │   `claude` CLI subprocesses  │
                               │    bridge ownership)  │                │   (one per Task; --resume)   │
                               │  - S3 (event log)     │                │   driven by claude-agent-sdk │
                               └───────────────────────┘                │                              │
                                                                        │  /work/                      │
                                                                        │   ├── repo-a/  (clone)       │
                                                                        │   ├── repo-b/  (clone)       │
                                                                        │   └── repo-c/  (clone)       │
                                                                        │  ~/.claude/projects/         │
                                                                        │   └─ session JSONLs          │
                                                                        └──────────────────────────────┘
```

Three apps:

- **apps/web** — pure SPA. Vite-built static bundle hosted on Cloudflare Pages or similar. Talks only to the orchestrator. Cannot talk to GitHub, Sprites, or the bridge directly.
- **apps/orchestrator** — long-running FastAPI service on Fly.io. The brain. Holds all secrets. Owns the DB. Owns both WSS surfaces (web at `/ws/web/...`; bridge at `/ws/bridge/{sandbox_id}` — bridge dials in, never the other way). Brokers every interaction between web ↔ bridge.
- **apps/bridge** — Python process installed into the Sprite by the orchestrator's `installing_bridge` reconciler phase (no image bake). Boots once when the sprite warms, dials home to the orchestrator over WSS, multiplexes N concurrent `claude` CLI subprocesses (one per active Task) driven by `claude-agent-sdk`, holds the in-process MCP server that registers `ask_user_clarification`. Resolves Anthropic credentials via `ClaudeCredentials`: in v1 it points the CLI at the orchestrator's Anthropic proxy with a sandbox-scoped synthetic token — **the real Anthropic API key never enters the sprite** (see §16.2). Repos live in `/work/<full_name>/`; CLI session transcripts live in `~/.claude/projects/`.

### Sandbox model — one per user, many repos

Each user gets exactly **one** persistent sandbox. When the user connects a repo, the sandbox clones it into `/work/<repo_full_name>/` and keeps it warm. Tasks run inside this sandbox; the bridge `cd`s into the right repo subdir for each task. Disconnecting a repo removes the subdir but does not destroy the sandbox.

Lifecycle: `none → spawning → running → idle → hibernated → resumed → running …` (per user, not per task). Idle hibernation kicks in after 10 minutes of no active task; resume on next task. Destroyed only on explicit user action (sign-out does **not** destroy — connected repos and warm caches survive).

> **Alternative considered, not chosen:** sandbox-per-task with on-demand `git clone` each time. Simpler isolation, but cold-start cost (clone + dependency install) on every task. Per-user warm sandbox amortizes that cost across N tasks across N repos. If you wanted the simpler model, this is the section to flip.
>
> **Forward-compat note (current limitation, not a permanent constraint):** today the product enforces exactly one sandbox per user — the UI, API surface (`/api/sandbox` with no `{sandbox_id}`), and `Sandbox` collection (one doc per user) all assume singleton. The architecture should be built so this can grow to **multiple sandboxes per user** later (e.g. per-environment, per-team, or to isolate heavy/long-running workloads) without a rewrite. Practically: keep `sandbox_id` on `Chat` / `ChatTurn` (see §8), avoid hard-coding "the user's sandbox" in domain logic that could equally accept a sandbox handle, and treat the singleton as a routing/UI choice in the orchestrator rather than a data-model invariant. When we lift the limit, the change should be: add sandbox selection to the chat-create flow + repo-connect flow, parameterize the sandbox endpoints by id, and drop the "one per user" uniqueness assumption — not reshape `Chat`/`ChatTurn`/`Repo`.

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
| Agent runtime | `claude` CLI (Claude Code) baked into Sprite image, driven by `claude-agent-sdk` | The CLI is the long-lived process that owns the conversation transcript and tools; the SDK is the local driver. The bridge wraps the SDK to multiplex sessions and route over WSS. |
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
                              ▼  pnpm --filter @octo-canvas/api-types gen:api-types
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

Collections in `octo_canvas` Mongo database, each Beanie `Document`. Slice annotation in parens.

### `users` (slice 1 — done; user-agent prefs added in slice 8b)
```python
class User(Document):
    github_user_id: Annotated[int, Indexed(unique=True)]
    github_username: str
    github_avatar_url: str | None
    email: str
    display_name: str | None
    github_access_token: str | None    # slice 2
    # User-agent preferences (slice 8b). Default off — user opts in.
    user_agent_enabled: bool = False
    # When enabled, controls whether the user-agent tries to answer the
    # sandbox agent's clarification questions itself or escalates every
    # one to the user. Prompt enhancement is on regardless when
    # user_agent_enabled is True.
    user_agent_mode: Literal["user_answers_all", "agent_handles"] = "agent_handles"
    # Claude credential mode (slice 8 ships only "platform_api_key"; the field
    # exists so OAuth and BYOK can land later as a settings flip + a new
    # ClaudeCredentials Protocol impl, not a schema migration. See §14.7.)
    claude_auth_mode: Literal["platform_api_key", "user_oauth", "user_api_key"] = "platform_api_key"
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

### `sandboxes` (slice 4 — implemented)

Holds the sandbox-side state that needs to survive orchestrator restarts (Redis is the hot cache; this is the source of truth). **In v1 the orchestrator enforces one alive sandbox per user as a routing/UI choice, not a data-model invariant** — the schema and indexes are multi-sandbox-ready (see §4 forward-compat note).

```python
class Sandbox(Document):
    user_id: Annotated[PydanticObjectId, Indexed()]  # NOT unique — see §4 forward-compat note
    provider_name: Literal["sprites", "mock"]    # discriminator
    provider_handle: dict[str, str]              # opaque payload, e.g. {"name": "octo-sbx-...", "id": "sprite-..."}
    status: Literal["provisioning","cold","warm","running","resetting","destroyed","failed"]
    public_url: str | None       # Sprites' per-sandbox URL (cf. python.md → Management)
    last_active_at: datetime | None
    spawned_at: datetime | None
    destroyed_at: datetime | None
    last_reset_at: datetime | None
    reset_count: int             # increments on every reset
    failure_reason: str | None   # sanitized; never contains tokens
    created_at: datetime
    class Settings: name = "sandboxes"
```

No `region`/`sprite_id`/`bridge_version`/`hibernated_at` — Sprites manages region and resources, the SDK owns the sprite UUID inside `provider_handle.id`, and there's no bridge daemon to version-track. See [slice/slice4.md](slice/slice4.md) for the full design discussion and [`python_packages/db/src/db/models/sandbox.py`](../python_packages/db/src/db/models/sandbox.py) for the canonical schema.

### `repo_introspection` (embedded subdocument, slice 3)
```python
class RepoIntrospection(BaseModel):
    primary_language: str | None
    package_manager: Literal["pnpm","npm","yarn","uv","poetry","pip","cargo","go","bundler"] | None
    test_command: str | None
    build_command: str | None
    detected_at: datetime
```

### `chats` (slice 8 — renamed from `tasks` stub in slice 5a)
A user-filed unit of work against one of the user's connected repos. Each task maps **1:1 to a Claude Code session** (the CLI's `session_id`, which is also the JSONL filename under `~/.claude/projects/<repo_hash>/`). Follow-ups produce additional turns within the same session via `--resume`. The sandbox is reused across tasks.
```python
class Task(Document):
    user_id: PydanticObjectId
    sandbox_id: PydanticObjectId  # required — multi-sandbox forward-compat per §4
    repo_id: PydanticObjectId     # which connected repo this task targets
    title: str                    # first line of initial message, or LLM-summarized
    status: Literal["pending","running","awaiting_input","completed","failed","cancelled"]
    initial_prompt: str
    base_branch: str              # usually repo.default_branch at task creation
    work_branch: str | None       # set when bridge creates it (octo/task-{slug})
    claude_session_id: str | None # CLI session uuid; null until first turn completes; used with --resume
    pr_number: int | None
    pr_url: str | None
    token_budget_input: int = 1_000_000
    token_budget_output: int = 500_000
    created_at: datetime
    updated_at: datetime
    class Settings: name = "tasks"
```

### `chat_turns` (slice 8 — renamed from `agent_runs` stub in earlier drafts)
One turn = one user message (initial or follow-up) within a `Chat`. Many turns per Chat; all turns share the Chat's `claude_session_id`. Used for spend accounting, status tracking, and the "this turn finished" boundary on the FE; the wire's `seq` numbering is per-(chat, session) so turns don't fragment the event stream.
```python
class ChatTurn(Document):
    chat_id: PydanticObjectId
    sandbox_id: PydanticObjectId  # → Sandbox._id (the user's sandbox)
    repo_id: PydanticObjectId     # denormalized for fast event-log queries
    claude_session_id: str | None # mirrors Chat.claude_session_id at turn start; null on the very first turn before the CLI assigns one
    status: Literal["queued","running","completed","failed","cancelled"]
    user_prompt: str              # the user's text for this turn (post-enhancement when User Agent on)
    is_follow_up: bool            # false for the first turn on a chat
    started_at: datetime
    ended_at: datetime | None
    input_tokens: int
    output_tokens: int
    class Settings: name = "chat_turns"
```

### `agent_events` (slice 8, with S3 archival in slice 11)
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

### User (slice 1 — done; user-agent prefs added in slice 8b)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/me` | `UserResponse` includes `user_agent_enabled` + `user_agent_mode`. 401 if unauthenticated. |
| PATCH | `/api/me/user-agent` | Body: `{enabled?: bool, mode?: "user_answers_all" \| "agent_handles"}`. Both fields optional; partial update. Returns the updated `UserResponse`. (slice 8b) |

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
| POST | `/api/sandboxes/{sandbox_id}/pause` | Force release of compute now: kills active exec sessions so Sprites' idle timer transitions the sprite to `cold`. Filesystem preserved. Idempotent on `cold`. 409 from `provisioning`/`resetting`/`destroyed`/`failed`. |
| POST | `/api/sandboxes/{sandbox_id}/hibernate` | Force hibernate now. |
| POST | `/api/sandboxes/{sandbox_id}/destroy` | Destroys the Sprite. Repos bound to this sandbox remain in `repos` but `clone_status="pending"` until next wake. |

### Chats (slice 8)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/repos/{repo_id}/tasks` | List tasks for a repo. |
| POST | `/api/repos/{repo_id}/chats` | Body `{prompt}`. Creates `Chat` + first `ChatTurn`. **Wakes the user's sandbox if not already running**; the bridge spawns a CLI in the chat's worktree at `/work/<full_name>/.octo-worktrees/chat-<slug>/`. |
| GET | `/api/tasks/{task_id}` | Task + recent events (paginated). |
| POST | `/api/chats/{chat_id}/messages` | Body `{prompt}`. Creates a follow-up `ChatTurn` on the same `Chat` (same sandbox, same worktree). |
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

## 10. Transport architecture (slice 5+)

### 10.1 Three legs — two of them are our wire, one is Sprites' SDK

The system has three transport legs:

1. **Web ↔ orchestrator** — our WS endpoint, our Pydantic protocol. `/ws/web/tasks/{task_id}` (slice 5a) + `/ws/web/sandboxes/{id}/pty/{terminal_id}` (slice 8). We own this wire.
2. **Bridge ↔ orchestrator** — our WS endpoint, our Pydantic protocol. `/ws/bridge/{sandbox_id}` (slice 8; bridge skeleton baked into image in slice 7). The bridge process inside the Sprite dials home; the orchestrator never opens a connection in this direction. We own this wire.
3. **Orchestrator ↔ sandbox (Sprites SDK)** — Sprites' Exec/Filesystem/Watch/Proxy. WSS, but we are the *client* of `sprites-py`. Used for PTY brokering (slice 8), file ops (slice 8), reconciliation `exec_oneshot` (slice 5b), and the per-sandbox HTTP preview URL. We do NOT define this protocol; Sprites does. See [`docs/sprites/v0.0.1-rc43/python.md`](sprites/v0.0.1-rc43/python.md).

The bridge↔orchestrator leg was deleted in the slice-4-era rewrite (when the design was "agent runs are subprocess-per-run via Sprites Exec, parsing JSON-lines from stdout"). It came back in slice 8 because the agent runtime is **`claude` CLI driven by `claude-agent-sdk`** — a long-lived multi-session process that needs persistent message routing with replay/idempotency that's awkward to express through Sprites Exec stdio. See §14 for the full agent runtime; see §10.4b for the bridge-side wire protocol.

We **do not** use gRPC for the web leg. Browsers don't speak gRPC natively; gRPC-Web is a separate stack we'd have to maintain. Pydantic→TS via OpenAPI codegen handles the only direction of typing we actually need.

Revisit the decision only if Sprites' API materially changes shape or production telemetry shows the SDK can't carry our load.

### 10.2 Channels (where they live now)

The user-facing channels are the same as before; what changed is **who hosts them**. The orchestrator-side (web-facing) endpoints are ours; the sandbox-side endpoints are Sprites'.

| Channel | Web side (we host) | Sandbox side (Sprites SDK) | Wire | Replay |
|---|---|---|---|---|
| **Control + events** (agent task feed, status) | `/ws/web/tasks/{task_id}` — Pydantic discriminated union | n/a — orchestrator generates events from SDK calls and Mongo state | JSON | `seq`-replay from Mongo |
| **PTY** (terminal) | `/ws/web/sandboxes/{id}/pty/{terminal_id}` — orchestrator brokers | `/v1/sprites/{name}/exec` (WSS, TTY mode) — orchestrator opens with stdin/stdout/stderr stream IDs | binary | Sprites' built-in **scrollback buffer** on attach — see [python.md → Exec → SCROLLBACK BUFFER](sprites/v0.0.1-rc43/python.md) |
| **File ops** | `GET/PUT /api/sandboxes/{id}/fs?path=...` — thin auth wrapper | `/v1/sprites/{name}/fs/{read,write,list,delete,rename,copy,chmod}` (HTTP) | HTTP body | n/a |
| **File watch** (live diff while agent edits) | merged into web's control+events channel as `FileEditEvent` | `/v1/sprites/{name}/fs/watch` (WSS) — orchestrator subscribes | JSON envelope | n/a |
| **HTTP preview** of dev server in sandbox | direct redirect to Sprites' per-sandbox URL | `https://{sprite_name}-{org}.sprites.app` — built into every sandbox | HTTP/HTTPS | n/a |
| **TCP tunnel** (post-v1, e.g., DB connection) | per-sandbox WSS broker if/when needed | `/v1/sprites/{name}/proxy` (WSS) | binary | n/a |

Why the orchestrator brokers PTY and FS rather than letting the FE call Sprites directly: **the FE must never see `SPRITES_TOKEN`.** The orchestrator authenticates the user via session cookie, opens its own SDK call to Sprites with the server-side token, and pipes bytes/JSON back to the FE. Costs ~10–20 ms; buys auth + audit + rate-limit + the ability to revoke a user without rotating the Sprites token. Direct FE→Sprites is a v2 latency optimization if anyone ever asks for it.

PTY connections are **opened on demand** (when the user clicks "Open terminal") and closed when the tab/terminal closes — most active sandboxes have zero PTYs open at any moment. Sprites' Exec sessions also persist across the FE↔orchestrator WS dropping (`max_run_after_disconnect` defaults to forever for TTY), so a user can reload the tab and reattach to the same shell session.

### 10.3 Endpoints + authentication

| Endpoint | Who connects | Auth |
|---|---|---|
| `/ws/web/tasks/{task_id}` | web client subscribes to a task's event stream | session cookie via FastAPI `Depends` on the WS handshake |
| `/ws/web/sandboxes/{sandbox_id}/pty/{terminal_id}` | web client opens a terminal (orchestrator brokers to Sprites Exec) | session cookie |
| `/ws/bridge/{sandbox_id}` | the bridge process inside the sprite dials home (slice 8; image+token wired in slice 7) | `Authorization: Bearer ${BRIDGE_TOKEN}` minted per-sandbox at provision time, scoped to that `sandbox_id`, rotatable |

Sprites' Exec/Watch/Proxy WSS are reached from the orchestrator outbound via the SDK. The bridge↔orchestrator WSS is **inbound** from the sprite — that's a deliberate choice (see §10.1, §14.4): the orchestrator does not open this connection.

All web-bound messages are Pydantic discriminated unions in `python_packages/shared_models/wire_protocol/`. Discriminator field: `type`.

### 10.4 Web-side message types (control + events channel)

Orchestrator → web (a transcoded UI feed; the source events are produced by the orchestrator from a mix of Mongo state, Sprites Exec stdout parses, and Sprites Watch deltas):

```
ToolCallEvent              { type, run_id, seq, tool_name, args }
ToolResultEvent            { type, run_id, seq, tool_name, ok, output }
FileEditEvent              { type, run_id, seq, path, before_sha, after_sha, summary }
ShellExecEvent             { type, run_id, seq, cmd, exit_code, stdout_tail, stderr_tail }
GitOpEvent                 { type, run_id, seq, op, branch?, commit_sha?, pr_url? }
AssistantMessageEvent      { type, run_id, seq, content, finish_reason? }
StatusChangeEvent          { type, run_id, seq, new_status }
SandboxStatusEvent         { type, sandbox_id, status, public_url? }   # mirrors Sprites cold/warm/running
TokenUsageEvent            { type, run_id, seq, input_delta, output_delta }
ErrorEvent                 { type, run_id?, seq, kind, message }
# User-agent events (slice 8b — only when Sandbox.user_agent_enabled is True for this user)
PromptEnhancedEvent        { type, run_id, seq, original, enhanced, applied: bool }
AskUserClarification       { type, run_id, seq, clarification_id, question, agent_attempted?: AgentAttempt }
AgentAnsweredClarification { type, run_id, seq, clarification_id, question, answer, reasoning?, override_window_ms }
Pong                       { type, nonce }
```

Web → orchestrator:

```
Resume                       { type, after_seq }                       # on (re)connect, request replay
SendFollowUp                 { type, run_id, content }
CancelTask                   { type, task_id }
RequestOpenPty               { type, terminal_id, cwd?, cols, rows }   # orchestrator opens Sprites Exec
RequestClosePty              { type, terminal_id }
ResizePty                    { type, terminal_id, cols, rows }
# User-agent (slice 8b)
AnswerClarification          { type, run_id, clarification_id, answer }   # user types reply when agent escalated
OverrideAgentAnswer          { type, run_id, clarification_id, new_answer? } # user disagrees with auto-answer; if new_answer omitted, treat as "ask the agent again with no preset"
Pong                         { type, nonce }
```

`PromptEnhancedEvent` is informational — it fires after the user-agent has already written the enhanced prompt to the sandbox stdin. The FE renders both `original` and `enhanced` collapsibly so the user can see what happened. `applied: false` means the user-agent decided enhancement wasn't useful and forwarded the raw prompt.

`AgentAnsweredClarification` carries an `override_window_ms` (default `8000`). The FE renders an "Override" affordance for that long; if the user clicks within the window, the FE sends `OverrideAgentAnswer` and the orchestrator interrupts the sandbox agent (writes a correction to stdin, since by then the auto-answer has already been forwarded). After the window closes, the override button is disabled — at that point the sandbox agent has already acted.

Everything else is HTTP REST.

### 10.4b Bridge ↔ orchestrator wire (slice 8)

A separate Pydantic discriminated union, parallel to §10.4. Lives in `python_packages/shared_models/src/shared_models/wire_protocol/bridge.py`. **All frames are session-scoped** (`session_id` is required) except connection-level frames (`Hello`, `Goodbye`, `Ping`, `Pong`).

Bridge → orchestrator (events from inside the sprite):

```
Hello                         { type, sandbox_id, bridge_version, last_acked_seq }
Goodbye                       { type, reason }
SessionStarted                { type, session_id, task_id, claude_session_id }
SessionEvicted                { type, session_id, reason }
AssistantMessage              { type, session_id, seq, content_blocks }   # streaming text + tool_use
ToolCallStarted               { type, session_id, seq, tool_use_id, tool_name, args }
ToolCallFinished              { type, session_id, seq, tool_use_id, ok, output_summary }
FileEditEvent                 { type, session_id, seq, path, before_sha, after_sha, summary }
ShellExecEvent                { type, session_id, seq, cmd, exit_code, stdout_tail, stderr_tail }
GitOpEvent                    { type, session_id, seq, op, branch?, commit_sha?, pr_url? }
TokenUsageEvent               { type, session_id, seq, input_delta, output_delta }
StatusChangeEvent             { type, session_id, seq, new_status }
AskUserClarification          { type, session_id, seq, clarification_id, question, context? }
ErrorEvent                    { type, session_id?, seq, kind, message }
Pong                          { type, nonce }
```

Orchestrator → bridge (commands into the sprite):

```
SessionState                  { type, sessions: list[{task_id, claude_session_id?, repo_full_name}] }
UserMessage                   { type, session_id, task_id, repo_full_name, claude_session_id?, text, frame_id }
AnswerClarification           { type, session_id, clarification_id, answer, frame_id }
CancelSession                 { type, session_id, frame_id }
PauseSession                  { type, session_id, frame_id }
SessionEnv                    { type, session_id, env: dict[str,str], frame_id }   # reserved for future creds modes
Ack                           { type, ack_seq }                                     # acknowledges bridge → orchestrator events up to seq
Ping                          { type, nonce }
```

`seq` is monotonic per `(sandbox_id, session_id)`, allocated by the bridge before send. The orchestrator sends `Ack{ack_seq}` periodically (at minimum every N events or every 5s); the bridge prunes its replay buffer up to `ack_seq`. `frame_id` on inbound commands gives the bridge a key for at-most-once tool-side effects (clarification answers must not double-fire if the orchestrator retransmits after a flap).

The bridge↔orchestrator stream is **per sandbox**, multiplexing all sessions for that sandbox over a single WSS — analogous to HTTP/2 streams over one TCP connection.

### 10.5 PTY channel (binary)

User opens a terminal. The orchestrator's `/ws/web/.../pty/{terminal_id}` handler validates the session, then opens a Sprites Exec WSS via the SDK (`sprite.command(...)` with `tty=True`) and pipes bytes both ways. The SDK handles stdin/stdout/stderr stream framing per [python.md → Exec → BINARY PROTOCOL](sprites/v0.0.1-rc43/python.md). xterm.js on the web side speaks the same byte stream.

Reattach semantics come from Sprites: the Exec session ID survives the FE↔orchestrator WS dropping. On reconnect, the orchestrator looks up the active Sprites session and uses Attach (`/v1/sprites/{name}/exec/{session_id}`) instead of starting a new one — Sprites replays its scrollback buffer so the user sees the output they missed.

Resize is a Sprites-side `{type: "resize", cols, rows}` JSON message on the same WSS, sent by the orchestrator when the FE asks via `ResizePty`.

### 10.6 Reliability — disconnects must be graceful and robust

The wire is the most-tested surface in production. Rules:

#### Heartbeat (web ↔ orchestrator AND bridge ↔ orchestrator)

- Application-level `Ping`/`Pong` with `nonce`, every **30 seconds** in both directions.
- **Two missed pongs (~90 s)** → declare the peer dead and close with code `1011`.
- Both legs use the same heartbeat machinery; only the wire-protocol module differs.

#### Sequence numbers + replay (control + events)

- Every event the orchestrator persists into `agent_events` gets a monotonic `seq` per `task_id` (5a) / per `(task_id, session_id)` (6).
- Web client tracks `last_seen_seq`; on reconnect sends `Resume{after_seq}` as the first message; orchestrator streams missed events from Mongo, then resumes live.
- The **bridge** also tracks `seq` per `(sandbox_id, session_id)` for outbound events and keeps a local ring buffer (1000 frames or 1 MB per session). On WSS reconnect, `Hello{last_acked_seq}` tells the orchestrator the last `seq` the bridge believes was acknowledged; the orchestrator writes any newer events to Mongo and replies with `Ack{ack_seq}`. Inbound commands use `frame_id` for idempotency (orchestrator may retransmit `AnswerClarification` on flap; bridge drops dupes).
- Mongo retains the last **24 hours** of events per task hot; older fetches go through the slice 10 S3 archive transparently.

#### Sprites-leg disconnect handling

Sprites' SDK manages reconnects on the orchestrator↔sprite leg. Our concerns:

- **Exec session loss** (sprite was destroyed mid-command): the SDK raises `NotFoundError` on next call. The orchestrator emits `ErrorEvent{kind: "exec_session_lost"}` and the web client surfaces it; the user's runs are not auto-retried.
- **Sprite cold during exec**: Sprites auto-warms on access; the SDK call blocks briefly then proceeds. No app-level intervention needed.
- **Network failure orchestrator → Sprites**: the SDK raises `NetworkError`; we map to `SpritesError(retriable=True)` (see `sandbox_provider.sprites._is_retriable`). Routes return 502; web client retries via standard backoff.
- **PTY brokerage interruption** (orchestrator ↔ Sprites Exec WSS dropped mid-stream): we re-attach to the same `session_id` and pipe the scrollback buffer to the FE. The FE doesn't notice unless the gap exceeds the Sprites scrollback window.

#### Backpressure

- Orchestrator buffers up to **1000 events per (run, web subscriber)**. If a slow web client overflows: drop intermediate events with a `BackpressureWarning` event, advance `seq`. Client catches up via `Resume` on next reconnect.
- PTY brokerage: orchestrator forwards bytes pass-through; if the FE WS write buffer fills up, **drop frames** rather than back-pressure into Sprites. Terminal output may briefly garble; better than freezing keystrokes.
- File-watch (`FileEditEvent`): orchestrator coalesces Sprites' `fs/watch` deltas by `path` at ≤4 Hz before fanning out to web subscribers.

#### Fail-fast vs. fail-soft

- Auth failure on web (re)connect: **fail fast** (close `4001`, no retry without re-auth).
- Schema mismatch on web messages (Pydantic validation fails): **fail soft** — drop, log, increment metric. Do not kill the connection. Schemas evolve.
- Sprites token revoked / expired: orchestrator's startup check catches this; runtime SDK calls returning 401 raise `SpritesError(retriable=False)`. Operator rotates `SPRITES_TOKEN` and restarts.
- Orchestrator restart mid-task: web sees TCP close → reconnect → `Resume` → catch up. Sprite state is unaffected because Sprites is the sandbox source-of-truth, not us.

### 10.7 Horizontal scale — stateless orchestrator + Redis pub/sub for fan-out

The orchestrator is stateless. Multiple instances run behind Fly's load balancer.

**Bridge connection routing** (slice 8): the bridge dials `/ws/bridge/{sandbox_id}` and lands on whichever instance Fly's LB picks. That instance becomes the **owner** of the bridge connection for its lifetime. Inbound bridge events (`AssistantMessage`, `ToolCallStarted`, …) are persisted to Mongo and **published to Redis** on `chat:{chat_id}` (looked up by `session_id → chat_id` from the bridge's `SessionStarted` frame). Outbound commands (`UserMessage`, `AnswerClarification`) target the bridge — the issuing instance must reach the owner. Mechanism: a Redis hash `bridge_owner:{sandbox_id} = {instance_id, expires_at}` (TTL 60s, refreshed by the owner every 20s); non-owner instances forward outbound commands via Redis pub/sub on `bridge_in:{sandbox_id}` and the owner picks them up. If the owner is gone (TTL expired), the bridge will reconnect on its own and a new owner takes over.

Web client routing is unchanged from slice 5a — fan-out via `task:{task_id}`, late-joiners use `Resume{after_seq=0}` against Mongo.

- Mongo retains the truth (`agent_events`); pub/sub is the fan-out, not the source of truth.
- A late-joining web client uses `Resume{after_seq=0}` and reads from Mongo.
- The bridge's local ring buffer covers the *bridge → orchestrator* direction; Mongo + pub/sub covers *orchestrator → web*.

#### Capacity caps + shedding

- Each instance advertises `(connections, runs_owned)` to Redis hash `orchestrator_capacity:{instance_id}` (60s TTL). Fly's LB checks before routing new sandbox-spawn requests.
- Per-instance soft cap: **5000 web WS connections + 200 active Sprites Exec sessions**. Hot-shed beyond that — return 503 on new sandbox spawn / new task creation. Existing connections aren't degraded.

### 10.8 What we deliberately don't do

- **No FE↔bridge direct connection.** All web traffic goes through the orchestrator for auth + audit + rate-limit + multi-tab fan-out. The bridge talks only to the orchestrator.
- **No FE↔Sprites direct connection.** Costs ~10–20 ms per orchestrator hop, buys auth (FE never holds `SPRITES_TOKEN`) + audit + rate-limit. Direct path is a v2 optimization if PTY genuinely bites.
- **No SSE / long-poll fallback.** WS works on every supported browser; one transport is enough.
- **No protocol versioning beyond Pydantic schema evolution.** When we need a v2, branch at the handler. Don't pre-build a versioning system.
- **No custom HTTP preview proxy.** Sprites ships a per-sandbox URL — surface it on the dashboard, configure `auth=sprite|public` via `update_url_settings`. Slice 9 is absorbed.

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

## 13. Sandbox lifecycle (slice 4 — implemented)

**One persistent sandbox per user.** It hosts every connected repo of that user under `/work/<full_name>/` and serves every agent run. It outlives individual tasks; it does not outlive the user account.

The sandbox is provisioned via Sprites (see [docs/sprites/v0.0.1-rc43/python.md](sprites/v0.0.1-rc43/python.md)). The `SandboxProvider` Protocol is intentionally narrow so the backend stays swappable. Slice 4 surface:

```python
@dataclass(frozen=True)
class SandboxHandle:
    provider: ProviderName       # "sprites" | "mock"
    payload: dict[str, str]      # opaque; e.g. {"name": "octo-sbx-...", "id": "sprite-..."}

class SandboxProvider(Protocol):
    name: ProviderName
    async def create(self, *, sandbox_id: str, labels: list[str]) -> SandboxHandle
    async def status(self, handle: SandboxHandle) -> SandboxState   # ProviderStatus + public_url
    async def destroy(self, handle: SandboxHandle) -> None
    async def wake(self, handle: SandboxHandle) -> SandboxState     # no-op exec to force warm
    async def pause(self, handle: SandboxHandle) -> SandboxState    # kill exec sessions; let Sprites idle
```

Slice 5b widens with `fs_*` and `exec_*`; slice 6 with `fs_rename` + `fs_watch_subscribe`; slice 7 with `image_tag` arg on `create()`. Don't pre-add. Sprite naming: `octo-sbx-{sandbox_id}` where `sandbox_id` is the Mongo `Sandbox._id`. v1 enforces exactly one alive `Sandbox` per user at the orchestrator routing layer (`SandboxManager.get_or_create`); the multi-sandbox future (§4 forward-compat note) lifts that enforcement — no naming or schema change needed.

### Per-user state machine

```
                       user signs up
                            │
                            ▼
                     ┌──────────────┐
                     │   no doc     │
                     └──────┬───────┘
                            │ POST /api/sandboxes
                            ▼
                     ┌──────────────┐
                     │ provisioning │
                     └──────┬───────┘
                            │ provider.create returns
                            ▼
        ┌──────────► ┌──────────────┐
        │            │ cold|warm|   │  ◄── auto-paused after idle (Sprites)
        │            │   running    │  ◄── auto-warmed on access (Sprites)
        │            └─┬───┬───┬────┘
        │   reset      │   │   │  destroy
        │     ▼        │   │   ▼
        │  resetting   │   │  destroyed (terminal; doc kept)
        │     │        │   │
        │     │        │   │ wake (force-warm via no-op exec)
        │     ▼        │   ▼
        └──── provisioning ┘

       Provider failure at any point → failed
                                       │
                                       │  reset    destroy
                                       ▼          ▼
                                   resetting   destroyed
```

Mapping to Sprites' status: `cold | warm | running` reflect the SDK's enum directly. Our app-level `provisioning`, `resetting`, `destroyed`, `failed` are added for transitions and audit.

### Reset and Destroy are distinct

- **Reset** (`POST /api/sandboxes/{id}/reset`): destroys the sprite + its filesystem, then provisions a fresh one for the *same* `Sandbox` doc (preserves `_id`, increments `reset_count`, rotates `provider_handle`). Slice 4 implementation is sequential `provider.destroy → provider.create`. Slice 5b will switch to **`restore_checkpoint("clean")`** (see [python.md → Checkpoints](sprites/v0.0.1-rc43/python.md)) — milliseconds vs. recreate, copy-on-write storage means incremental checkpoints are tiny.
- **Destroy** (`POST /api/sandboxes/{id}/destroy`): tears down the sprite + filesystem and marks the `Sandbox` doc `destroyed` (audit trail). User must `POST /api/sandboxes` again to provision a new one (new `_id`). Sign-out does **not** destroy.

### Concurrency model inside one sandbox

A user can have multiple tasks. v1 policy: **one active agent run at a time per sandbox**, others queue. Rationale: simpler reasoning about concurrent file system writes, simpler cost caps, simpler UX (one "live" task indicator).

Queue lives in Redis: `sandbox:{sandbox_id}:queue` (LIST of `run_id`). The orchestrator dequeues and dispatches via the bridge WSS (slice 8) — see §14. Queue depth surfaces as `Sandbox.queue_depth` for the UI.

### State storage

- **Mongo `sandboxes`** — durable source of truth. Fields: `user_id`, `provider_name` (discriminator), `provider_handle: dict[str, str]` (opaque), `status`, `public_url`, all timestamps + `reset_count`, `failure_reason`. **Not stored**: region, CPU, RAM, disk, bridge_version. Sprites manages those.
- **Redis** — hot cache for slice 5a's WS hot path, written by `SandboxManager` on every state transition (90s TTL):
  - `sandbox:{sandbox_id}` → hash of `{status, public_url, last_active_at}`
  - `sandbox:{sandbox_id}:owner` → orchestrator instance id (60s TTL, refreshed on heartbeat) — for sticky routing of web subscribers when multiple instances are running
  - `sandbox:{sandbox_id}:queue` → list of pending `run_id`s (slice 8)
  - `sandbox:{sandbox_id}:active_run` → currently-running `run_id` (slice 8)

### Idle hibernation

**Sprites does this server-side** — sandboxes auto-pause to `cold` after idle and auto-warm on the next access (exec, HTTP request to the public URL, fs read). No orchestrator-side cron. The dashboard uses `POST /api/sandboxes/{id}/refresh` to resync live status when needed.

### Manual pause (slice 4)

`POST /api/sandboxes/{id}/pause` lets the user release compute *now* instead of waiting on Sprites' idle timer. Sprites' rc43 SDK exposes no force-pause verb, so the implementation kills any active exec sessions (which is what keeps a sprite warm) via `POST /v1/sprites/{name}/exec/{session_id}/kill` (raw HTTP through the SDK's authenticated client — `kill_session` isn't in rc37 SDK methods). The sprite then idles to `cold` on its own within seconds. Idempotent: pausing a `cold` sandbox is a no-op. Filesystem is preserved; user pays for storage only while paused. Slice 8+ will narrow the kill set to *non-agent* sessions so an active agent run isn't accidentally murdered by Pause.

### Destroy semantics

`POST /api/sandboxes/{id}/destroy` is destructive: filesystem is gone, all warm caches (`node_modules`, `.venv`, agent run history on disk) are gone. The `Sandbox` doc is **kept** with `status="destroyed"` (audit trail); the user must `POST /api/sandboxes` to get a new one. Repos in the `repos` collection are unaffected — slice 5b will flip their `clone_status` back to `pending` so the next provision re-clones into the fresh filesystem.

---

## 14. Agent runtime — two-agent architecture (slices 6 / 6b)

**Two agents, one transport.** v1 ships two distinct agent processes:

- **Sandbox Agent** (slice 8) — runs *inside the sprite*, driven by a long-lived **bridge** Python process. The bridge spawns and supervises the **`claude` CLI binary** (Claude Code, baked into the sprite image in slice 7) per chat session via `claude-agent-sdk`, which is itself a stdio-JSON wrapper over the CLI. The CLI does the actual coding work and owns the conversation transcript on disk under `~/.claude/projects/<hash>/` (JSONL per session). The bridge multiplexes N concurrent CLI sessions for one user, dials home to the orchestrator over a single WSS, and forwards events both ways. Stateful via the persistent filesystem (`/work/<repo>/`, `~/.claude/projects/`) and the CLI's own LLM context per session.
- **User Agent** (slice 8b — *opt-in*, off by default) — runs *inside the orchestrator* as an Anthropic SDK call with its own system prompt and small set of tools (read user prefs, read connected repos, read introspection data, look up past answers, surface to FE). Sits as a man-in-the-middle between FE and Sandbox Agent. Toggle + mode are persisted on the `User` doc (see §8).

The bridge daemon is **back** — earlier drafts of this plan tried to invoke `agent_runner` as a fresh subprocess per run via Sprites Exec, parsing JSON-lines off stdout. That model is **deleted**: Claude Code is a long-lived interactive process with on-disk session state and `--resume <session_id>` semantics, follow-ups are first-class, and a per-run subprocess would re-pay cold-start + cache-miss every turn. The bridge owns the WSS to the orchestrator and the CLI subprocesses; the orchestrator never opens a Sprites Exec stream for agent work (it still does for PTY in slice 8). See [apps/bridge/](../apps/bridge/) for the bridge process that ships in the Sprite image.

### 14.1 User Agent — toggle + modes (slice 8b)

Stored on `User` (see §8):

| Field | Values | Effect |
|---|---|---|
| `user_agent_enabled` | `true` / `false` (default `false`) | Master toggle. **Off** = orchestrator is a pure passthrough; user types go to sandbox stdin verbatim, sandbox questions surface to FE verbatim. **On** = User Agent is in the path. |
| `user_agent_mode` | `"agent_handles"` / `"user_answers_all"` (only meaningful when enabled) | Controls clarification routing. Default `agent_handles`. |

When `user_agent_enabled=true`, **prompt enhancement is always on** — the User Agent rewrites every user message before it hits the sandbox stdin, surfacing the original + enhanced via `PromptEnhancedEvent` so the user sees what was sent. Enhancement is informational, not gated; if the User Agent decides enhancement adds nothing it forwards the raw text and emits `PromptEnhancedEvent{applied: false}`.

Clarification routing (Sandbox Agent emits `AskUserClarification` on its stdout — see §14.3):

- **Off**: forwarded to FE verbatim. User types reply on FE; orchestrator writes to sandbox stdin.
- **On + `user_answers_all`**: User Agent does NOT try to answer. It still surfaces the question to FE (possibly with annotations like "I think the answer is X but you said you'd handle these") and forwards the user's reply to sandbox stdin.
- **On + `agent_handles`**: User Agent attempts to answer using its tools (read user prefs, repos, introspection). Two paths:
  - **Confident** → write answer to sandbox stdin immediately AND emit `AgentAnsweredClarification` to FE with an 8-second `override_window_ms`. User can click Override; FE emits `OverrideAgentAnswer`; orchestrator writes a correction to stdin (or aborts the answer if the sandbox hasn't acted on it yet).
  - **Not confident / question is genuinely user-only ("which color theme?")** → emit `AskUserClarification` to FE with `agent_attempted={attempted: true, reasoning: "..."}` so the user sees what the agent tried.

The User Agent's "confidence" is a self-reported flag in its tool's structured output; we don't try to infer it. If a tool the user-agent calls returns low-quality or conflicting data, the agent escalates.

### 14.2 Per-session data flow (combined)

```
[FE]         user types in chat   ──► SendFollowUp{task_id, content}  ──► [Orchestrator]
                                                                              │
                          if user_agent_enabled = true                        │
                                  │                                           │
                                  ▼                                           │
                          [User Agent — orchestrator]                         │
                          • enhance prompt                                    │
                          • PromptEnhancedEvent{original, enhanced} → FE      │
                                  │                                           │
                                  ▼ (or raw text if toggle off)               │
                          Bridge WSS — UserMessage{session_id, text} ─►  [Bridge]
                                                                            │
                                                                  spawns / resumes
                                                                  the `claude` CLI for
                                                                  session_id (--resume),
                                                                  feeds prompt via SDK
                                                                            │
                                                                            ▼
                                                                  [claude CLI subprocess]
                                                                  reads/writes files in
                                                                  /work/<repo>, runs
                                                                  shells, calls tools
                                                                            │
                                       SDK message stream         ◄─── stdio JSON
                                       (assistant text,                  to bridge
                                       tool_use, tool_result,
                                       AskUserClarification)
                                                                            │
                                       Bridge WSS frames (with             │
                                       session_id, seq) ────► [Orchestrator]
                                                                            │
                          [User Agent decides per event:]   ◄─── parsed by orchestrator
                          • passthrough? → web WS
                          • coalesce/summarize? → summarized event → web WS
                          • AskUserClarification?
                              ├─ try to answer (mode == agent_handles, confident)
                              │     → AnswerClarification frame back to bridge
                              │     → emit AgentAnsweredClarification with override window
                              └─ surface to user
                                    → emit AskUserClarification → web WS
                                    ◄── AnswerClarification from FE
                                    → AnswerClarification frame back to bridge
                                                                            │
                                                                            ▼
                                                                  [back to claude CLI]
```

### 14.3 `AskUserClarification` protocol

The sandbox agent (CLI) calls a custom MCP tool `ask_user_clarification(question, context?)` registered by the bridge. The tool **blocks** in the bridge until the answer arrives. Mechanics:

1. Bridge generates a `clarification_id` (uuid4), creates an `asyncio.Future` keyed by id, and sends `AskUserClarification{session_id, clarification_id, question}` over WSS.
2. Orchestrator (User Agent on or off) routes per §14.1; eventually the answer comes back as `AnswerClarification{session_id, clarification_id, answer}`.
3. Bridge resolves the future; the tool returns the answer string to the SDK, which feeds it back to the CLI as the tool result.

Multiple in-flight clarifications are allowed across sessions and within a session — each has its own id.

If the user closes the FE tab while a clarification is pending: orchestrator does NOT auto-answer. The clarification stays open in Mongo (`agent_events` row with `kind="awaiting_clarification"`); next time the user opens the task page, the FE renders it again. User Agent (when on, `agent_handles`) gets a second chance to answer if its confidence has changed.

If the bridge dies while a tool is blocked: the CLI fails the tool call on next read; the next `UserMessage` on that session resumes via `--resume` and the agent retries (CLI re-prompts the user).

### 14.4 Bridge process: lifecycle

The bridge is **one long-lived Python process per Sprite**, baked into the Sprite image and started by the image entrypoint. Lifecycle:

1. **Boot**: read `BRIDGE_TOKEN`, `ORCHESTRATOR_WS_URL`, `CLAUDE_AUTH_MODE` from env. Resolve `ClaudeCredentials` (§14.7).
2. **Dial home**: open WSS to `${ORCHESTRATOR_WS_URL}/ws/bridge/{sandbox_id}` with `Authorization: Bearer ${BRIDGE_TOKEN}`. On accept, send `Hello{sandbox_id, bridge_version, last_acked_seq}`.
3. **Reconcile sessions on resume**: orchestrator replies with `SessionState[]` — for each task that should be active, the bridge ensures a CLI subprocess is alive (or evictable, see §14.5). No CLI is started until a `UserMessage` arrives.
4. **Steady state**: pump `UserMessage`/`AnswerClarification`/`Cancel`/`Pause` inbound; pump `*Event` frames outbound from the multiplexer.
5. **WSS reconnect**: jittered backoff (1→16s ±25%); on reconnect resend `Hello{last_acked_seq}` and replay buffered outbound frames from local ring buffer (1 MB or 1000 frames per session, whichever smaller). Inbound is at-least-once, idempotent on `(session_id, frame_id)`.
6. **Shutdown** (sprite hibernates / restart): SIGTERM → bridge sends `Goodbye`, kills CLI processes (sessions on disk survive), exits.

The bridge is **never** invoked by `provider.exec_oneshot` from the orchestrator. It's part of the Sprite image; the orchestrator only sees its inbound WSS connection.

### 14.5 Bridge process: per-session multiplexing

A `Task` ↔ a `claude_session_id` (the CLI's session uuid; the JSONL filename under `~/.claude/projects/<repo_hash>/`). The bridge holds:

```python
@dataclass
class ClaudeSession:
    task_id: PydanticObjectId
    session_id: str                  # CLI session uuid; None until first turn
    repo_full_name: str
    state: Literal["idle","spawning","working","awaiting_clarification","evicted"]
    proc: ClaudeAgentProcess | None  # SDK handle wrapping the CLI subprocess; None if evicted
    last_user_msg_at: datetime
    pending_clarifications: dict[str, asyncio.Future[str]]
```

Concurrency rules:

- **Cap**: `MAX_LIVE_SESSIONS_PER_SANDBOX = 3` (env-tunable). Beyond cap, new `UserMessage` on a fresh session triggers eviction of the LRU `idle` session.
- **Eviction**: kill the CLI process; keep the JSONL on disk. Session moves to `state="evicted"`. Next `UserMessage` on that session re-spawns via `claude --resume <session_id>` — transcript is rehydrated from disk.
- **Idle eviction timer**: a session in `state="idle"` with no user message for `SESSION_IDLE_EVICT_S = 600` (10 min) is evicted to free RAM.
- **Cross-chat FS sharing**: chats use git worktrees under `/work/<repo>/.octo-worktrees/chat-<slug>/` (slice 8 call #12 in [slice8.md](slice/slice8.md)). Each chat is single-repo, on its own `octo/chat-<slug>` branch. Multi-chats on the same repo run concurrently in different worktrees backed by the shared object store at `/work/<repo>/.git/`. Cross-repo chats are post-v1.

### 14.6 Bridge ↔ CLI: how messages and tools flow

The bridge drives the CLI via `claude-agent-sdk` (Python). For each session:

```python
async with ClaudeAgentClient(
    options=ClaudeAgentOptions(
        cwd=f"/work/{repo_full_name}",
        resume=session.session_id,                   # None on first turn → SDK creates a new session
        system_prompt=render_system_prompt(repo, introspection),
        allowed_tools=["Read","Write","Edit","Bash","ask_user_clarification"],
        permission_mode="acceptEdits",                # MCP tool calls auto-approved; risky bash gated by hooks
        mcp_servers={"octo": OctoMcpServer(bridge_ref=self)},  # registers ask_user_clarification
        env={**creds.env(), "GIT_AUTHOR_NAME": "...", ...},
    )
) as client:
    await client.query(prompt=user_text)
    async for msg in client.receive_response():
        await self._fanout(session.task_id, msg)     # serialize + send over WSS
        if isinstance(msg, ResultMessage):
            session.session_id = msg.session_id      # capture on first turn
```

Notes:

- **Tools**: built-in CLI tools (`Read`, `Write`, `Edit`, `Bash`) handle code; the only custom tool is `ask_user_clarification` registered as an in-process MCP server.
- **Bash jailing**: enforced via the SDK's `PreToolUse` hook (`Bash` tool) — reject commands whose parsed `cwd` escapes `/work/<repo>/`. This is *belt* — the *braces* are the bridge running as a non-root user with `/work` mounted writable but `~` and `/etc` not.
- **No stdio JSON between bridge and orchestrator** — that's a property of the SDK↔CLI subprocess interface, hidden inside `ClaudeAgentClient`. The bridge talks to the orchestrator over WSS in our Pydantic protocol.
- **Token usage**: extracted from each `ResultMessage` (`usage.input_tokens`, `usage.output_tokens`) and emitted as `TokenUsageEvent`.

### 14.7 Pluggable Claude credentials

v1 ships **API key only**. The credential layer is a Protocol so OAuth (`claude setup-token`) and BYOK (per-user API key) can land later without protocol or wire changes:

```python
# python_packages/agent_config/src/agent_config/credentials.py

class ClaudeCredentials(Protocol):
    """Resolves the env vars passed when spawning the `claude` CLI."""
    name: ClassVar[Literal["platform_api_key", "user_oauth", "user_api_key"]]
    async def env(self) -> dict[str, str]: ...
    async def refresh(self) -> None: ...   # no-op for API key; OAuth refresh later
```

v1 implementations:

- `PlatformApiKeyCredentials` — reads `ANTHROPIC_API_KEY` from sprite env (orchestrator passes it at sandbox provision time as a sprite secret). Returns `{"ANTHROPIC_API_KEY": ...}`. `refresh()` is a no-op.

Future implementations (NOT slice 8 — design space only):

- `UserOAuthCredentials` — wraps a user-scoped Claude OAuth refresh token persisted on `User.claude_oauth_refresh_token`. `env()` mints a fresh access token via Anthropic's token endpoint; refreshes on demand.
- `UserApiKeyCredentials` — pulls a per-user `ANTHROPIC_API_KEY` from `User.user_anthropic_api_key` (encrypted at rest).

Selection is a string on `User.claude_auth_mode: Literal["platform_api_key","user_oauth","user_api_key"] = "platform_api_key"` (see §8). v1 hard-codes `"platform_api_key"`; the field exists so adding modes later is a settings page + a new Protocol impl, not a schema migration.

**Storage rule**: credentials are NEVER baked into the Sprite image. The bridge resolves them at session-spawn time via env vars or via WSS frames from the orchestrator (`SessionEnv{session_id, env: dict[str,str]}`) — the latter path is how user-scoped credentials flow when modes other than `platform_api_key` ship. v1 uses the env-var path only; the WSS frame is reserved.

### 14.8 Why a long-lived bridge (and not subprocess-per-run)

- **Claude Code is a long-lived process by design.** The CLI holds the conversation transcript, prompt cache, MCP server connections, and tool state in memory. Killing it after every `query()` would cost a cache miss + cold start every turn.
- **Follow-ups are first-class.** `claude --resume <session_id>` (or the SDK's `resume` option) rehydrates the transcript from `~/.claude/projects/`. Persistent disk gives us this for free; we just keep the SDK client alive across turns where possible.
- **Multi-session multiplexing needs an owner.** A user can have 3+ tasks open at once; the bridge is the natural place to track them, evict LRU, and route inbound messages by `session_id`.
- **WSS reconnect with replay** survives orchestrator restarts and short network blips; subprocess-per-run via Sprites Exec gave us reattach-with-scrollback but no message-level idempotency.
- **Clarification blocking is in-process.** Tool calls block on `asyncio.Future` keyed by `clarification_id`; no stdin write race, no sentinel-line parsing.

The cost: a bridge daemon to operate (boot, supervise, reconnect, evict). Worth it.

### 14.9 Cross-repo runs (post-v1 hook)

Filesystem has every connected repo under `/work/`, so a multi-repo task type drops in cleanly: the CLI's `cwd` becomes a parent dir, tool calls accept any path under `/work/`, and the run-finalize step pushes to N branches and opens N PRs. Not in v1; v1 task is single-repo and CLI `cwd` is the repo subdir.

### 14.10 Sandbox-Agent tools (slice 8)

The CLI ships its own toolset — `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `WebFetch`, etc. We do **not** re-implement them. Slice 8 adds exactly one custom tool, registered via an in-process MCP server in `apps/bridge/src/bridge/mcp/`:

- `ask_user_clarification(question: str, context: str | None = None) -> str` — emits `AskUserClarification` over WSS, blocks on the future, returns the answer.

Allowlist enforcement is via `ClaudeAgentOptions.allowed_tools` and per-tool hooks:

- `PreToolUse[Bash]` — parse the command, reject if it escapes `/work/<repo>/` (no `cd /etc`, no `rm -rf /`), reject `git push` to base branch.
- `PreToolUse[Write|Edit]` — reject paths outside the session's repo subdir.

Budget ceilings (per session):

- Wall-clock cap per `Bash` call: 5 min.
- Output truncation: 50 KB stdout/stderr per `Bash`.
- Per-session token cap: configurable on `Task.token_budget`, default 1M input + 500k output. Exceeding emits `ErrorEvent{kind:"token_budget_exceeded"}` and pauses the session.

### 14.9 User-Agent tools (slice 8b)

The User Agent calls these synchronously inside the orchestrator process. Each is a Python function the User Agent's Anthropic SDK invocation can call:

- `get_user_profile()` → returns user prefs, github_username, mode flags
- `list_user_repos()` → connected repos with introspection (language, package_manager, test_command, build_command, dev_command)
- `read_past_clarification(repo_id, question_summary)` → recall the last similar clarification's answer for this user (Mongo lookup; ~v1.1 personalization, may stub in slice 8b and fill in slice 11)
- `ask_user(question)` → emits `AskUserClarification` to FE, awaits `AnswerClarification`. Used when the User Agent decides "I genuinely cannot answer this."

The User Agent does **not** have direct access to the sandbox filesystem or to the Sandbox Agent's tools. By design, it sits *outside* the sandbox; if it needs sandbox state, it asks the Sandbox Agent (via stdin) or surfaces the question to the user.

### 14.10 System prompt design (`python_packages/agent_config/`)

- **Sandbox Agent** prompt: repo metadata injected (full_name, default_branch, language, test command). Project conventions injected if a `CLAUDE.md` exists in the repo. Hard rules: don't `rm -rf /`, don't push to base branch, don't expose secrets in commits, never reach outside the current repo subdir. Instructed to call `ask_user_clarification` when truly blocked rather than guessing.
- **User Agent** prompt: explains the user-agent's role (orchestrator-side, mediates between user and sandbox-agent). Lists the user's prefs + connected repos + introspection inline. Hard rules: never invent answers — only respond confidently when grounded in tool output; default to escalating ambiguous questions; preserve the user's intent in prompt enhancement (don't change requirements, only clarify them).

---

## 15. Git workflow inside the bridge (slice 9)

- All git ops happen inside `/work/<repo_full_name>/`. Each `provider.exec_oneshot` call sets `dir` per command; never `cd`s globally (so concurrent runs in the future stay isolated).
- Repo bootstrap (slice 5b clone op): `git clone --filter=blob:none https://x-access-token:<user_token>@github.com/<full_name>.git /work/<full_name>` — partial clone for fast first-pull on big repos. Then `git remote set-url origin https://github.com/<full_name>.git` to scrub the token.
- Branch naming: `octo/task-{slug}` where `slug` is 8 chars of the task id. Run 1 creates it; follow-up runs check it out and add commits.
- Commit messages: agent generates them; the agent-runner appends `Co-Authored-By: octo-canvas <bot@octo-canvas.dev>`.
- Push: HTTPS with the user's OAuth access token via `git -c http.extraheader="AUTHORIZATION: bearer <user_token>" push`. Token never written to `.git/config`.
- PR creation: githubkit `repos.create_pull_request` against `default_branch`. Body includes a deep link back to the platform task page.
- PR updates on follow-ups: just push more commits to the same branch — GitHub auto-updates the PR diff.
- Disconnect path (slice 5b remove op): `provider.exec_oneshot(["rm", "-rf", "/work/<full_name>/"])`. Other repos in `/work/` are untouched.

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
- `claude-agent-sdk` + the underlying `claude` CLI are sandboxed per Sprite; tools cannot reach the orchestrator filesystem. Bash and file tools are jailed to `/work/<repo>/` via SDK `PreToolUse` hooks plus filesystem-level isolation.
- **Bridge auth**: the bridge presents `Authorization: Bearer ${BRIDGE_TOKEN}` on the `/ws/bridge/{sandbox_id}` handshake. Tokens are minted by the orchestrator at sandbox provision time (slice 7), scoped to that single `sandbox_id`, persisted on `Sandbox.bridge_token_hash` (sha256), and rotatable via `POST /api/sandboxes/{id}/rotate-bridge-token` (slice 8 ships rotation as an admin-only endpoint behind `ALLOW_INTERNAL_ENDPOINTS`; full ops surface lands later). The bearer token is plaintext in the sprite env; it is NOT logged and NOT included in error responses.
- **Anthropic credentials — never enter the sprite.** Hard invariant (slice 7): the user has terminal + agent-Bash access inside the sprite, so anything readable from process env / `/proc/<pid>/environ` / on-disk config is presumed leaked. The real `ANTHROPIC_API_KEY` lives only in the orchestrator's process env (typed `pydantic.SecretStr` so it masks on every `repr`/`model_dump`/log). The bridge talks to api.anthropic.com via the orchestrator's `/api/_internal/anthropic-proxy/{sandbox_id}` route. Env vars piped to the bridge (verified against the `claude` CLI v2.1.118 binary): `CLAUDE_CODE_API_BASE_URL` + `ANTHROPIC_BASE_URL` (both set; the former is the higher-priority var, hedges against the [closed but unverified interactive-mode regression](https://github.com/anthropics/claude-code/issues/36998)) + `ANTHROPIC_AUTH_TOKEN=<bridge_token>` (Bearer-mode; CLI sends `Authorization: Bearer <bridge_token>`; takes priority over `ANTHROPIC_API_KEY`, which we deliberately omit). The proxy validates `Authorization: Bearer <bridge_token>` (sha256 + `hmac.compare_digest`) against `Sandbox.bridge_token_hash`, strips it, sets `x-api-key: <real_key>` from `BridgeRuntimeConfig._anthropic_api_key`, forwards. **Async streaming end-to-end** is mandatory: single shared `httpx.AsyncClient(http2=True)` lifespan-managed; inbound body via `request.stream()`; upstream via `client.send(req, stream=True)` + `aiter_raw()` + `StreamingResponse` + `BackgroundTask(upstream.aclose)`; `Cache-Control: no-cache` + `X-Accel-Buffering: no` on the response so SSE chunks aren't buffered by any intermediary. Cancellation propagates: bridge disconnect → route handler cancelled → `finally: aclose()` → upstream HTTP/2 stream RST → Anthropic stops billing. Per-sandbox rate limits + audit log land at the proxy. Future credential modes (`user_oauth`, `user_api_key`) flow through the same proxy with a different upstream resolution rule. See §14.7 + [slice 7 brief #6b](slice/slice7.md) for the slice-8 implementation contract.
- GitHub install tokens are one-time, scoped to a single `run_id`, expire 30 minutes after issue.
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
- Test DB is `octo_canvas_test`, dropped in a session-scoped fixture.
- GitHub API is mocked at the httpx layer in unit tests; layer 3 hits real GitHub.

### 16.5 Codegen pipeline

After any change to an orchestrator route or response model:

```bash
# Terminal 1
pnpm --filter @octo-canvas/orchestrator dev
# Terminal 2 (once orchestrator is up)
pnpm --filter @octo-canvas/api-types gen:api-types
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
| `SANDBOX_PROVIDER` | orchestrator (sprites \| mock; default `sprites`) | 4 |
| `SPRITES_TOKEN` | orchestrator (required when `SANDBOX_PROVIDER=sprites`) | 4 |
| `SPRITES_BASE_URL` | orchestrator (default `https://api.sprites.dev`) | 4 |
| `ANTHROPIC_API_KEY` | sprite (env at provision time, consumed by `claude` CLI via the bridge's `PlatformApiKeyCredentials`) AND orchestrator-hosted user-agent | 7 / 8b |
| `BRIDGE_TOKEN` | per-sprite — minted by orchestrator at provision (slice 7), presented on `/ws/bridge/{sandbox_id}` handshake (slice 8) | 7 |
| `ORCHESTRATOR_WS_URL` | sprite — bridge dials home (e.g. `wss://api.octo-canvas.dev`); env wired in slice 7, dialed in slice 8 | 7 |
| `MAX_LIVE_CHATS_PER_SANDBOX` | bridge (default `5`) — concurrent CLI processes per sprite before LRU eviction (only chats with no live web subscriber are evictable) | 8 |
| `IDLE_AFTER_DISCONNECT_S` | bridge (default `300`) — grace timer before killing a CLI whose web subscribers all disconnected | 8 |
| `CLAUDE_AUTH_MODE` | sprite (default `platform_api_key`) — selects which `ClaudeCredentials` impl the bridge uses | 7 |
| `BRIDGE_IMAGE_TAG` | orchestrator (default `latest`) — sprite image tag passed to `provider.create()` | 7 |
| `USER_AGENT_DAILY_USD_CAP` | orchestrator (per-user spend cap on user-agent LLM calls; default `5`) | 6b |
| `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | orchestrator | 10 |
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
7. `pnpm --filter @octo-canvas/api-types gen:api-types` so [packages/api-types/generated/schema.d.ts](../packages/api-types/generated/schema.d.ts) is real, not the stub.
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

### Slice 4 — Sandbox provisioning (the box exists) ✅ shipped

**Scope-narrow.** This slice ends at "the box exists, REST endpoints work, mock + Sprites providers behind one Protocol." It does **not** include cloning, reconciliation, exec, or PTY — those land in 5b/6/8.

**Adds:** `SpritesProvider` (real `sprites-py` SDK) and `MockSandboxProvider` behind the `SandboxProvider` Protocol. Opaque `SandboxHandle(provider, payload: dict[str, str])` so the backend stays swappable. `Sandbox` Mongo collection (one alive per user enforced at the routing layer, NOT at the index — see §4 forward-compat note). Redis hash for hot state (`sandbox:{id} → {status, public_url, last_active_at}`, 90s TTL — no queue yet). REST endpoints `POST /api/sandboxes`, `GET /api/sandboxes`, `POST /api/sandboxes/{id}/wake`, `.../pause`, `.../refresh`, `.../reset`, `.../destroy`. **`pause` is the manual force-pause** — Sprites' SDK has no force-hibernate verb, so the implementation kills active exec sessions via raw HTTP to `/v1/sprites/{name}/exec/{session_id}/kill` (rc37 SDK doesn't expose `kill_session`); Sprites' own idle timer then transitions to `cold` within seconds.
**Files:** `python_packages/sandbox_provider/src/sandbox_provider/{sprites.py,mock.py,interface.py}`; orchestrator `services/sandbox_manager.py`, `routes/sandbox.py`, `lib/provider_factory.py`, `lib/redis_client.py`.
**Risks:** Sprites SDK rc-only (rc37 on PyPI, rc43 docs at [docs/sprites/v0.0.1-rc43/python.md](sprites/v0.0.1-rc43/python.md); workspace pyproject sets `[tool.uv] prerelease = "allow"` so rc resolves); silent provider fallback (forbidden — empty `SPRITES_TOKEN` aborts startup); reset semantics (slice 4 uses sequential destroy+create; slice 5b switches to checkpoints).
**Acceptance:** `POST /api/sandboxes` creates a `Sandbox` doc and immediately calls `provider.create()`; the sprite shows up `warm` with a public URL right away. `wake` issues a no-op exec to force `cold→running`. `pause` kills active exec sessions and returns whatever the provider currently reports (warm, then cold within seconds via Sprites' idle); idempotent on `cold`. `refresh` resyncs status from the provider. `reset` rotates `provider_handle.id` on the same `Sandbox._id`, increments `reset_count`, returns the sandbox to `warm`. `destroy` marks the doc `destroyed`; user must re-`POST /api/sandboxes` to provision a new one (new `_id`).
**Out of scope:** WS endpoints (5a), cloning (5b), agent runs (6), PTY/file ops (8 — though Sprites already covers most of it, see §18 below).

### Slice 5a — Web ↔ orchestrator WS (control + events) ✅ shipped

The bridge↔orchestrator WS leg is **gone** — Sprites' SDK is outbound-driven. Only the web↔orchestrator WS remains.

**Adds:** `/ws/web/tasks/{task_id}` (Pydantic discriminated unions per §10.4); `seq`-replay from Mongo via `Resume{after_seq}` against an atomic per-task allocator (`seq_counters` raw collection, `findOneAndUpdate {$inc: {next: 1}}` upsert); 30s/90s `Ping`/`Pong`; web-side reconnect loop with jittered backoff (1s → 16s, ±25%). Redis pub/sub for cross-instance event fan-out (`task:{task_id}` channel) via a per-instance `TaskFanout` polling its own `PubSub` — `listen()` was rejected because redis-py's async `listen()` blocks on an empty subscription set and doesn't wake reliably when channels are added mid-flight. Per-subscriber backpressure tracking (`Subscription.last_dropped_seq`) drives `BackpressureWarning` emission. Wire-protocol TS codegen via `gen_wire_schema.py` → `pnpm dlx json-schema-to-typescript` → `packages/api-types/generated/wire.d.ts`. Dev-only inject endpoints `POST /api/_internal/tasks` + `POST /api/_internal/tasks/{id}/events` gated by `ALLOW_INTERNAL_ENDPOINTS`.
**Files:** `apps/orchestrator/src/orchestrator/ws/{web.py,task_fanout.py}`; `apps/orchestrator/src/orchestrator/services/event_store.py`; `apps/orchestrator/src/orchestrator/routes/internal.py`; `python_packages/shared_models/src/shared_models/wire_protocol/` (events.py, commands.py, adapters); `python_packages/shared_models/src/shared_models/scripts/gen_wire_schema.py`; `python_packages/db/src/db/models/{task.py,agent_event.py}`; `apps/web/src/hooks/useTaskStream.ts`; `apps/web/src/routes/_authed/tasks/$taskId.tsx`.
**Risks:** discriminated-union evolution (mitigated by `extra="ignore"` on every variant); cross-instance fan-out via Redis pub/sub must not become the source of truth (Mongo stays canonical); WS handshake auth has no native `Depends` parity (wrapped in `_resolve_user_for_ws`); 4xxx close codes only meaningful **after** `accept()` (handler accepts first, then validates+closes).
**Acceptance:** ✅ test event injected via internal endpoint shows up on the WS subscriber. Force-disconnect → jittered reconnect → `Resume{after_seq=lastSeq}` skips replay correctly. Two `TaskFanout` instances against one Redis cross-fan (in-process simulation; manual smoke for two real processes documented as followup). 82 orchestrator tests + 23 provider tests passing.

### Slice 5b — Cloning + reconciliation + Reset = `/work` wipe ✅ shipped

**Adds:** Provider widening — `fs_list`, `fs_read`, `fs_write`, `exec_oneshot` on `SandboxProvider` (Sprites impl wraps the SDK; mock implements an in-memory FS sufficient for tests). On connect-repo, orchestrator calls `provider.exec_oneshot(handle, ["git", "clone", ...], env={GITHUB_TOKEN: ...})` to clone into `/work/<full_name>/`. After successful clone+install, **create a `clean` checkpoint** via `provider.snapshot(handle, comment="clean")`. Reset switches to `provider.restore(handle, "clean")` instead of destroy+create — milliseconds, repo state preserved, see [python.md → Checkpoints](sprites/v0.0.1-rc43/python.md). Reconciliation: orchestrator periodically calls `provider.fs_list(handle, "/work")` and diffs against `Repo` rows where `sandbox_id == this`; issues clone/remove ops to converge.
**Files:** `python_packages/sandbox_provider/src/sandbox_provider/{sprites.py,mock.py}` (widen the impls); `apps/orchestrator/src/orchestrator/services/reconciliation.py`.
**Risks:** install-token leakage in `.git/config` (set `extraheader` at command time, never persist — see §19 #12); race between connect-repo and sandbox provision (queue clone op in Mongo until sandbox is `warm` or `running`); clone retries when sprite is `cold` (Sprites auto-warms on exec, so this just-works).
**Acceptance:** connect three repos against a running sandbox → all three end up cloned to `/work/<full_name>/`, `clone_status="ready"`, `Repo.sandbox_id` populated. After clone+install, a `clean` checkpoint exists. Reset → restore_checkpoint → repos still present, working trees clean. Disconnect one → directory removed via `provider.exec_oneshot(["rm", "-rf", path])`, row deleted.

### Slice 6 — IDE shell: file tree + file editor + terminal + dummy chat panel

**Pulls forward what was old slice 8 (PTY + FS) and wraps it in a VS Code-style layout.** First slice that lets the user actually *see and touch* the sandbox: browse cloned repos in a file tree, open files in Monaco, save with sha-based If-Match, run shell commands in xterm.js terminals (multi-tab, reattach via Sprites scrollback), and see a placeholder Chats panel for slice 8.

**Adds:** Provider Protocol gains `fs_rename` + `fs_watch_subscribe`. Orchestrator REST `GET/PUT/DELETE /api/sandboxes/{id}/fs` (path-traversal validated server-side; `If-Match: <sha>` for save-conflict detection). PTY broker `/ws/web/sandboxes/{id}/pty/{terminal_id}` (Sprites Exec passthrough with reattach via Redis hash `pty:{sandbox_id}:{terminal_id}`). FS-watch broker `/ws/web/sandboxes/{id}/fs/watch` (single Sprites subscription per active sandbox, ≤4 Hz coalesce, Redis pub/sub fan-out across instances). Wire-protocol additions `FileEditEvent`, `RequestOpenPty`, `RequestClosePty`, `ResizePty` (declared in §10.4 but not yet shipped). Web: a new `/_authed/sandbox` page with four collapsible regions (file tree left, Monaco editor center, xterm.js terminal bottom, dummy Chats right). Dashboard becomes a router.
**Files:** `python_packages/sandbox_provider/src/sandbox_provider/{interface.py, sprites.py, mock.py}` (Protocol widening); `apps/orchestrator/src/orchestrator/routes/sandbox_fs.py`, `ws/{pty.py, fs_watch.py}`, `services/fs_watcher.py`; `apps/web/src/routes/_authed/sandbox.tsx`, `components/ide/{Layout, FileTree, FileEditor, Terminal, Terminals, ChatsPanel}.tsx`, `lib/{fs.ts, pty.ts, fsWatch.ts}`, `hooks/{useFileTree, useOpenFile, useTerminal, useFsWatch, usePanelLayout}.ts`.
**Risks:** path-traversal validation must be airtight (server-side helper + 20-input test suite); `fs/watch` storms during bulk operations (rate-cap at 100/s, single `BackpressureWarning` per minute); Monaco bundle size (lazy import); xterm.js + Sprites binary stream demux; PTY reattach Redis-hash leak on FE crash (sweeper job in slice 10, lightweight expiry in slice 6).
**Acceptance:** a signed-in user with a connected repo opens `/_authed/sandbox`, browses files, edits + saves a file (verified via terminal `cat`), runs commands in two terminal tabs, refreshes the browser and sees terminals reattach with scrollback, edits via terminal and watches the file tree update via `fs/watch`. The "+ New chat" button shows a "Coming in slice 8" toast.
**Out of scope (slice 6):** sprite image bake (slice 7). Bridge daemon, agent runtime, `Chat` data model, MCP (slice 8). User Agent (slice 8b). Git push, PR creation (slice 9). HTTP preview proxy already absorbed (Sprites' built-in URL surfaces in the IDE top bar).

### Slice 7 — Sprite image bake + runtime installation + agent_config bootstrap

**Makes the sandbox ready for the slice-8 agent.** Bakes everything the agent will need into the sprite image: Node ≥ 20, the pinned `claude` CLI binary, runtime managers (nvm/pyenv/rbenv), the bridge wheel, a static system-package baseline. Fills `python_packages/agent_config/` with the `ClaudeCredentials` Protocol, dev-agent prompt template, and tool allowlist. Ships a bridge **skeleton** that boots and idles cleanly (no WSS connect — that's slice 8).

**Adds:** `apps/bridge/Dockerfile.sprite` (multi-stage; pinned versions in `apps/bridge/CLAUDE_CLI_VERSION` + Dockerfile). CI workflow `.github/workflows/sprite-image.yml` builds + pushes the image on every main-branch merge with in-build smoke (`bash -l -c 'claude --version && python -m bridge.main --self-check && nvm --version'`). `python_packages/agent_config/` filled in (`credentials.py`, `prompts/dev_agent.py`, `tools/allowlist.py`). `apps/bridge/` workspace member created (skeleton: `main.py` with `--self-check` + idle loop, `config.py` with pydantic-settings). Provider Protocol `create()` widens to accept `image_tag: str | None`. `SandboxManager.get_or_create` mints `BRIDGE_TOKEN`, hashes to `Sandbox.bridge_token_hash`, passes plaintext + `ORCHESTRATOR_WS_URL` + `ANTHROPIC_API_KEY` + `CLAUDE_AUTH_MODE="platform_api_key"` into sprite env. Dashboard repo card surfaces "Agent setup — will install Node 20, Python 3.12" banner driven by `RepoIntrospection.runtimes`.
**Files:** `apps/bridge/{Dockerfile.sprite, CLAUDE_CLI_VERSION, sprite-baseline-packages.txt, pyproject.toml}`, `apps/bridge/src/bridge/{main.py, config.py, __init__.py}`; `python_packages/agent_config/src/agent_config/{credentials.py, prompts/dev_agent.py, tools/allowlist.py}`; `python_packages/sandbox_provider/src/sandbox_provider/{interface.py, sprites.py, mock.py}` (`image_tag` arg); `apps/orchestrator/src/orchestrator/services/sandbox_manager.py` (provision-time env mint); `apps/web/src/components/RepoCard.tsx` (banner); `.github/workflows/sprite-image.yml`.
**Risks:** Sprites' image-registry constraints (verify before CI; fallback is per-boot install scripts, slower); CLI version drift dev↔sprite (boot-time `claude --version` check refuses to start on mismatch); nvm/pyenv activation only in login shells (`bash -l -c` convention from slice 5b stays); image bloat (~few-hundred MB acceptable for v1); CI registry creds in PRs (build-but-don't-push for forks).
**Acceptance:** image builds + pushes in CI; `docker run --rm <image> bash -l -c 'claude --version && python -m bridge.main --self-check'` exits 0; provisioning a sandbox with `BRIDGE_IMAGE_TAG=<new-sha>` results in a sprite with `claude --version` working, bridge process idling cleanly (no WSS), `nvm install 20` works from the slice-6 terminal; `Sandbox.bridge_token_hash` populated, plaintext never logged; repo card "Agent setup" banner renders.
**Out of scope (slice 7):** WSS handler (`/ws/bridge/{sandbox_id}`), `Chat` model, agent invocation — all slice 8. Hard token-budget enforcement, User Agent — slice 8b. Git push, PR — slice 9.

### Slice 8 — Chats + Bridge + `claude` CLI driven by `claude-agent-sdk` (passthrough)

**The agent runtime itself.** Builds on slice 6 (IDE shell) and slice 7 (sprite image with `claude` CLI + bridge wheel). Bridge process inside the sprite dials home over `/ws/bridge/{sandbox_id}` and supervises N concurrent `claude` CLI subprocesses driven by `claude-agent-sdk`. `Chat ↔ Claude session 1:1`; `Chat` is the user-facing primitive (renamed from earlier-draft `Task`). CLI processes **stay alive** between user messages while the user is connected — direct feed via the live SDK client; `--resume` is the cold-path fallback only (CLI was killed). Multi-chats per sandbox (`MAX_LIVE_CHATS_PER_SANDBOX = 5`); multi-chats per repo via git worktrees under `/work/<repo>/.octo-worktrees/chat-<slug>/`. Auth = API key only via `PlatformApiKeyCredentials`; `ClaudeCredentials` Protocol leaves room for OAuth and BYOK without protocol or schema changes.

**Adds:** `Chat` doc (replaces slice-5a `Task` stub; rename in this slice) + `ChatTurn` (per-turn) + `AgentEvent` widened with `claude_session_id`. WS endpoint rename `/ws/web/tasks/{task_id}` → `/ws/web/chats/{chat_id}` (and Redis channel `task:{id}` → `chat:{id}`). `POST /api/chats`, `POST /api/chats/{id}/messages`, `POST /api/chats/{id}/cancel`, `POST /api/chats/{id}/archive`. `POST /api/sandboxes/{id}/rotate-bridge-token` behind `ALLOW_INTERNAL_ENDPOINTS`. Bridge process at `apps/bridge/src/bridge/{ws_client.py, session_mux.py, mcp/octo_server.py, ringbuf.py, credentials/}` widens slice-7's skeleton with WSS dialer (jittered reconnect 1→16s ±25%, ring buffer 1000 frames or 1MB per chat, `Hello{last_acked_seq}` replay), session multiplexer (per-chat `ClaudeAgentClient` from `claude-agent-sdk`; `cwd` = chat's worktree path; `resume=claude_session_id` only when `proc.is_alive() == False`; LRU evict only chats with no live web subscriber after `IDLE_AFTER_DISCONNECT_S = 300` grace), in-process MCP server registering `ask_user_clarification(question, context?) -> str` (blocking on `asyncio.Future` keyed by `clarification_id`; 5-min timeout). Orchestrator: `/ws/bridge/{sandbox_id}` handler (`apps/orchestrator/src/orchestrator/ws/bridge.py`), bridge-side wire-protocol Pydantic union (`python_packages/shared_models/src/shared_models/wire_protocol/bridge.py`), bridge-owner Redis routing (`bridge_owner:{sandbox_id}` 60s TTL + `bridge_in:{sandbox_id}` pub/sub for cross-instance commands), per-sandbox `BridgeSession` service that turns inbound bridge frames into `agent_events` rows + `chat:{chat_id}` Redis publishes. Bridge dispatch: `if proc.is_alive(): proc.send(text) else: proc = spawn(resume=claude_session_id); proc.send(text)`. Web: replaces slice-6's dummy ChatsPanel with a real chat list + active-chat view; supports switching between chats (each persists scroll + last seen seq); `AskUserClarification` modal.
**Files:** `apps/orchestrator/src/orchestrator/routes/chats.py`, `services/{bridge_session.py, bridge_owner.py}`, `ws/bridge.py`; `apps/bridge/src/bridge/{ws_client.py, session_mux.py, ringbuf.py, mcp/octo_server.py}`; `python_packages/shared_models/src/shared_models/wire_protocol/bridge.py` + adapter; `python_packages/db/src/db/models/{chat.py (rename + widen Task), chat_turn.py, agent_event.py (widen)}`; `apps/web/src/components/ide/ChatsPanel.tsx` (real impl), `lib/chats.ts`.
**Risks:** worktree-vs-clone-layout migration (slice 6 IDE file tree must root at the active worktree, not the bare repo); bridge-owner failover races under churn (mitigated by short Redis TTL + `Hello{last_acked_seq}` replay); MCP `ask_user_clarification` blocking forever (5-min hard cap with abort); `acceptEdits` permission mode is permissive — Bash + path hooks are the safety net; CLI version drift between dev and sprite (slice 7's pin + boot-time check); orchestrator restart drops in-flight `UserMessage` (mitigation: write `ChatTurn` first, then send; on boot scan for `queued` turns and re-send via `frame_id` idempotency).
**Acceptance:** with two connected repos, the user opens a chat on repo A and "add HELLO.md saying hi" → bridge spawns CLI, agent edits files (visible live in slice-6 file tree + editor), commits locally on `octo/chat-<slug>`. Follow-up "make heading bigger" lands on the same `claude_session_id` (verified in Mongo via direct feed, no `--resume`). User opens a second chat on repo B in parallel; both are live; user switches between them in the right panel. User disconnects (closes tab) → after 5 min grace the CLI is killed; reopens tab → bridge `--resume`s the session; transcript intact. Killing the orchestrator mid-turn → bridge ring-buffer replays missed frames after reconnect; no event loss in `agent_events` seq. `ask_user_clarification` blocks the agent, surfaces to FE, user types answer, agent unblocks. Wrong `BRIDGE_TOKEN` → close 4001.
**Out of scope (slice 8):** User Agent (slice 8b). Git push + PR creation (slice 9). Hard token-budget enforcement, OAuth/BYOK Claude credentials. 24h Mongo / S3 archive (slice 10).

### Slice 8b — User Agent layer (toggle + prompt enhancement + clarification routing)

Builds the orchestrator-hosted User Agent on top of slice 8. Off-by-default; user opts in.

**Adds:** `User.user_agent_enabled` + `user_agent_mode` fields (see §8); `PATCH /api/me/user-agent` endpoint; new web message types `PromptEnhancedEvent`, `AgentAnsweredClarification`, `OverrideAgentAnswer`, `AnswerClarification` (see §10.4). User-Agent process inside the orchestrator: an Anthropic SDK invocation per user message and per sandbox-agent clarification, with the tools listed in §14.9. UI: a settings panel with the master toggle + mode radio (on dashboard or `/settings`); inline indicator on the chat page showing "User-agent: on (handles)" / "off"; per-event display of `PromptEnhancedEvent` (collapsible original/enhanced); `AgentAnsweredClarification` rendered with an Override button + countdown until `override_window_ms` closes. Hard token-budget cut-off lands here too (slice 8 is warn-only).
**Files:** `apps/orchestrator/src/orchestrator/services/user_agent.py` (Anthropic SDK invocation + tool implementations); `routes/me_user_agent.py` (PATCH endpoint); web `components/UserAgentToggle.tsx`, `components/PromptEnhancedDisplay.tsx`, `components/AgentAnswerWithOverride.tsx`.
**Risks:** **two-LLM coherence** — User Agent and Sandbox Agent must not contradict each other; the User Agent's system prompt forbids inventing answers and instructs it to escalate when unsure. **Override race** — between User Agent emitting `AgentAnsweredClarification` and the user clicking Override, the sandbox-agent has already been fed the answer and may have started acting; the orchestrator writes a correction `UserMessage` and the sandbox-agent's prompt must instruct it to handle corrections gracefully. **Per-event LLM cost** — User Agent runs on every user message and every clarification; budget so a chatty agent doesn't 10x our LLM bill. **Toggle race** — if the user flips the toggle mid-chat, the orchestrator finishes the current event with the prior setting and applies the new one to the next event.
**Acceptance:** with `user_agent_enabled=false`, slice 8 behaviour is unchanged. With `user_agent_enabled=true`, all four of these must work:

- User types "fix the failing tests" → orchestrator emits `PromptEnhancedEvent{original, enhanced}` to FE before the sandbox sees anything; the sandbox receives the enhanced prompt.
- With `mode=agent_handles`, sandbox-agent asking "which test command should I use?" → User Agent looks up `Repo.introspection.test_command`, sends that as `AnswerClarification` to the bridge, emits `AgentAnsweredClarification{question, answer, override_window_ms: 8000}` to FE. User does nothing → sandbox-agent runs the command. User clicks Override within 8s → FE sends `OverrideAgentAnswer`; orchestrator writes the correction; sandbox-agent re-prompts the user.
- With `mode=user_answers_all`, the same clarification surfaces to FE as `AskUserClarification` with `agent_attempted={attempted: true, reasoning: "test_command from introspection is 'pnpm test'"}`. The User Agent does *not* answer it, but annotates so the user can decide.
- Toggle the agent off mid-chat → next user message and next clarification go through as raw passthrough.

### Slice 9 — Git ops + PR creation

**Adds:** `git push` + `repos.create_pull_request` via githubkit (run inside the bridge process per chat, not the orchestrator); PR URL surfaced on `Chat` + UI; follow-ups push more commits to the same branch. The chat's worktree at `/work/<repo>/.octo-worktrees/chat-<slug>/` is the push source.
**Files:** `apps/bridge/src/bridge/git/` (push helpers, path-scoped to the chat's worktree); `apps/bridge/src/bridge/session_mux.py` post-turn hook to call push + PR-open.
**Risk:** auth-token leakage in `.git/config` — extraheader at command time, never persist. Different repos in the same sandbox can have different installation tokens (different orgs); orchestrator mints per-repo tokens at chat-start time and passes them via WSS frame, not at sandbox provision.
**Acceptance:** the slice-8 chat ends with a real PR opened against the connected repo, linked from the chat panel. A follow-up message produces a second commit on the same PR.

### Slice 10 — HTTP preview (use Sprites' built-in URL)

**Note**: surfacing the per-sandbox URL is already done by slice 6 (top-bar link in the IDE). Slice 10 only widens the auth posture controls.

**No proxy to build.** Sprites already gives every sandbox `https://{name}-{org}.sprites.app`, and slice 6's IDE top bar surfaces it as a link. Slice 10 widens the auth posture controls.

**Adds:** UI auth-posture toggle ("Private — requires Sprites session" vs "Public — anyone with the link"). Auth posture configurable via `provider.update_url_settings(handle, auth="sprite"|"public")`; default is `"sprite"`. Optional: an orchestrator-side redirect at `/api/sandboxes/{id}/preview` that 302s to the URL, so we control link sharing centrally.
**Files:** `apps/web/src/components/ide/SandboxTopBar.tsx` (auth-posture toggle alongside the existing link); `apps/orchestrator/src/orchestrator/routes/sandbox.py` (`/preview` redirect).
**Risks:** secrets in dev-server output; CSP/iframe issues if we want to embed in our UI; cookie-domain leakage. Ship preview-in-new-tab first; embed later.
**Acceptance:** user runs `pnpm dev` in a sandbox terminal; clicks the preview link in the IDE top bar; new tab loads. Toggling Public/Private flips Sprites' auth posture.

### Slice 11 — Event log persistence (S3)

**Adds:** archival job that, on `Chat` completion (or after N days of inactivity), writes the chat's events to `s3://{S3_BUCKET}/chats/{chat_id}.ndjson` and prunes from Mongo (keeping the last N for active UI hydration). `GET /api/chats/{chat_id}/events` paginates Mongo + S3 transparently. Also: PTY-reattach Redis-hash sweeper (the slice-6 followup) and `Sandbox.bridge_last_acked_seq_per_chat` cleanup (slice 8 followup).
**Files:** `apps/orchestrator/src/orchestrator/jobs/archive_chat.py`; `services/event_store.py`.
**Risk:** S3 vs MinIO config drift — keep the client behind an interface.
**Acceptance:** completed chat's events disappear from Mongo and reappear when paginating in UI; S3 object exists.

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
8. **Webhook delivery in local dev** — slice 2's GitHub redesign deleted webhooks; this risk is moot. Listed for historical context.
9. **Sprites SDK is rc-only** — `sprites-py` ships only as `0.0.1rcN` versions on PyPI. Workspace pyproject sets `[tool.uv] prerelease = "allow"` so the resolver picks them up. rc43 docs at [docs/sprites/v0.0.1-rc43/python.md](sprites/v0.0.1-rc43/python.md); rc37 is the current installable. Pin floor to whatever's been validated in tests.
10. **Sprites token discipline** — `SPRITES_TOKEN` is server-side only; **never** flows to the FE. Orchestrator brokers all sprite traffic. Empty `SPRITES_TOKEN` with `SANDBOX_PROVIDER=sprites` aborts startup; CI must assert prod manifests don't carry `SANDBOX_PROVIDER=mock`.
11. **Per-user sandbox = noisy-neighbor surface** — all of one user's tasks share one sprite. v1 limits to one active run at a time per sandbox (queue the rest). Sprites manages CPU/RAM/disk; if cost-spiral becomes real, contact Sprites about per-sprite limits.
12. **Multi-repo install token scoping** — different repos in the same sandbox can be on different GitHub App installations (different orgs). Mint **per-repo, per-run** install tokens at task-start time and pass via the agent-runner's `task_json`; never share a token across repos or persist on the sandbox filesystem.
13. **Reconciliation correctness (slice 5b)** — the diff between `Repo` rows where `sandbox_id == this.sandbox_id` and the sprite's `/work` listing (via `provider.fs_list`) must converge: missing on disk → clone; on disk but not bound to this sandbox → remove. Reconciliation is per-sandbox, never per-user. Test the four-quadrant matrix explicitly.
14. **Sandbox name reuse on Reset** — `octo-sbx-{sandbox_id}` is deterministic and reused across resets (same `Sandbox._id`). The `provider.destroy → provider.create` sequence in `SandboxManager.reset` is sequential, so Sprites finishes destroying the old sprite before the new one is created. Don't parallelize.
15. **No disk-cap eviction yet** — Sprites manages storage; we don't run our own `du`-based eviction. If real users blow past the underlying quota, Reset (which clears the filesystem) is the escape hatch and slice 5b's `clean` checkpoint makes it cheap.

16. **Transport choice — WS for the web leg only** — Sprites' SDK handles the orchestrator↔sandbox leg over WSS; we don't operate a custom protocol there. gRPC stays off the table for the web leg (browsers don't speak it natively, gRPC-Web is more cost than benefit). See §10.1.

17. **No incoming bridge connection** — there is no daemon inside the sandbox dialing back to us. The orchestrator drives sprites outbound via the SDK. Anything you read in older drafts about `ClientHello`, bridge tokens, or `/ws/bridge/...` is deleted; see §10 and §14.

18. **PTY brokerage, not direct FE→Sprites** — orchestrator brokers the PTY WS so the FE never sees `SPRITES_TOKEN`. Use Sprites' `Attach to Exec Session` on reconnect to get scrollback replay. See §10.5.

19. **Sprites Exec sessions persist across orchestrator restarts** — `max_run_after_disconnect` defaults to forever for TTY. After a restart, look up the active `session_id` from Mongo or Sprites' `list_sessions`, and re-attach instead of killing.

20. **Cross-instance event fan-out via Redis pub/sub** — at multi-orchestrator-instance scale, an active agent run is owned by one instance (it holds the Sprites Exec stream). Other instances with web subscribers on the same task pick up events via Redis pub/sub on `task:{task_id}`. Mongo retains the truth; pub/sub is the live broadcast channel. See §10.7.

21. **Backpressure caps + drop policy** — orchestrator buffers ≤1000 events per (run, web subscriber); PTY drops frames under back-pressure (terminals can drop, agent events can't because of `seq`-replay); file-watch coalesces by path at ≤4 Hz. Never grow buffers unbounded; alert on drops. See §10.6.

22. **Reconnect backoff has jitter** — web reconnect: `0.5, 1, 2, 4, 8, 16, 30…` seconds with ±25%. Without jitter, an orchestrator restart causes a thundering-herd reconnect spike.

23. **Capacity caps + hot-shedding** — each orchestrator instance soft-caps at 5000 web WS + 200 active Sprites Exec sessions. New sandbox spawns get 503 if no instance has headroom; existing connections aren't degraded. See §10.7.

24. **Reset preserves repo connections; Destroy doesn't preserve the `Sandbox` doc id** — `POST /api/sandboxes/{id}/reset` keeps `Sandbox._id` and `Repo.sandbox_id` references, just rotates `provider_handle`. `POST /api/sandboxes/{id}/destroy` marks the doc destroyed; the user's next `POST /api/sandboxes` creates a *new* doc with a *new* id, and slice 5b will re-bind `Repo.sandbox_id` accordingly.

25. **User Agent is opt-in and visible** (slice 8b) — `User.user_agent_enabled` defaults to `false`. When enabled, **every** action the User Agent takes is surfaced to the FE: `PromptEnhancedEvent` shows original vs enhanced; `AgentAnsweredClarification` shows the answer with an 8s override countdown. Users must always be able to see what was answered on their behalf and override it. No silent decisions. See §14.1.

26. **Override race in slice 8b** — by the time the User Agent emits `AgentAnsweredClarification`, the answer has already been written to the sandbox-agent's stdin and the sandbox-agent may have started acting on it. Override is therefore an **interrupt + correct**, not a "withhold the answer." The orchestrator writes a correction line to stdin (`# CORRECTION: previous answer was incorrect, do not act on it; awaiting new answer`); the sandbox-agent's prompt instructs it to honor corrections. Don't try to gate the answer behind the override window — the latency would be terrible.

27. **Two-LLM coherence** — User Agent and Sandbox Agent must not contradict each other. The User Agent's system prompt forbids inventing answers and instructs it to escalate when its tool data doesn't directly answer the question. The Sandbox Agent treats answers from stdin as ground truth (because the User Agent grounded them in user prefs / introspection); but it must also detect contradictions ("the user said pnpm but the lockfile is yarn.lock") and escalate via `ask_user_clarification` rather than guessing.

28. **User-Agent LLM cost** — slice 8b runs a User-Agent invocation on every user message and every sandbox-agent clarification. Budget caps: per-user spend cap (configurable, default $X/day) enforced before each User-Agent call; if exceeded, fall back to passthrough mode and surface a banner. Monitor average User-Agent calls per task; if it >5x's the Sandbox-Agent's call count, something is misrouted.

29. **Sandbox-agent clarification timeout** — `ask_user_clarification` blocks reading stdin. v1 caps that wait at **5 minutes**; if no answer arrives, the sandbox-agent emits `ErrorEvent{kind: "clarification_timeout"}` and the run aborts. Otherwise a closed FE tab + dropped User Agent could deadlock the sandbox forever.

30. **Pause kills *all* exec sessions in slice 4** — slice 4 has no agent runs yet, so this is harmless. From slice 8 onward Pause must be narrowed to skip the bridge process and any agent-spawned exec sessions; otherwise clicking Pause mid-chat would kill the agent. The pause implementation is in [`python_packages/sandbox_provider/src/sandbox_provider/sprites.py`](../python_packages/sandbox_provider/src/sandbox_provider/sprites.py); revisit at slice 8.

- **Slice 0** ✅ scaffolding shipped
- **Slice 1** ✅ shipped (GitHub OAuth + user persistence)
- **Slice 2** ✅ shipped (OAuth `repo` scope + repo connection)
- **Slice 3** ✅ shipped (repo introspection — Trees + Contents detection, dev_command, per-field user overrides)
- **Slice 4** ✅ shipped (sandbox provisioning on Sprites SDK; opaque `SandboxHandle`; 7-state machine; Reset/Pause/Destroy distinct; auto-hibernation delegated to Sprites)
- **Slice 5a** ✅ shipped (web↔orchestrator WS `/ws/web/tasks/{task_id}`; Pydantic discriminated unions; atomic per-task seq via `seq_counters`; Mongo-replay → Redis pub/sub live mode via `TaskFanout`; 30/90s heartbeat; jittered FE reconnect; wire-protocol TS codegen; dev-only inject endpoints)
- **Slice 5b** ✅ shipped (provider widened with exec/fs/snapshot/restore; reconciliation service event-driven with safety net + 15min wall-clock timeout; Reset = `rm -rf /work && mkdir -p /work` + reconcile re-clone preserving sprite identity; one-time git setup at fixed `/etc/octo-canvas/` paths via `GIT_CONFIG_GLOBAL`; `apt-get` via `sudo -n`; `exec_oneshot` retries WS-handshake timeouts up to 6× / 63s backoff; introspection deepened with runtimes + system_packages on `RepoIntrospection` and `IntrospectionOverrides`; activity banner on the dashboard for every reconciler phase)
- **Slices 6 – 10** ⬜ not started; briefs to be authored slice-by-slice.

**Plan rewrites on 2026-05-02** following the rc43 SDK docs:

- §10 transport: dropped the bridge↔orchestrator WS leg (Sprites' SDK is outbound-only — but Exec WSS is bidirectional once opened, like SSH); web↔orchestrator WS is the only custom protocol.
- §13 sandbox lifecycle: state machine maps onto Sprites' `cold | warm | running` enum directly; no idle-hibernation job; reset uses checkpoints (slice 5b).
- §14 agent runtime: **two-agent architecture** — Sandbox Agent runs as a `claude` CLI subprocess driven by `claude-agent-sdk` and supervised by a long-lived bridge daemon (slice 8); orchestrator-hosted User Agent (slice 8b, opt-in) sits as MITM doing prompt enhancement and clarification routing.
- §18 slice plan: slice 6 = IDE shell (FS/editor/terminal); slice 7 = sprite image bake + runtime managers + agent_config; slice 8 = chats + bridge + CLI (passthrough); slice 8b = User Agent. 5a was web-WS-only; 5b added clone+reconciliation+checkpoints; HTTP preview collapses to surfacing Sprites' built-in URL (slice 6 + slice 10).
- §19 risks: replaced bridge-WS-specific gotchas with Sprites SDK realities; added user-agent risks (#25–#29: visible-by-default, override race, two-LLM coherence, LLM cost cap, clarification timeout).

Repo metrics (from latest [`/graphify`](../graphify-out/GRAPH_REPORT.md) run, 2026-05-01): **107 files (~75k words) · 443 nodes · 633 edges · 89 communities**. Extraction quality: 76% EXTRACTED · 24% INFERRED (avg confidence 0.71) · 0% AMBIGUOUS. Top community hubs reflect the shipped slices 0–3: *Repo Introspection Architecture / Tests*, *Command Detection*, *Package Manager Detection*, *Primary Language Detection*, *FastAPI App & Health*, *GitHub OAuth Wrapper*, *Mongo Lifecycle & Collections*, *Repo Models & Sandbox API*, *Type Bridges (Pydantic→TS)*, *Frontend Repo API Client / Query Hooks*, *Project Docs & Slice Discipline*, *Risks & Gotchas*. Use `/graphify --update` (incremental, cheap) after every shipped slice; full rebuild only when the user asks. See [AGENTS.md §2.7](../AGENTS.md) for query workflow and verification rules.

---

## 21. Concrete next steps (do these in order)

1. ~~**Sign off slice 4**~~ — done 2026-05-02; brief frozen.
2. ~~**Author `slice5a.md`**~~ — done.
3. ~~**Implement slice 5a**, ship, sign off.~~ — done 2026-05-02; brief frozen.
4. ~~**Author `slice5b.md`**~~ — done.
5. ~~**Implement slice 5b.**~~ — done 2026-05-02; brief frozen. **Reset semantics shifted mid-slice** from "checkpoint restore" to "wipe `/work` + reconcile re-clone" because the checkpoint path was visually indistinguishable from a no-op. Sprite identity (and all non-`/work` state — git config, apt cache) is preserved across Reset.
6. ~~**Author `slice6.md`**~~ — done 2026-05-02. IDE shell: file tree + Monaco + xterm.js terminal + dummy chat panel.
7. ~~**Author `slice7.md`**~~ — done 2026-05-02. Sprite image bake + runtime install + `agent_config` bootstrap.
8. ~~**Author `slice8.md`**~~ — done 2026-05-02. Chats + bridge + `claude` CLI driven by `claude-agent-sdk` (passthrough). `Task → Chat`, `AgentRun → ChatTurn` rename. CLI stays alive while user connected.
9. **Implement slice 6** (IDE shell), ship, sign off → slice 7 (sprite image bake) → slice 8 (chats + bridge + CLI) → slice 8b (User Agent) → slice 9 (git push + PR) → slice 10 (HTTP preview controls) → slice 11 (S3 archive).

Do **not** start slice N+1 implementation before the slice N brief is signed off and the slice N+1 brief is reviewed. Hard rule from every prior slice brief — "do not start the next task automatically" — applies for every slice transition.
