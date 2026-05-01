# Testing the platform

There are three layers you can test, from cheapest to most realistic. Run Layer 1 + Layer 2 every time you make changes; run Layer 3 once after you set up GitHub OAuth.

---

## Layer 1 — Automated checks

These run against a real MongoDB but do **not** need GitHub credentials. Fastest signal that the code is correct.

```bash
docker compose up -d        # Mongo must be running
pnpm typecheck              # → 11 successful, 11 total
pnpm lint                   # → 10 successful, 10 total
pnpm build                  # → 4 successful, 4 total
pnpm test                   # → 11 successful, 11 total (includes 9 orchestrator auth tests)
```

What each one verifies:

| Command | Verifies |
| --- | --- |
| `pnpm typecheck` | Pyright strict against every Python package, `tsc --noEmit` against every TS package. Catches type drift between Pydantic models, generated TS types, and frontend usage. |
| `pnpm lint` | ruff (Python) + ESLint (TS). Style + import order + bug-prone patterns. |
| `pnpm build` | Each package can produce its release artifact: orchestrator/bridge wheels via `uv build`, web bundle via Vite. |
| `pnpm test` | pytest for the orchestrator (real Mongo, mocked GitHub) and the python_packages, vitest for the web app. Auth flow, session lifecycle, and HTTP boundary are all exercised here. |

If all four pass, the contracts are solid. If only `pnpm test` fails, the runtime behaviour is the regression.

### Running just one slice

```bash
pnpm --filter @vibe-platform/orchestrator test         # Python auth tests only
pnpm --filter @vibe-platform/orchestrator typecheck    # Pyright on the orchestrator
pnpm --filter @vibe-platform/web typecheck             # tsc on the web app
```

To re-run a single pytest test:

```bash
uv run pytest apps/orchestrator/tests/test_auth.py::test_logout_clears_session -v
```

---

## Layer 2 — Probe the running orchestrator

Boots everything but only hits the HTTP surface — no GitHub round-trip needed.

```bash
# Terminal 1 — start everything
pnpm dev
```

In another terminal, exercise the public endpoints:

```bash
# Health
curl http://localhost:3001/health
# → {"status":"ok"}

# OpenAPI schema (used by the codegen pipeline)
curl http://localhost:3001/openapi.json | python3 -m json.tool | head -20
# → 6 paths: /api/auth/github/{login,callback}, /api/auth/{logout,session}, /api/me, /health

# OAuth start endpoint — should redirect to GitHub
curl -i http://localhost:3001/api/auth/github/login
# → HTTP/1.1 302 Found
#   location: https://github.com/login/oauth/authorize?...&scope=read%3Auser+user%3Aemail&state=...
#   set-cookie: vibe_oauth_state=...; HttpOnly; ...

# Protected endpoints without a session
curl -o /dev/null -w "%{http_code}\n" http://localhost:3001/api/me
# → 401
curl -o /dev/null -w "%{http_code}\n" http://localhost:3001/api/auth/session
# → 401
```

If the orchestrator boots cleanly, paths are present, and the unauthenticated paths return 401, the wiring is working.

### Web app

Open `http://localhost:5173` in a browser. You should see the page redirect to `/login` and render the "Sign in with GitHub" card. The button click navigates to GitHub — that's where Layer 3 picks up.

---

## Layer 3 — Full UI flow with real GitHub

This is the only way to verify "click button, sign in, land on dashboard."

### One-time setup

1. **GitHub** → Settings → Developer settings → OAuth Apps → **New OAuth App**.
2. Fill in:
   - Application name: `vibe-platform (local dev)`
   - Homepage URL: `http://localhost:5173`
   - Authorization callback URL: `http://localhost:3001/api/auth/github/callback`
3. Click **Register application**.
4. Copy the **Client ID**.
5. Click **Generate a new client secret** and copy it (you only see it once).
6. Edit `.env`:

   ```
   GITHUB_OAUTH_CLIENT_ID=<paste>
   GITHUB_OAUTH_CLIENT_SECRET=<paste>
   AUTH_SECRET=<run: openssl rand -base64 32>
   ```

### Run

```bash
docker compose up -d
pnpm dev
```

Open `http://localhost:5173`.

| Step | Expected |
| --- | --- |
| 1. Visit `/` while signed out | Redirects to `/login`, shows "Sign in" card |
| 2. Click **Sign in with GitHub** | Navigates to GitHub authorize page; requested scopes are `read:user` and `user:email` |
| 3. Click **Authorize** | Redirects back to orchestrator's callback, then forward to `http://localhost:5173/dashboard` |
| 4. Dashboard renders | "Welcome, &lt;your-github-username&gt;" + "Sign out" button |
| 5. Hard-refresh `/dashboard` | Stays signed in |
| 6. Open a new tab to `http://localhost:5173/dashboard` | Loads dashboard directly (cookie persists) |
| 7. Click **Sign out** | Returns to `/login`; the session document is deleted |
| 8. Visit `/dashboard` directly while signed out | Redirects to `/login` |

### Database verification

```bash
docker exec -it vibe-mongo mongosh vibe_platform

# In mongosh:
db.users.find().pretty()
# → one document with github_user_id, github_username, email, ...

db.sessions.find().pretty()
# → one document while signed in; empty after sign-out
```

### Manual cookie probe

Copy the `vibe_session` cookie value from browser dev tools (Application → Cookies → `localhost:3001`), then:

```bash
curl --cookie "vibe_session=<paste>" http://localhost:3001/api/me
# → JSON with your user data

curl http://localhost:3001/api/me
# → {"detail":"unauthenticated"}
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Orchestrator crashes on startup with `ValidationError: 6 validation errors for Settings` | `.env` not present or missing required vars | Confirm `.env` exists at repo root with `MONGODB_URI`, `AUTH_SECRET`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, `WEB_BASE_URL`, `ORCHESTRATOR_BASE_URL` |
| `db.connect_failed` in orchestrator log | Mongo not running | `docker compose up -d`, then `docker ps` to confirm `vibe-mongo` is Up |
| GitHub returns `redirect_uri_mismatch` | Callback URL in the OAuth App doesn't match `${ORCHESTRATOR_BASE_URL}/api/auth/github/callback` | Edit the OAuth App on GitHub or fix `ORCHESTRATOR_BASE_URL` in `.env` |
| Browser stays on `/login` after authorizing | Session cookie not set — usually a CORS or `credentials: 'include'` issue | Open dev tools → Network → click the callback redirect → the response should have a `set-cookie: vibe_session=...` header. If it does, confirm `WEB_BASE_URL` matches the URL you're hitting in the browser. |
| "Failed to fetch /api/me" in browser console | Orchestrator unreachable or CORS misconfigured | Check `VITE_ORCHESTRATOR_BASE_URL` in `.env` matches the orchestrator's actual address |
| Pytest test_auth tests crash with `RuntimeError: Task ...` | Likely a regression in the test event-loop wiring | Tests must use the `client` fixture (httpx.AsyncClient + ASGITransport). Don't add `TestClient`-based tests for DB-touching code. |
| `pnpm typecheck` fails with `Stub file not found for "db" / "shared_models"` | A workspace package is missing its `py.typed` marker | Make sure `python_packages/<pkg>/src/<pkg>/py.typed` exists, then `uv sync --all-packages --all-extras --reinstall` |

---

## What to run when

| When | Run |
| --- | --- |
| After every change, before commit | `pnpm typecheck && pnpm lint && pnpm test` |
| After changing an orchestrator route or response model | Layer 1 + regenerate types (see `CONTRIBUTING.md`) |
| After changing UI behaviour | Layer 1 + Layer 2, then click through the flow in a browser |
| After upgrading dependencies | All three layers |
| Before merging a slice | All three layers |
