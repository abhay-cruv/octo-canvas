# Setup brief — bilingual monorepo scaffolding (Python backend + TS frontend)

You are setting up the **base scaffolding** for a new project on a fresh, empty repository. This is the **first** task in the project. **Do not write any business logic, route handlers, database models, UI components, or feature code in this task.** Your job is to lay down the skeleton: directory structure, package manifests, tooling configs, and minimal placeholder entry points that prove the build, dev, and test commands work end-to-end across both languages.

After this task is complete, subsequent tasks will fill in features one by one. Treat this as a foundation pour, not a build.

---

## The product (one paragraph of context)

The product is a developer tool with two future modes — dev mode and vibe mode — but **only dev mode is in scope for v1**, and even dev mode is not being built in this task. In dev mode, a user connects a GitHub repository, files coding tasks via chat, and an AI agent (Claude Agent SDK, Python) running inside a remote sandbox (Fly.io Sprites) makes the changes, runs tests, and opens a pull request back to GitHub. Vibe mode (greenfield project generation with multiple specialized agents) is deferred. Architecture should leave room for it but not scaffold it.

You don't need to build features now. Knowing this much is enough to name packages sensibly and place files in the right folders.

---

## The tech stack — lock these in exactly

### Backend ecosystem (Python)

Both the orchestrator service and the bridge process (which will run inside Sprites) are Python.

- **Language:** Python 3.12+
- **Package manager:** **uv** (modern, fast, with first-class workspace support). Do not use pip directly, Poetry, conda, or rye.
- **Web framework:** FastAPI (≥ 0.115), with `fastapi[standard]` to pull uvicorn and the standard ecosystem.
- **ASGI server:** uvicorn (dev), gunicorn + uvicorn workers (production — not configured in this task).
- **ODM:** Beanie (Pydantic + Motor for MongoDB).
- **Auth library:** Authlib (will be wired in slice 1, **not** in this scaffolding task).
- **HTTP client:** httpx.
- **GitHub integration:** githubkit (modern, async, fully-typed; do not use PyGithub).
- **WebSocket on orchestrator:** FastAPI's built-in WebSocket support.
- **WebSocket client (bridge):** the `websockets` library.
- **Agent SDK (bridge only):** `claude-agent-sdk` (Python).
- **Git operations (bridge only):** GitPython.
- **Logging:** structlog.
- **Settings/env:** pydantic-settings.
- **Validation:** Pydantic v2 (comes with FastAPI).
- **Linting + formatting:** ruff (replaces black, isort, flake8 — one tool for everything).
- **Type checking:** Pyright (`uv run pyright`).
- **Testing:** pytest + pytest-asyncio.

### Frontend ecosystem (TypeScript)

- **Language:** TypeScript 5.x with `strict: true` and `noUncheckedIndexedAccess: true`.
- **Package manager:** pnpm (≥ 9). Do not use npm or yarn.
- **Framework:** React 18 + Vite (Vite SPA, **not** Next.js).
- **Routing:** TanStack Router (file-based via the Vite plugin).
- **Data fetching:** TanStack Query.
- **API client:** `openapi-fetch` (typed against generated types from FastAPI's OpenAPI schema).
- **Styling:** Tailwind CSS.
- **Components:** shadcn/ui (initialized but no components added yet).
- **Real-time:** native browser WebSocket API.
- **Linting:** ESLint + Prettier.
- **Testing:** Vitest.

### Cross-language tooling

- **Monorepo orchestrator:** Turborepo. It runs commands across both pnpm workspaces and uv workspaces.
- **API type generation:** `openapi-typescript` consumes FastAPI's `/openapi.json` and produces TS types for the web app.
- **Database:** MongoDB (already deployed externally; we connect via env var). Local dev uses MongoDB + Redis via Docker Compose.

### Deployment targets (informational only — no deploy config in this task)

- Frontend → static hosting (Cloudflare Pages or similar)
- Orchestrator → long-running container (Fly.io)
- Bridge → bundled into a Sprite template (handled later)
- MongoDB → existing deployment
- Sprites → hosted by Fly

---

## Why these choices (so you don't second-guess them)

- **All-Python backend** because the Agent SDK has reached parity between Python and TypeScript, and keeping a single language across orchestrator + bridge eliminates a whole class of cross-language coupling. The bridge talks to the orchestrator over WebSocket using shared Pydantic models — one source of truth.
- **uv over Poetry** because it's faster, has better workspace support, and is the modern default in 2026.
- **FastAPI over Flask/Django** because it's async-native, Pydantic-first, and auto-generates OpenAPI which gives us the type bridge to the frontend.
- **Beanie over raw Motor** because Pydantic models as DB schemas mirror the Typegoose/Mongoose pattern and give us types end-to-end on the Python side.
- **githubkit over PyGithub** because it's async, generated from GitHub's OpenAPI, and stays current. PyGithub is sync-only and lags behind GitHub features.
- **Vite + React (no Next.js)** because the product lives behind a login wall — SSR/RSC offer nothing here. Vite is faster in dev and produces static assets you can host anywhere.
- **TanStack Router over React Router** for typed file-based routing — better DX for the URL shape this product has.
- **openapi-fetch over hand-written fetch** to recover most of the type-safety we'd have had with Hono RPC. Codegen step is automated.
- **ruff for everything Python** because one tool replacing black + isort + flake8 + pydocstyle is genuinely simpler.
- **Pyright over mypy** because Pyright is faster, the newer Python codebases prefer it, and it has better inference.

---

## What to scaffold

Set up exactly the structure below. Create directories, create the listed config files, create **placeholder entry points only** for each app and package. Placeholder means: the file exists, has correct imports, exports a stub or stub function, and would compile/run if everything were wired up — but contains no real logic.

### Top-level layout

```
.
├── apps/
│   ├── web/                                  # TypeScript (Vite + React)
│   ├── orchestrator/                         # Python (FastAPI)
│   └── bridge/                               # Python (runs in Sprites later)
├── packages/                                 # JS-side shared code
│   ├── api-types/                            # generated TS types from OpenAPI
│   └── tsconfig/                             # shared TS configs
├── python_packages/                          # Python-side shared code
│   ├── shared_models/                        # Pydantic models used by both apps
│   ├── db/                                   # Beanie models + connection
│   ├── sandbox_provider/                     # Sprites abstraction
│   ├── github_integration/                   # githubkit + GitHub App helpers
│   ├── repo_introspection/                   # detect language/framework
│   └── agent_config/                         # system prompts, tool allowlists
├── docker-compose.yml
├── turbo.json
├── pnpm-workspace.yaml
├── package.json                              # root JS dev tooling
├── tsconfig.json                             # root TS config
├── pyproject.toml                            # ROOT Python workspace declaration
├── .python-version                           # 3.12
├── .nvmrc                                    # 20 LTS
├── .gitignore
├── .env.example
├── .npmrc
├── .prettierrc
├── .eslintrc.cjs
├── .ruff.toml
├── pytest.ini
├── README.md
└── CLAUDE.md                                 # for future Claude Code sessions on this repo
```

### Root files — what they contain

**Root `pyproject.toml`** — declares the uv workspace. Members are `apps/orchestrator`, `apps/bridge`, and `python_packages/*`. Include workspace sources so members can import each other in editable mode:

```toml
[project]
name = "octo-canvas"
version = "0.1.0"
description = "Monorepo root"
requires-python = ">=3.12"

[tool.uv.workspace]
members = ["apps/orchestrator", "apps/bridge", "python_packages/*"]

[tool.uv.sources]
shared_models = { workspace = true }
db = { workspace = true }
sandbox_provider = { workspace = true }
github_integration = { workspace = true }
repo_introspection = { workspace = true }
agent_config = { workspace = true }
```

**Root `package.json`** — private, declares pnpm workspaces, holds dev tooling (turbo, prettier, typescript). Scripts: `dev`, `build`, `test`, `lint`, `typecheck`, `format`, all delegating to Turborepo.

**`pnpm-workspace.yaml`** — Turbo discovers tasks via `package.json` files, so all apps and JS packages need to be pnpm workspace members. The Python apps (orchestrator, bridge) have `package.json` files containing only Turbo-glue scripts that delegate to uv.

```yaml
packages:
  - "apps/*"
  - "packages/*"
```

The Python packages under `python_packages/` also need `package.json` files for Turbo, but they should NOT be pnpm workspace members (they have no JS dependencies). Add them via a separate Turbo configuration mechanism: include them as a glob in `turbo.json`'s root if needed, or simply add `python_packages/*` to `pnpm-workspace.yaml` as well — the empty package.json files will install nothing but Turbo will still see them. **Use this approach: include `python_packages/*` in pnpm-workspace.yaml for Turbo discovery, even though the packages have no JS deps.**

Final `pnpm-workspace.yaml`:

```yaml
packages:
  - "apps/*"
  - "packages/*"
  - "python_packages/*"
```

**`turbo.json`** — pipeline config covering both ecosystems:

```jsonc
{
  "$schema": "https://turbo.build/schema.json",
  "tasks": {
    "build": {
      "dependsOn": ["^build"],
      "outputs": ["dist/**", "build/**"]
    },
    "dev": {
      "cache": false,
      "persistent": true
    },
    "test": {
      "dependsOn": ["^build"],
      "outputs": []
    },
    "typecheck": {
      "dependsOn": ["^build"],
      "outputs": []
    },
    "lint": {
      "outputs": []
    },
    "format": {
      "cache": false,
      "outputs": []
    },
    "gen:api-types": {
      "outputs": ["packages/api-types/generated/**"]
    }
  }
}
```

**`tsconfig.json` (root)** — references the TS workspaces (`apps/web`, `packages/api-types`, `packages/tsconfig`). Composite: true. Do not reference Python packages here.

**`.npmrc`** — pnpm settings: `strict-peer-dependencies=true`, `auto-install-peers=true`, `link-workspace-packages=true`.

**`.python-version`** — `3.12` (literal one-line file).

**`.nvmrc`** — `20` (Node 20 LTS, for tools that still want a Node version).

**`.gitignore`** — comprehensive: `.env`, `node_modules`, `dist`, `build`, `.turbo`, `.vite`, `coverage`, `*.tsbuildinfo`, `__pycache__`, `*.pyc`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `.venv`, `*.egg-info`, `uv.lock` (NO — actually, commit `uv.lock`; just gitignore `.venv`).

Specifically: **commit `uv.lock` and `pnpm-lock.yaml`. Do NOT gitignore them.** Gitignore: `.env`, `node_modules/`, `dist/`, `build/`, `.turbo/`, `.vite/`, `coverage/`, `*.tsbuildinfo`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.venv/`, `*.egg-info/`, `packages/api-types/generated/schema.d.ts` (regenerated, not committed).

**`.env.example`** — placeholder values for all env vars the project will use. Populate with all the env vars listed below in commented form (no values needed for this scaffolding task, just declared so the next slice knows what to fill):

```
# Mongo (orchestrator + bridge)
MONGODB_URI=mongodb://localhost:27017/octo_canvas

# Redis (orchestrator)
REDIS_URL=redis://localhost:6379

# Sessions (orchestrator)
AUTH_SECRET=changeme-generate-with-openssl-rand-base64-32

# GitHub OAuth (orchestrator) — slice 1 will use these
GITHUB_OAUTH_CLIENT_ID=
GITHUB_OAUTH_CLIENT_SECRET=

# GitHub App (orchestrator + bridge) — used in later slices
GITHUB_APP_ID=
GITHUB_APP_PRIVATE_KEY=
GITHUB_APP_WEBHOOK_SECRET=

# Sprites (orchestrator)
SPRITES_API_KEY=

# Anthropic (bridge)
ANTHROPIC_API_KEY=

# Object storage (orchestrator) — for agent run event logs
S3_ENDPOINT=
S3_BUCKET=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=

# Service URLs
ORCHESTRATOR_PORT=3001
WEB_BASE_URL=http://localhost:5173
ORCHESTRATOR_BASE_URL=http://localhost:3001
VITE_ORCHESTRATOR_BASE_URL=http://localhost:3001
```

**`.prettierrc`** — 2-space indent, single quotes, trailing commas, 100-char line width.

**`.eslintrc.cjs`** (or flat `eslint.config.js`) — TypeScript rules + React rules for `apps/web`, `no-explicit-any` as warning, `prefer-const` as error.

**`.ruff.toml`** — ruff config. Line length 100, target Python 3.12, enable rule sets: `E` (pycodestyle), `F` (pyflakes), `I` (isort), `N` (pep8-naming), `UP` (pyupgrade), `B` (bugbear), `A` (builtins), `RUF` (ruff-specific). Configure ruff format alongside.

**`pytest.ini`** — minimal: testpaths point at app and package test dirs, asyncio_mode = "auto".

**`docker-compose.yml`** — services: `mongo` (port 27017, persistent volume), `redis` (port 6379). Local dev only.

**`README.md`** — short. Project name, one-paragraph description, prerequisites (Python 3.12, Node 20, pnpm 9, uv, Docker), setup steps:

```
1. Install Node 20+, pnpm 9+, Python 3.12+, uv, Docker.
2. cp .env.example .env  (no need to fill values for this scaffolding task)
3. docker compose up -d
4. pnpm install
5. uv sync
6. pnpm dev
```

Document that `pnpm dev` runs all three apps concurrently via Turbo: web on 5173, orchestrator on 3001, bridge in watch mode.

**`CLAUDE.md`** — instructions for future Claude Code sessions in this repo. Key contents:

- The backend is Python (FastAPI + Beanie); the frontend is TypeScript (Vite + React). Do not introduce Hono, Express, tRPC, Drizzle, or Bun.
- Python uses `uv` exclusively. Run code via `uv run <command>`. Never use `pip install` directly.
- TypeScript uses `pnpm` exclusively. Never use `npm` or `yarn`.
- Both ecosystems are orchestrated by Turborepo. Use `pnpm <task>` from the root for cross-ecosystem commands.
- The frontend talks to the orchestrator via HTTP (typed via `openapi-fetch` against generated types from FastAPI's OpenAPI schema) and via WebSocket (typed via Pydantic-derived TS types).
- Pydantic models in `python_packages/shared_models/` are the source of truth for both the FastAPI request/response schemas and the WebSocket message schemas.
- Strict typing everywhere: TypeScript `strict: true`, Pyright in strict mode, no untyped Python functions.
- Run `pnpm typecheck && pnpm lint` before considering work done.

### Shared TypeScript configs (`packages/tsconfig/`)

Three files that other tsconfigs extend:

- `base.json` — common compiler options: `strict`, `noUncheckedIndexedAccess`, `esModuleInterop`, `skipLibCheck`, `moduleResolution: "Bundler"`, `target: "ES2022"`, `module: "ESNext"`, `verbatimModuleSyntax: true`, `isolatedModules: true`.
- `library.json` — extends base, for `packages/*` if any are libraries. Adds `composite: true`, `declaration: true`, `outDir: "dist"`.
- `react-app.json` — extends base, for `apps/web`. Adds `"jsx": "react-jsx"`, `"lib": ["DOM", "DOM.Iterable", "ES2022"]`.

Plus a `package.json` declaring this as a workspace package so others can extend its files via `"extends": "@octo-canvas/tsconfig/react-app.json"`.

### Apps

For each app, scaffold the structure and configs but **no real logic**.

#### `apps/web` (Vite SPA, TypeScript)

Files to create:
- `package.json` — depends on: `react`, `react-dom`, `@tanstack/react-router`, `@tanstack/react-query`, `@tanstack/router-plugin`, `@tanstack/router-devtools`, `openapi-fetch`, `tailwindcss`, `clsx`, `tailwind-merge`, `class-variance-authority`. Workspace deps: `@octo-canvas/api-types`. Dev deps: `vite`, `@vitejs/plugin-react`, `typescript`, `@types/react`, `@types/react-dom`, `autoprefixer`, `postcss`, `vitest`. Scripts: `dev` (`vite`), `build` (`vite build`), `preview`, `typecheck` (`tsc --noEmit`), `lint` (`eslint .`), `test` (`vitest`).
- `tsconfig.json` extending `react-app.json`.
- `vite.config.ts` with the React plugin and TanStack Router plugin configured.
- `tailwind.config.ts` with content globs covering `src/**/*.{ts,tsx}`.
- `postcss.config.js` with `tailwindcss` and `autoprefixer`.
- `components.json` (shadcn/ui config — initialized for future use, no components yet).
- `index.html` with `<div id="root">` and the Vite entry script tag.
- `src/main.tsx` — placeholder: imports React, mounts `<App />` to `#root`. App renders `<div className="p-8">Web app placeholder</div>`.
- `src/styles/globals.css` — Tailwind directives (`@tailwind base; @tailwind components; @tailwind utilities;`).
- `src/routes/__root.tsx` — minimal TanStack Router root route exporting `<Outlet />`.
- `src/routes/index.tsx` — minimal home route returning `<div>Home</div>`.
- Empty placeholder folders (with `.gitkeep`): `src/components/`, `src/hooks/`, `src/lib/`.

Do **not** scaffold the API client, the WebSocket client, auth integration, or any real UI. Those come in slice 1 and onwards.

#### `apps/orchestrator` (FastAPI, Python)

Files to create:

- `pyproject.toml`:
  ```toml
  [project]
  name = "orchestrator"
  version = "0.1.0"
  requires-python = ">=3.12"
  dependencies = [
      "fastapi[standard]>=0.115",
      "uvicorn[standard]>=0.30",
      "beanie>=1.27",
      "authlib>=1.3",
      "httpx>=0.27",
      "pydantic-settings>=2.6",
      "structlog>=24.4",
      "redis>=5.0",
      "githubkit>=0.11",
      "shared_models",
      "db",
      "sandbox_provider",
      "github_integration",
      "agent_config",
  ]

  [project.optional-dependencies]
  dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "pyright>=1.1", "ruff>=0.7"]

  [tool.uv.sources]
  shared_models = { workspace = true }
  db = { workspace = true }
  sandbox_provider = { workspace = true }
  github_integration = { workspace = true }
  agent_config = { workspace = true }

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/orchestrator"]
  ```
- `package.json` (Turbo glue only):
  ```json
  {
    "name": "@octo-canvas/orchestrator",
    "private": true,
    "scripts": {
      "dev": "uv run uvicorn orchestrator.main:app --reload --host 0.0.0.0 --port 3001",
      "build": "uv build",
      "start": "uv run uvicorn orchestrator.main:app --host 0.0.0.0 --port 3001",
      "test": "uv run pytest",
      "typecheck": "uv run pyright src/",
      "lint": "uv run ruff check src/ && uv run ruff format --check src/",
      "format": "uv run ruff format src/"
    }
  }
  ```
- `Dockerfile` using `python:3.12-slim` base, installs uv, copies workspace, runs `uv sync`, runs the orchestrator. Single-stage is fine for now.
- `src/orchestrator/__init__.py` — empty.
- `src/orchestrator/main.py` — placeholder entry. Loads env via `pydantic-settings`, creates the FastAPI app from `app.py`. This is the module uvicorn imports: `from orchestrator.app import app`.
- `src/orchestrator/app.py` — creates `app = FastAPI(title="octo-canvas orchestrator")`, mounts a single `GET /health` route returning `{"status": "ok"}`. CORS middleware configured for `WEB_BASE_URL`. No other routes.
- `src/orchestrator/lib/__init__.py` — empty.
- `src/orchestrator/lib/env.py` — `pydantic-settings` `BaseSettings` class with the env vars the orchestrator needs for *this scaffolding task only* (port, web base URL). Do not include OAuth, Mongo, Redis, or other slice-1+ vars yet.
- `src/orchestrator/lib/logger.py` — structlog setup, JSON in production, pretty in dev.
- Empty placeholder folders with `__init__.py` files: `src/orchestrator/routes/`, `src/orchestrator/ws/`, `src/orchestrator/services/`, `src/orchestrator/middleware/`, `src/orchestrator/jobs/`.
- `tests/__init__.py` and a single `tests/test_health.py` that uses FastAPI's TestClient to verify `GET /health` returns 200 with `{"status": "ok"}`.
- `pyrightconfig.json` — strict mode, Python 3.12, src layout.

Do **not** scaffold actual routes (beyond `/health`), the WebSocket server, Mongo connection, GitHub integration, or sandbox manager. Those come later.

#### `apps/bridge` (Python, runs in Sprites later)

Files to create:

- `pyproject.toml`:
  ```toml
  [project]
  name = "bridge"
  version = "0.1.0"
  requires-python = ">=3.12"
  dependencies = [
      "claude-agent-sdk>=0.1.48",
      "websockets>=13.0",
      "GitPython>=3.1",
      "structlog>=24.4",
      "pydantic-settings>=2.6",
      "githubkit>=0.11",
      "httpx>=0.27",
      "shared_models",
      "agent_config",
      "repo_introspection",
      "github_integration",
  ]

  [project.optional-dependencies]
  dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "pyright>=1.1", "ruff>=0.7"]

  [tool.uv.sources]
  shared_models = { workspace = true }
  agent_config = { workspace = true }
  repo_introspection = { workspace = true }
  github_integration = { workspace = true }

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/bridge"]
  ```
- `package.json` (Turbo glue):
  ```json
  {
    "name": "@octo-canvas/bridge",
    "private": true,
    "scripts": {
      "dev": "uv run python -m bridge",
      "build": "uv build",
      "test": "uv run pytest",
      "typecheck": "uv run pyright src/",
      "lint": "uv run ruff check src/ && uv run ruff format --check src/",
      "format": "uv run ruff format src/"
    }
  }
  ```
- `Dockerfile` using `python:3.12-slim` base, installs uv, copies workspace, runs `uv sync`, runs `python -m bridge`. This image gets baked into the Sprite template later — for now it just needs to build cleanly.
- `src/bridge/__init__.py` — empty.
- `src/bridge/__main__.py` — placeholder entry. Logs "bridge process started" via structlog and exits cleanly. No WebSocket connection, no Agent SDK invocation yet.
- `src/bridge/lib/__init__.py` — empty.
- `src/bridge/lib/env.py` — `pydantic-settings` placeholder with empty Settings class.
- `src/bridge/lib/logger.py` — structlog, stdout-only.
- Empty placeholder folders with `__init__.py` files: `src/bridge/lifecycle/`, `src/bridge/agent/`, `src/bridge/agent/tools/`, `src/bridge/git/`.
- `tests/__init__.py` and a single trivial `tests/test_smoke.py` that just imports `bridge` and asserts True.
- `pyrightconfig.json` matching orchestrator's.

Do **not** scaffold Agent SDK invocation, git operations, or WebSocket client. Those come later.

### TypeScript packages

#### `packages/api-types`
Generated TS types from FastAPI's OpenAPI schema.

- `package.json` — depends on: `openapi-fetch`. Dev deps: `openapi-typescript`, `typescript`. Scripts: `gen:api-types` (runs `openapi-typescript http://localhost:3001/openapi.json -o generated/schema.d.ts`), `build` (`tsc --build`), `typecheck` (`tsc --noEmit`).
- `tsconfig.json` extending `library.json`.
- `src/index.ts` — re-exports the generated types:
  ```ts
  export type { paths, components, operations } from "../generated/schema";
  ```
- `generated/schema.d.ts` — placeholder content so the package builds before the orchestrator runs:
  ```ts
  export type paths = Record<string, never>;
  export type components = Record<string, never>;
  export type operations = Record<string, never>;
  ```
  This file gets overwritten when `pnpm gen:api-types` runs against a live orchestrator.
- `generated/.gitkeep` is not needed since the file above exists.

The `gen:api-types` script will be run manually for now. Do **not** wire up automatic regeneration in this task — that's a slice-1+ concern.

#### `packages/tsconfig`
Holds shared TS configs as described above.

### Python packages

For each Python package: `pyproject.toml`, `src/<pkg_name>/__init__.py` with a placeholder, no real logic. Each also needs a `package.json` Turbo glue file.

#### `python_packages/shared_models`

Pydantic models that will be imported by both the orchestrator and the bridge.

- `pyproject.toml` declares package `shared_models`, depends on `pydantic>=2.9`. Use hatchling build backend, package the `src/shared_models/` directory.
- `package.json` (Turbo glue):
  ```json
  {
    "name": "@octo-canvas/shared-models",
    "private": true,
    "scripts": {
      "test": "uv run pytest",
      "typecheck": "uv run pyright src/",
      "lint": "uv run ruff check src/ && uv run ruff format --check src/",
      "format": "uv run ruff format src/"
    }
  }
  ```
- `src/shared_models/__init__.py` — placeholder export only.
- `src/shared_models/wire_protocol/__init__.py` — empty placeholder; no actual schemas yet.

#### `python_packages/db`

Beanie models and Mongo connection helpers.

- Depends on `beanie>=1.27`, `pydantic>=2.9`, `motor>=3.6`, `shared_models`.
- `package.json` (Turbo glue) — same shape as above, name `@octo-canvas/db`.
- `src/db/__init__.py` — placeholder.
- `src/db/connect.py` — placeholder function:
  ```python
  async def connect(uri: str) -> None:
      """TODO: implement Mongo connection in slice 1."""
      raise NotImplementedError("connect() not implemented yet")
  ```
- Empty `src/db/models/__init__.py`. No models yet.

#### `python_packages/sandbox_provider`

Sprites abstraction.

- Depends on `pydantic>=2.9`. **Do not add the Sprites SDK dependency in this task** — leave a comment in the dependencies list.
- `package.json` Turbo glue, name `@octo-canvas/sandbox-provider`.
- `src/sandbox_provider/__init__.py` — placeholder.
- `src/sandbox_provider/interface.py` — defines a Protocol class as the interface scaffold:
  ```python
  from typing import Protocol

  class SandboxProvider(Protocol):
      """Sandbox provider interface. Methods will be added in a later slice."""
      # TODO: define create, resume, hibernate, destroy, exec methods in the sandbox slice.
      ...
  ```

#### `python_packages/github_integration`

githubkit + GitHub App helpers.

- Depends on `githubkit>=0.11`, `pydantic>=2.9`.
- `package.json` Turbo glue, name `@octo-canvas/github-integration`.
- `src/github_integration/__init__.py` — placeholder.

#### `python_packages/repo_introspection`

Detect language/framework from a cloned repo.

- Depends on `pydantic>=2.9`.
- `package.json` Turbo glue, name `@octo-canvas/repo-introspection`.
- `src/repo_introspection/__init__.py` — placeholder.

#### `python_packages/agent_config`

System prompts and tool allowlists for agents.

- Depends on `pydantic>=2.9`.
- `package.json` Turbo glue, name `@octo-canvas/agent-config`.
- `src/agent_config/__init__.py` — placeholder.
- Empty `src/agent_config/dev_agent/__init__.py`. No prompts yet.

### Naming convention

- TypeScript package names in `package.json`: `@octo-canvas/<kebab-name>` (e.g., `@octo-canvas/web`, `@octo-canvas/api-types`).
- Python package names in `pyproject.toml` and import statements: snake_case (e.g., `shared_models`, `github_integration`, `sandbox_provider`).
- Each Python package's `package.json` (Turbo glue) uses the kebab-case TS-style name `@octo-canvas/<kebab-name>`. The Python module name and the npm name can differ — that's fine because the npm name is only for Turbo, not for imports.

The user can rename the project later via find-and-replace.

---

## Acceptance criteria — what "done" looks like

After this task, all of the following must be true. Each criterion must be verified with the actual command output captured in your final summary.

1. `pnpm install` from the root completes successfully.
2. `uv sync` from the root completes successfully and installs all Python workspace members in editable mode.
3. `pnpm typecheck` passes across all workspaces (TS via tsc, Python via pyright).
4. `pnpm lint` passes across all workspaces (ESLint for TS, ruff for Python).
5. `pnpm build` builds every package and app without errors.
6. `pnpm test` runs all tests across both ecosystems via Turbo. The trivial tests pass.
7. `docker compose up -d` brings up Mongo and Redis on the expected ports.
8. **`pnpm dev` runs all three apps concurrently via Turbo:**
   - The web app is reachable at `http://localhost:5173` and renders the placeholder.
   - The orchestrator is reachable at `http://localhost:3001/health` and returns `{"status":"ok"}`.
   - The bridge logs its startup message to the console (and either exits or stays alive — both acceptable since there's no real loop yet).
9. `curl http://localhost:3001/openapi.json` returns a valid OpenAPI schema (FastAPI generates this automatically).
10. The directory layout matches the structure above exactly. No extra files, no missing files.
11. Pyright runs in strict mode with zero errors across all Python source.
12. TypeScript compiles in strict mode with zero errors across all TS source.

---

## Hard rules — do not violate

- **Do not write business logic.** No real route handlers (other than `/health`), no DB models, no React components beyond the placeholder, no WebSocket handlers, no GitHub integration code, no Agent SDK invocation, no Sprites SDK calls.
- **Do not mix package managers.** Python is uv only. TypeScript is pnpm only. No pip, no npm, no yarn.
- **Do not invent dependencies.** Use only the packages listed above. If you think something else is needed, leave a `# TODO` or `// TODO` comment and surface it in your summary.
- **Do not skip the workspace configuration.** Every Python package must be a uv workspace member; every TS package must be a pnpm workspace member; every package must have a Turbo-recognizable `package.json`.
- **Do not introduce Hono, Express, tRPC, Drizzle, Bun, Next.js, Prisma, Clerk, or Better Auth.** They are explicit non-choices.
- **Do not write a CI config.** No `.github/workflows/` in this task.
- **Do not deploy anything.** Dockerfiles must build cleanly but no deployment manifests, no fly.toml, nothing else.
- **Do not register a GitHub OAuth App or GitHub App.** Those happen in slice 1.

---

## When done

Write a brief summary covering:
1. Anything that didn't work first try and how you resolved it.
2. Any decision points where the brief was ambiguous and you made a judgment call (especially around uv workspace setup, Pyright config, or Turbo task wiring across languages).
3. Any TODOs left in placeholder files (so the next task knows where to look).
4. Confirm each acceptance criterion with the actual command output.
5. Specifically note: did `pnpm dev` cleanly start all three apps? Any timing/race issues between the JS and Python sides?

Do **not** start on the next task automatically. Wait for the user to review the scaffolding and approve before proceeding to slice 1 (GitHub OAuth + user persistence).