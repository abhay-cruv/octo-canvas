# Slice 1 — GitHub OAuth and user persistence

This is the **first feature slice** after scaffolding. The previous task laid down the empty monorepo with placeholder entry points and proven plumbing. This task adds the first end-to-end vertical slice: a user can sign in with GitHub, land on a dashboard, and have their identity persisted in MongoDB.

This is intentionally narrow in user-visible scope. The point is to exercise every integration boundary (frontend ↔ orchestrator ↔ DB ↔ GitHub OAuth, plus the OpenAPI codegen pipeline) on something simple enough that all the pieces can be debugged independently. Future slices stack on this foundation.

**Do not build features beyond this slice.** No repo connection, no GitHub App, no tasks, no sandboxes, no WebSocket, no Agent SDK, no real Redis usage. Just sign-in, the user collection, and a placeholder dashboard.

---

## Context from the previous task

The scaffolding task is complete. Read its summary in your conversation history before starting. Key things to know:

- All Python packages are installed editable via `uv sync --all-packages --all-extras`. Use this command, not bare `uv sync`.
- `python_packages/db/src/db/connect.py` currently has `connect()` raising `NotImplementedError`. **You will implement it in this slice.**
- TanStack Router is wired with `tsr generate` running before typecheck and build. The `.tanstack/` folder and `routeTree.gen.ts` are gitignored.
- `apps/web/src/main.tsx` currently mounts a static placeholder (`<div>Web app placeholder</div>`), not the router. **You will replace this with a real router setup in this slice.**
- `apps/orchestrator/src/orchestrator/lib/env.py` only has `ORCHESTRATOR_PORT` and `WEB_BASE_URL` so far. **You will extend it with the env vars this slice needs.**
- `.env.example` already declares the GitHub OAuth vars (`GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, `AUTH_SECRET`, `MONGODB_URI`). They're empty; this slice wires them up.
- `packages/api-types/generated/schema.d.ts` currently contains stub types. **It will be regenerated against a live orchestrator in this slice for the first time.**
- Redis is declared in docker-compose but blocked by a pre-existing local container. **This slice does not need Redis** — leave that situation alone.
- Pyright strict mode is the bar. All Python code in this slice must pass `uv run pyright src/` with zero errors.

---

## What "done" looks like

After this task, a user can:

1. Visit the web app at `http://localhost:5173`.
2. Be redirected to `/login` if not authenticated.
3. Click "Sign in with GitHub."
4. Get redirected to GitHub's OAuth consent page.
5. Authorize the app.
6. Get redirected back to the orchestrator's OAuth callback URL.
7. The orchestrator creates or updates the user record in MongoDB (keyed by GitHub user ID) and creates a session.
8. The user lands on `/dashboard`, which renders `Welcome, {githubUsername}` and a "Sign out" button.
9. Clicking "Sign out" clears the session and returns the user to `/login`.
10. Re-visiting the site while still signed in skips `/login` and goes straight to `/dashboard`.

That is the entire user-facing scope. Anything else is out of scope.

---

## Auth library — Authlib + custom session management

Use **Authlib** (`authlib`) as the OAuth client library. It handles only the OAuth dance — building authorization URLs, exchanging codes for tokens, fetching user profiles. Session management is yours: signed cookies backed by a `sessions` collection in Mongo.

**Authentication providers:** GitHub OAuth only. No email/password, no other providers, no passwordless.

**No emails sent by this system.** GitHub already verified the user's email when they signed up there. There are no email verification, password reset, or magic link flows in this slice or in v1. Do not configure any email transport, do not install any email library.

---

## GitHub OAuth setup (the user does this manually)

The user will register a GitHub OAuth App separately and provide the credentials via env vars. **Do not register the app yourself.** Document in the README what the user needs to do:

1. Go to GitHub Settings → Developer settings → OAuth Apps → New OAuth App.
2. Application name: `vibe-platform (local dev)`.
3. Homepage URL: `http://localhost:5173`.
4. Authorization callback URL: `http://localhost:3001/api/auth/github/callback`.
5. Click "Register application," copy the Client ID, generate a Client Secret, copy that.
6. Put both in `.env`: `GITHUB_OAUTH_CLIENT_ID=...` and `GITHUB_OAUTH_CLIENT_SECRET=...`.
7. Generate a session secret: `openssl rand -base64 32` and put it in `.env` as `AUTH_SECRET=...`.

The OAuth scope for this slice is **`read:user user:email`** — just enough to read the GitHub user profile and primary email at signup. Do **not** request `repo` or any GitHub App scope yet — those come in a later slice when we add repo connection.

---

## What to build

### 1. MongoDB connection — `python_packages/db/src/db/connect.py`

Replace the `NotImplementedError` placeholder with a real connection helper:

- A module-level `motor.motor_asyncio.AsyncIOMotorClient` reference (initialized to None, set on connect).
- An `async def connect(uri: str) -> None` that:
  - Creates the Motor client
  - Calls `await init_beanie(database=client[<db_name>], document_models=[...])`
  - Logs successful connection and connection errors via structlog
  - Raises on connection failure (orchestrator should fail to start)
- An `async def disconnect() -> None` for graceful shutdown.
- Extract the database name from the URI's path component (default to `vibe_platform` if absent).

The `document_models` list passed to `init_beanie` should include all Beanie `Document` classes. For this slice that's the `User` model and the `Session` model (both described next).

Export `connect` and `disconnect` from `python_packages/db/src/db/__init__.py`.

### 2. Beanie models — `python_packages/db/src/db/models/`

Add two Beanie `Document` models in this slice. Both go in `python_packages/db/src/db/models/`.

**`user.py`** — the `User` document.

```python
from datetime import datetime
from beanie import Document, Indexed
from pydantic import Field
from typing import Annotated

class User(Document):
    github_user_id: Annotated[int, Indexed(unique=True)]
    github_username: str
    github_avatar_url: str | None = None
    email: str
    display_name: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_signed_in_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "users"
```

**`session.py`** — the `Session` document. Stores server-side session state keyed by an opaque session ID (the cookie value).

```python
from datetime import datetime
from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field
from typing import Annotated

class Session(Document):
    session_id: Annotated[str, Indexed(unique=True)]  # opaque random string, lives in cookie
    user_id: PydanticObjectId  # FK to User._id
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime  # 7 days from creation
    last_used_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "sessions"
```

Sessions go in their own collection (not embedded in User) so we can revoke them, list them per user, and prune expired ones in a future job.

Export both classes from `python_packages/db/src/db/models/__init__.py` and from `python_packages/db/src/db/__init__.py`.

### 3. Pydantic API models — `python_packages/shared_models/`

Add request/response Pydantic models that FastAPI will use. These are separate from the Beanie `Document` models because they shape the API surface, not the DB.

In `python_packages/shared_models/src/shared_models/`:

**`user.py`**:

```python
from datetime import datetime
from pydantic import BaseModel

class UserResponse(BaseModel):
    id: str
    github_user_id: int
    github_username: str
    github_avatar_url: str | None
    email: str
    display_name: str | None
    created_at: datetime
    last_signed_in_at: datetime
```

Export from `python_packages/shared_models/src/shared_models/__init__.py`.

The orchestrator will convert `User` (Beanie) → `UserResponse` (Pydantic) at the API boundary.

### 4. Env config — `apps/orchestrator/src/orchestrator/lib/env.py`

Extend the existing `Settings` class to include the env vars this slice needs:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Existing
    orchestrator_port: int = Field(default=3001, alias="ORCHESTRATOR_PORT")
    web_base_url: str = Field(alias="WEB_BASE_URL")

    # New for slice 1
    mongodb_uri: str = Field(alias="MONGODB_URI")
    auth_secret: str = Field(alias="AUTH_SECRET")
    github_oauth_client_id: str = Field(alias="GITHUB_OAUTH_CLIENT_ID")
    github_oauth_client_secret: str = Field(alias="GITHUB_OAUTH_CLIENT_SECRET")
    orchestrator_base_url: str = Field(alias="ORCHESTRATOR_BASE_URL")

    @property
    def is_production(self) -> bool:
        return False  # TODO: wire to ENV var in a later slice

settings = Settings()  # type: ignore[call-arg]
```

The orchestrator must fail to start if any required env var is missing. pydantic-settings handles this automatically — just make sure the fields are required (no defaults).

### 5. App startup — `apps/orchestrator/src/orchestrator/main.py` and `app.py`

Wire DB connection into FastAPI's lifespan. In `app.py`, replace the current minimal setup with:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db import connect, disconnect
from .lib.env import settings
from .lib.logger import logger
from .routes import auth, me

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect(settings.mongodb_uri)
    logger.info("orchestrator.startup_complete")
    yield
    await disconnect()
    logger.info("orchestrator.shutdown_complete")

app = FastAPI(title="vibe-platform orchestrator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_base_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(me.router, prefix="/api", tags=["me"])

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

`main.py` continues to expose `app` for uvicorn — no other changes there.

### 6. Auth routes — `apps/orchestrator/src/orchestrator/routes/auth.py`

Implement four endpoints:

- **`GET /api/auth/github/login`** — generates a state token (for CSRF protection in the OAuth flow), stores it briefly in a cookie, redirects the user to GitHub's authorization URL.
- **`GET /api/auth/github/callback`** — handles GitHub's redirect-back. Validates state, exchanges the code for an access token via Authlib, fetches the GitHub user profile and primary email, upserts the `User` document, creates a `Session` document, sets the session cookie, redirects to `${WEB_BASE_URL}/dashboard`.
- **`POST /api/auth/logout`** — deletes the session document, clears the session cookie, returns 204.
- **`GET /api/auth/session`** — returns the current session info (or 401 if no valid session). This is what the frontend uses to check auth state on app load.

Use Authlib's `AsyncOAuth2Client` for the OAuth dance. The GitHub authorization endpoint is `https://github.com/login/oauth/authorize`, the token endpoint is `https://github.com/login/oauth/access_token`, and the user endpoint is `https://api.github.com/user`. Fetch primary email from `https://api.github.com/user/emails` (the user endpoint may return a null email if the user has it private).

**Session cookie config:**
- Name: `vibe_session`
- `httponly=True`
- `secure=False` in dev, `True` in prod (use `settings.is_production`)
- `samesite="lax"` (web and API are on different origins in dev, so cross-site behavior matters; lax is correct because the OAuth redirect is a top-level navigation)
- `max_age=7 * 24 * 60 * 60` (7 days, matching session expiry)
- `path="/"`

**Session ID generation:** use `secrets.token_urlsafe(32)`. Store the resulting string as both the cookie value and the `Session.session_id` field. Do not put the user ID, email, or anything else in the cookie — just the opaque session ID. The orchestrator looks up the session in Mongo on every request.

**State token for OAuth CSRF:** also `secrets.token_urlsafe(32)`. Store it in a short-lived cookie (`vibe_oauth_state`, expires in 10 minutes, samesite=lax) on the login redirect. Verify and clear it on the callback. Reject the callback if state doesn't match.

**On callback:**
1. Validate state token.
2. Exchange code for access token via Authlib.
3. Fetch `/user` and `/user/emails` from GitHub.
4. Upsert user by `github_user_id`. Update `github_username`, `github_avatar_url`, `email`, `display_name`, and `last_signed_in_at` on every login. Set `created_at` only if the document is new.
5. Delete any existing sessions for this user that have expired (cheap cleanup, not strictly required but a nice habit).
6. Create a new `Session` document with `expires_at = now + 7 days`.
7. Set the session cookie.
8. Redirect to `${WEB_BASE_URL}/dashboard`.

Return useful error responses if anything fails — log the actual error via structlog, return a generic 400/500 to the user. Do not leak token info or stack traces in API responses.

### 7. Auth middleware — `apps/orchestrator/src/orchestrator/middleware/auth.py`

Implement a FastAPI dependency `async def require_user(request: Request) -> User`:

- Read the `vibe_session` cookie.
- If missing, raise `HTTPException(status_code=401, detail="unauthenticated")`.
- Look up the `Session` document by `session_id`. If missing or expired (`expires_at < now`), raise 401.
- Update `last_used_at` on the session (a tiny write, but useful for active-session metrics later — cheap).
- Look up the `User` document by `Session.user_id`. If missing (shouldn't happen but defensively check), raise 401.
- Return the `User`.

Routes that need auth use this as a dependency: `user: User = Depends(require_user)`.

Also export an optional variant `async def get_user_optional(request: Request) -> User | None` that returns None instead of raising — the `/api/auth/session` endpoint uses this to return a 401 vs. 200 with user data without raising mid-handler.

### 8. The `/api/me` endpoint — `apps/orchestrator/src/orchestrator/routes/me.py`

```python
from fastapi import APIRouter, Depends
from db.models import User
from shared_models import UserResponse
from ..middleware.auth import require_user

router = APIRouter()

@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(require_user)) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        github_user_id=user.github_user_id,
        github_username=user.github_username,
        github_avatar_url=user.github_avatar_url,
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
        last_signed_in_at=user.last_signed_in_at,
    )
```

The `response_model=UserResponse` is what makes this end up in the OpenAPI schema correctly so the frontend can derive types from it.

### 9. Regenerate API types — `packages/api-types/`

After the orchestrator is running with the new endpoints, regenerate the TS types:

```bash
# In one terminal:
pnpm --filter @vibe-platform/orchestrator dev

# In another:
pnpm --filter @vibe-platform/api-types gen:api-types
```

This overwrites `packages/api-types/generated/schema.d.ts` with real types derived from the live OpenAPI schema. After regeneration, the frontend can import `paths`, `components`, and `operations` types and use them with `openapi-fetch`.

Document this two-terminal workflow in the README under a "Regenerating API types" section. (We're not automating this with a file watcher in this slice — that's a polish task for later.)

### 10. Frontend — API client — `apps/web/src/lib/api.ts`

```ts
import createClient from "openapi-fetch";
import type { paths } from "@vibe-platform/api-types";

const baseUrl = import.meta.env.VITE_ORCHESTRATOR_BASE_URL;
if (!baseUrl) {
  throw new Error("VITE_ORCHESTRATOR_BASE_URL is not set");
}

export const api = createClient<paths>({
  baseUrl,
  credentials: "include", // send/receive the session cookie cross-origin in dev
});
```

### 11. Frontend — auth queries — `apps/web/src/lib/queries.ts`

Wrap the `/api/me` call in TanStack Query option factories:

```ts
import { queryOptions } from "@tanstack/react-query";
import { api } from "./api";

export const meQueryOptions = queryOptions({
  queryKey: ["me"],
  queryFn: async () => {
    const { data, response } = await api.GET("/api/me");
    if (response.status === 401) return null;  // signed out is not an error
    if (!data) throw new Error("Failed to fetch /api/me");
    return data;
  },
  staleTime: 30_000,
  retry: false,  // 401 is the answer, don't retry
});
```

The "no session" case returns `null` rather than throwing because it's a normal app state, not an error.

### 12. Frontend — auth helpers — `apps/web/src/lib/auth.ts`

```ts
import { api } from "./api";

export function startGithubLogin(): void {
  window.location.href = `${import.meta.env.VITE_ORCHESTRATOR_BASE_URL}/api/auth/github/login`;
}

export async function logout(): Promise<void> {
  await api.POST("/api/auth/logout");
}
```

GitHub login is a redirect, not a fetch — it's a top-level navigation so cookies and CORS work the way GitHub expects. Don't try to do it via fetch.

### 13. Frontend — main + router setup — `apps/web/src/main.tsx`

Replace the current placeholder mount with a real router setup:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { routeTree } from "./routeTree.gen";
import "./styles/globals.css";

const queryClient = new QueryClient();

const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Root element not found");

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>
);
```

The router context (`{ queryClient }`) makes the QueryClient accessible to route loaders/beforeLoad — the auth guard uses this.

### 14. Frontend — routes

Create or update these routes in `apps/web/src/routes/`. TanStack Router's `tsr generate` will pick them up.

**`__root.tsx`** — root layout. Renders `<Outlet />`. No providers here (they live in main.tsx). Define the route context type:

```tsx
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";

interface RouterContext {
  queryClient: QueryClient;
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: () => <Outlet />,
});
```

**`index.tsx`** — root path `/`. Redirects to `/dashboard` if signed in, `/login` otherwise. Use `beforeLoad` to do this server-side-style:

```tsx
import { createFileRoute, redirect } from "@tanstack/react-router";
import { meQueryOptions } from "../lib/queries";

export const Route = createFileRoute("/")({
  beforeLoad: async ({ context }) => {
    const me = await context.queryClient.ensureQueryData(meQueryOptions);
    if (me) throw redirect({ to: "/dashboard" });
    throw redirect({ to: "/login" });
  },
});
```

**`login.tsx`** — public route. Not behind any guard. Renders a simple centered page with a "Sign in with GitHub" button.

```tsx
import { createFileRoute } from "@tanstack/react-router";
import { startGithubLogin } from "../lib/auth";

export const Route = createFileRoute("/login")({
  component: LoginPage,
});

function LoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="p-8 border rounded-lg space-y-4">
        <h1 className="text-2xl font-semibold">Sign in</h1>
        <button
          onClick={startGithubLogin}
          className="px-4 py-2 bg-black text-white rounded hover:bg-gray-800"
        >
          Sign in with GitHub
        </button>
      </div>
    </div>
  );
}
```

**`_authed.tsx`** — auth guard layout. Anything under `_authed/` is protected.

```tsx
import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { meQueryOptions } from "../lib/queries";

export const Route = createFileRoute("/_authed")({
  beforeLoad: async ({ context }) => {
    const me = await context.queryClient.ensureQueryData(meQueryOptions);
    if (!me) throw redirect({ to: "/login" });
  },
  component: () => <Outlet />,
});
```

**`_authed/dashboard.tsx`** — the dashboard.

```tsx
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { meQueryOptions } from "../../lib/queries";
import { logout } from "../../lib/auth";

export const Route = createFileRoute("/_authed/dashboard")({
  component: DashboardPage,
});

function DashboardPage() {
  const { data: me } = useQuery(meQueryOptions);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  if (!me) return null; // guard already ran, this satisfies TS

  async function handleSignOut() {
    await logout();
    queryClient.setQueryData(meQueryOptions.queryKey, null);
    navigate({ to: "/login" });
  }

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="p-8 border rounded-lg space-y-4 text-center">
        <h1 className="text-2xl font-semibold">Welcome, {me.github_username}</h1>
        <button
          onClick={handleSignOut}
          className="px-4 py-2 bg-gray-200 rounded hover:bg-gray-300"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
```

Styling: minimal Tailwind. A centered card on `/login`, a centered greeting on `/dashboard`. No shadcn/ui components yet — this is structural, not visual.

### 15. Tests

Add real tests alongside the existing smoke tests.

**`apps/orchestrator/tests/test_auth.py`** — at minimum, the following test cases. Use `httpx.AsyncClient` with FastAPI's `ASGITransport` (or `TestClient` if simpler) and `pytest-asyncio`. Mock out the actual GitHub API calls — don't hit GitHub in tests.

- `GET /api/auth/session` returns 401 with no cookie.
- `GET /api/auth/session` returns 200 with a valid session cookie (set up a session in the test DB first).
- `GET /api/auth/github/login` returns a 302 to GitHub with the right state cookie set.
- `GET /api/auth/github/callback?state=mismatch` returns 400.
- `POST /api/auth/logout` clears the session cookie and deletes the Session document.
- `GET /api/me` returns 401 with no session.
- `GET /api/me` returns the user's data with a valid session.

For mocking GitHub, patch the Authlib client or the httpx call inside the callback handler. Use `pytest-mock` or `unittest.mock`. **Add `pytest-mock` to the orchestrator's `[project.optional-dependencies] dev` if it isn't there.**

For the test database: use a separate database name (e.g., `vibe_platform_test`), connect/disconnect in a session-scoped fixture, drop the database at the end. Don't touch the dev database from tests.

**`apps/web/`** — no tests required for this slice. Vitest stays at 0 files with `--passWithNoTests`.

### 16. README updates

Add three new sections to the README:

**"Setting up GitHub OAuth (local dev)"** — the steps from the GitHub OAuth setup section above.

**"Running the app"** — order of operations:
```
docker compose up -d        # mongo (redis is fine if it conflicts, this slice doesn't use it)
cp .env.example .env        # if not done already
# Fill in MONGODB_URI, AUTH_SECRET, GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_SECRET
pnpm install
uv sync --all-packages --all-extras
pnpm --filter @vibe-platform/orchestrator dev   # terminal 1
pnpm --filter @vibe-platform/api-types gen:api-types  # terminal 2, run once after orchestrator is up
pnpm dev                    # terminal 3, runs everything
```

**"Regenerating API types"** — when you change a route or response model in the orchestrator, run `pnpm --filter @vibe-platform/api-types gen:api-types` against a running orchestrator. The frontend's typecheck will pick up the new types. (This is manual for now; auto-regeneration on backend changes is a future polish.)

---

## What's intentionally out of scope

Do not build any of the following in this task:

- GitHub App (the OAuth App and the GitHub App are different things — only the OAuth App for this slice).
- Repo listing, repo connection, repo model.
- Tasks, agent runs, sandboxes.
- WebSocket server or client.
- Agent SDK invocation.
- Any change to the bridge (`apps/bridge/` stays as the placeholder).
- Sprites integration.
- Email verification, password reset, magic links (no emails at all).
- Multi-factor auth.
- Account deletion / settings page.
- Real Redis usage. Redis is in docker-compose for later slices; this slice doesn't touch it.
- shadcn/ui components. Plain Tailwind only.
- A landing page or marketing copy.
- Auto-regeneration of API types on backend changes (manual for now).

If you find yourself building any of the above, stop. They are future slices.

---

## Acceptance criteria

After this task, all of the following must hold. Capture the actual command/output for each in your final summary.

1. `pnpm install` from root completes with no errors.
2. `uv sync --all-packages --all-extras` completes successfully.
3. `pnpm typecheck` passes across all workspaces (Pyright strict + tsc).
4. `pnpm lint` passes across all workspaces (ruff + ESLint).
5. `pnpm build` builds every package and app without errors.
6. `pnpm test` passes — orchestrator now has real auth tests, all green.
7. `docker compose up -d` brings up Mongo (Redis port conflict is acceptable, not a regression).
8. With `.env` populated and the orchestrator running:
   - `curl http://localhost:3001/health` returns `{"status":"ok"}`.
   - `curl http://localhost:3001/openapi.json` returns a schema that includes `/api/auth/github/login`, `/api/auth/github/callback`, `/api/auth/logout`, `/api/auth/session`, `/api/me`.
9. After running `pnpm --filter @vibe-platform/api-types gen:api-types` against the live orchestrator, `packages/api-types/generated/schema.d.ts` contains real `paths` types (not the stub from scaffolding).
10. With all three apps running (`pnpm dev`):
    - Visiting `http://localhost:5173` while signed out redirects to `/login`.
    - Clicking "Sign in with GitHub" navigates to GitHub's OAuth consent page with the requested scopes (`read:user user:email`).
    - After authorizing, the user lands on `/dashboard` and sees their GitHub username.
    - A new document appears in the `users` collection with the GitHub identity fields populated.
    - A document appears in the `sessions` collection.
    - Refreshing `/dashboard` keeps the user signed in (session cookie works).
    - Clicking "Sign out" clears the session and returns the user to `/login`. The `sessions` document is deleted.
    - Visiting `/dashboard` directly while signed out redirects to `/login`.
11. `curl --cookie "vibe_session=<valid_id>" http://localhost:3001/api/me` returns the user's data. With no cookie, it returns 401.
12. Pyright strict still passes with zero errors across all Python source.
13. TypeScript strict still passes with zero errors across all TS source.

---

## Hard rules — do not violate

- **Do not implement email/password sign-up or any other auth provider.** GitHub OAuth only.
- **Do not configure any email transport.** No SMTP, no Resend, no email library installed.
- **Do not introduce a different auth library.** No Clerk, no Better Auth, no FastAPI Users. Authlib only.
- **Do not register a GitHub App.** Only the OAuth App is in scope. The user creates it manually via the README instructions.
- **Do not duplicate types.** The `User` Beanie model and the `UserResponse` Pydantic model are different on purpose: one is the DB shape, the other is the API shape. Don't merge them.
- **Do not write business logic that doesn't belong in this slice.** No repo, task, or sandbox code, even as placeholders.
- **Do not skip the `require_user` dependency** on protected routes. Even though `/api/me` is the only one right now, the pattern needs to be established correctly.
- **Do not put user data in cookies.** Cookies hold only the opaque session ID. Everything else is looked up server-side.
- **Do not relax Pyright strict mode.** If Pyright complains about a third-party library's missing types, configure that specifically (e.g., `reportMissingTypeStubs = false` for that library) — don't disable strict globally.

---

## When done

Write a brief summary covering:
1. The Authlib integration approach you took, especially around state token handling and the user/email fetch flow.
2. Anything in the OAuth flow that was non-obvious or required reading source code or docs.
3. Any decision points where this brief was ambiguous and you made a judgment call.
4. Confirm each acceptance criterion with the actual command output or a description of the verified behavior.
5. Whether the OpenAPI codegen pipeline worked smoothly — did `gen:api-types` produce a sensible schema on the first try?
6. Flag any TODOs or known issues for slice 2 to address.

Do not start the next slice automatically. Wait for the user to review and approve before continuing.