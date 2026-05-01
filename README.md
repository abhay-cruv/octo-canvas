# octo-canvas

A bilingual monorepo with a Python backend (FastAPI orchestrator + bridge) and a TypeScript frontend (Vite + React). Cross-language tasks are orchestrated by Turborepo.

## Prerequisites

- Node.js 20+
- pnpm 9+
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (for local Mongo)

## Setting up GitHub OAuth (local dev)

You register **one** GitHub OAuth App. It's used for both sign-in (slice 1) and repo access (slice 2). There is **no separate GitHub App** and no webhook tunnel.

1. Go to GitHub Settings → Developer settings → OAuth Apps → **New OAuth App**.
2. **Application name:** `octo-canvas (local dev)`.
3. **Homepage URL:** `http://localhost:5173`.
4. **Authorization callback URL:** `http://localhost:3001/api/auth/github/callback`.
5. Click **Register application**, copy the **Client ID**, generate a **Client Secret**, copy that.
6. Put both in `.env`:

   ```dotenv
   GITHUB_OAUTH_CLIENT_ID=<paste>
   GITHUB_OAUTH_CLIENT_SECRET=<paste>
   ```

7. Generate a session secret and put it in `.env`:

   ```bash
   AUTH_SECRET=$(openssl rand -base64 32)
   ```

The OAuth scope requested is `read:user user:email repo`. The `repo` scope lets the orchestrator clone, branch, and push to repos you grant — using your OAuth token via `githubkit.TokenAuthStrategy`. Tradeoffs: commits/PRs from the agent are attributed to you (no bot identity), and access is all-or-nothing at consent time. See [docs/Plan.md §12](docs/Plan.md) for why we chose this over a separate GitHub App.

## Connecting repositories

After signing in:

1. Dashboard → **Connect repositories** → `/repos` shows your already-connected repos (initially empty).
2. Click **Browse repositories** → `/repos/connect` lists every repo your OAuth token can read.
3. Click **Connect** on any → the repo lands with `clone_status: pending` (slice 4 will provision a sandbox and clone it).
4. Click **Disconnect** to remove a connection.

### When your token expires or is revoked

If you revoke the OAuth grant on GitHub (Settings → Applications → Authorized OAuth Apps → Revoke), the next repo call returns `403 github_reauth_required`. The dashboard shows a **Reconnect GitHub** banner; clicking it re-runs the OAuth flow with the same scopes. Already-connected repo rows are preserved across reconnects.

> Org SSO note: personal OAuth tokens are often blocked from accessing org repos until you click "Authorize" per-org on GitHub. If you don't see an org's repos in the list, visit GitHub → Settings → Applications → your OAuth app → "Organization access" and authorize the org.

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

Visit http://localhost:5173 → you'll be redirected to `/login`. Click **Sign in with GitHub**, authorize `read:user user:email repo`, and you'll land on `/dashboard`.

## Regenerating API types

The frontend's HTTP client is typed against types generated from the orchestrator's live `/openapi.json` schema. When you change a route or response model in the orchestrator, regenerate:

```bash
# Terminal 1 — keep the orchestrator running
pnpm --filter @octo-canvas/orchestrator dev

# Terminal 2 — regenerate types
pnpm --filter @octo-canvas/api-types gen:api-types
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
