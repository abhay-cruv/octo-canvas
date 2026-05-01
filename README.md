# vibe-platform

A bilingual monorepo with a Python backend (FastAPI orchestrator + bridge) and a TypeScript frontend (Vite + React). Cross-language tasks are orchestrated by Turborepo.

## Prerequisites

- Node.js 20+
- pnpm 9+
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (for local Mongo)

## Setting up GitHub OAuth (local dev)

Slice 1 ships GitHub OAuth sign-in. You need to register an OAuth App once:

1. Go to GitHub Settings → Developer settings → OAuth Apps → **New OAuth App**.
2. **Application name:** `vibe-platform (local dev)`.
3. **Homepage URL:** `http://localhost:5173`.
4. **Authorization callback URL:** `http://localhost:3001/api/auth/github/callback`.
5. Click **Register application**, copy the **Client ID**, generate a **Client Secret**, copy that.
6. Put both in `.env`:

   ```
   GITHUB_OAUTH_CLIENT_ID=<paste>
   GITHUB_OAUTH_CLIENT_SECRET=<paste>
   ```

7. Generate a session secret and put it in `.env`:

   ```
   AUTH_SECRET=$(openssl rand -base64 32)
   ```

The OAuth scope requested is `read:user user:email`. Do not register a GitHub App — that's a different concept used in a later slice.

## Running the app

```bash
# 1. Bring up Mongo (Redis is in compose for later slices; OK if its port conflicts)
docker compose up -d

# 2. Copy env template and fill in the values
cp .env.example .env
#    MONGODB_URI, AUTH_SECRET, GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_SECRET
#    plus WEB_BASE_URL, ORCHESTRATOR_BASE_URL, VITE_ORCHESTRATOR_BASE_URL

# 3. Install deps
pnpm install
uv sync --all-packages --all-extras

# 4. Start everything via Turbo
pnpm dev
```

`pnpm dev` runs:

- web on http://localhost:5173
- orchestrator on http://localhost:3001 (try `/health`, `/openapi.json`, `/api/auth/github/login`)
- bridge (placeholder — logs `bridge.started` and exits)

Visit http://localhost:5173 → you'll be redirected to `/login`. Click **Sign in with GitHub**, authorize the app, and you'll land on `/dashboard`.

## Regenerating API types

The frontend's HTTP client is typed against types generated from the orchestrator's live `/openapi.json` schema. When you change a route or response model in the orchestrator, regenerate:

```bash
# Terminal 1 — keep the orchestrator running
pnpm --filter @vibe-platform/orchestrator dev

# Terminal 2 — regenerate types
pnpm --filter @vibe-platform/api-types gen:api-types
```

The generator overwrites `packages/api-types/generated/schema.d.ts`. The frontend picks up the new types on its next typecheck/build. (Auto-regeneration on backend changes is a future polish.)

## Common commands

| Command              | What it does                                                   |
| -------------------- | -------------------------------------------------------------- |
| `pnpm dev`           | Start every app via Turbo                                      |
| `pnpm build`         | Build every package and app                                    |
| `pnpm test`          | Run JS (Vitest) and Python (pytest) test suites                |
| `pnpm lint`          | ESLint for TS, ruff for Python                                 |
| `pnpm typecheck`     | tsc for TS, pyright for Python                                 |
| `pnpm format`        | prettier for TS, ruff format for Python                        |
| `pnpm gen:api-types` | Regenerate `packages/api-types` from FastAPI's `/openapi.json` |

## Layout

```
apps/web              TypeScript SPA (Vite + React + TanStack)
apps/orchestrator     FastAPI service
apps/bridge           Python process that runs inside Sprites
packages/             Shared TS code (tsconfig, generated API types)
python_packages/      Shared Python code (Pydantic models, DB helpers, etc.)
```

See `CLAUDE.md` for guidance on extending the project.
