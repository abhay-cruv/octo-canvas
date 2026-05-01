# Slice 2 — OAuth `repo` scope + repo connection

Slice 1 gave us a signed-in user. This slice lets that user **connect any number of repos** to their account, using **the slice-1 OAuth App with the `repo` scope added** — *not* a separate GitHub App, no installation flow, no webhook server, no smee tunnel.

Connection is a *logical* state — the `Repo` document gets created with `clone_status="pending"`. Nothing is cloned, no sandbox is spawned, no introspection runs. Those land in slices 3 and 4.

The point of this slice is to wire up the OAuth-token repo path end-to-end (token persistence, available-repo listing, connect/disconnect, **graceful re-auth on token expiry/revocation**) on the simplest possible surface.

**Do not build features beyond this slice.** No sandbox, no clone, no introspection, no tasks, no agent runs, no WebSocket, no GitHub App.

---

## Why no GitHub App

We deliberately do *not* register a separate GitHub App. The slice-1 OAuth App with the `repo` scope can clone, fetch, and push on the user's behalf using `githubkit.TokenAuthStrategy(user.github_access_token)`. Tradeoffs accepted:

- ❌ All-or-nothing repo access at consent time (the user grants `repo` — they can't pick specific repos like a GitHub App lets them).
- ❌ Commits/PRs from the agent are attributed to the user, not a bot identity.
- ❌ Org SSO often blocks personal OAuth tokens from accessing org repos until the user clicks "Authorize" per-org on GitHub.
- ❌ No way for an org admin to revoke us cleanly — they'd revoke the user's whole grant.
- ✅ Massively simpler dev setup: one GitHub-side registration, one token type, no PEM, no smee, no webhook server.

This decision is documented in [Plan.md §12](../Plan.md). If we later need per-repo selection or bot identity, we restore the GitHub App path from `git log`.

---

## Context from slice 1

Slice 1 is signed off. Read it ([slice1.md](slice1.md)) before starting if you don't have it in conversation history. Key things now in place:

- `User` and `Session` Beanie documents in `python_packages/db/src/db/models/`. **You will add a `github_access_token: str | None` field on `User` and update `init_beanie`'s `document_models=[...]` to include the new `Repo` model.**
- `apps/orchestrator/src/orchestrator/middleware/auth.py` exports `require_user` and `get_user_optional`. **Use these.**
- `apps/orchestrator/src/orchestrator/lib/env.py` is `pydantic-settings`. **No new env vars.** All slice-1 OAuth env vars are reused.
- `apps/orchestrator/src/orchestrator/routes/auth.py` already does the OAuth dance via Authlib. **You will: (a) expand the scope from `read:user user:email` to `read:user user:email repo`, and (b) extract the access token from the OAuth response and persist it on `User.github_access_token`.**
- `python_packages/github_integration/src/github_integration/` is empty (just `__init__.py` + `py.typed`). **You will fill it with a thin OAuth-token client + a typed exception for re-auth.**
- `packages/api-types/generated/schema.d.ts` is real (regenerated against the live orchestrator at the end of slice 1). **You will regenerate it again at the end of this slice.**
- TanStack Router file routes live under `apps/web/src/routes/_authed/`. The `_authed` guard layout already exists.
- Pyright strict and TS strict are the bar.

---

## What "done" looks like

After this task, a signed-in user can:

1. Visit `/dashboard` and click "Connect repositories".
2. Land on `/repos`. If they have a valid token with `repo` scope, see two sections: "Connected" (initially empty) and a CTA to browse available repos.
3. If they signed in *before* this slice (slice-1 token without `repo` scope), see a "Reconnect GitHub" prompt instead — clicking it re-runs the OAuth flow with the new scope.
4. Click "Browse repos" → `/repos/connect` → list of every repo their token can see (`GET /user/repos`), minus already-connected ones.
5. Click "Connect" on a few → each becomes a row in the connected list with `clone_status: pending`.
6. Click "Disconnect" on one → it disappears. The other rows are untouched.
7. **Token revocation handling:** if the user revokes the OAuth grant on GitHub (Settings → Applications → Authorized OAuth Apps → Revoke), the next repo call returns `403 {"detail": "github_reauth_required"}`. The web app shows the Reconnect button. Reconnecting restores the list **without losing already-connected `Repo` documents**.

That is the entire user-facing scope.

---

## What to build

### 1. Update slice 1 OAuth — `apps/orchestrator/src/orchestrator/routes/auth.py`

Two changes to the existing file:

- **Scope expansion**: change `OAUTH_SCOPE = "read:user user:email"` to `OAUTH_SCOPE = "read:user user:email repo"`.
- **Token persistence**: in the callback handler, after `_upsert_user(profile)` succeeds, save `token["access_token"]` onto `user.github_access_token` and `await user.save()`. Pass the token through to `_upsert_user` (cleanest) or set it on the returned `User` and save.

The OAuth flow itself doesn't change — same redirect, same state cookie, same callback URL.

### 2. Beanie model updates — `python_packages/db/src/db/models/`

**`user.py`** — add one field:

```python
class User(Document):
    # ... existing fields ...
    github_access_token: str | None = None  # null until first OAuth callback or after a 401-driven clear
```

Default to `None` so existing test fixtures and seed code keep working.

**`repo.py`** — new file:

```python
from datetime import UTC, datetime
from typing import Annotated, Literal

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


def _now() -> datetime:
    return datetime.now(UTC)


class Repo(Document):
    user_id: PydanticObjectId
    github_repo_id: Annotated[int, Indexed(unique=True)]
    full_name: str
    default_branch: str
    private: bool
    # Slice 3 widens this to RepoIntrospection | None — keep typed as None for now.
    introspection: None = None
    clone_status: Literal["pending", "cloning", "ready", "failed"] = "pending"
    clone_path: str | None = None
    last_synced_at: datetime | None = None
    connected_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "repos"
```

**No `installation_id`** — the user's OAuth token is the only credential.

Register both in `init_beanie`'s `document_models=[...]` in `db/connect.py`. Export from `db/models/__init__.py` and `db/__init__.py`.

### 3. Pydantic API models — `python_packages/shared_models/src/shared_models/`

**`github.py`**:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AvailableRepo(BaseModel):
    github_repo_id: int
    full_name: str
    default_branch: str
    private: bool
    description: str | None


class ConnectedRepo(BaseModel):
    id: str  # str(_id)
    github_repo_id: int
    full_name: str
    default_branch: str
    private: bool
    clone_status: Literal["pending", "cloning", "ready", "failed"]
    connected_at: datetime


class ConnectRepoRequest(BaseModel):
    github_repo_id: int
    full_name: str  # "owner/repo" — server re-fetches to verify access
```

**Extend `user.py`** to surface re-auth state to the frontend:

```python
class UserResponse(BaseModel):
    # ... existing fields ...
    needs_github_reauth: bool  # True iff user.github_access_token is None
```

The orchestrator computes this at the API boundary (it never returns the raw token to the web app).

Export from `shared_models/__init__.py`.

### 4. github_integration package — `python_packages/github_integration/src/github_integration/`

Replace the empty `__init__.py` with three small modules.

**`exceptions.py`**:

```python
class GithubReauthRequired(Exception):
    """Raised when a GitHub call returns 401 — the stored token is no longer valid."""
```

**`client.py`**:

```python
from collections.abc import Awaitable, Callable
from typing import TypeVar

from githubkit import GitHub, TokenAuthStrategy
from githubkit.exception import RequestFailed

from .exceptions import GithubReauthRequired

T = TypeVar("T")


def user_client(token: str) -> GitHub[TokenAuthStrategy]:
    return GitHub(TokenAuthStrategy(token))


async def call_with_reauth(fn: Callable[[], Awaitable[T]]) -> T:
    """Run a githubkit call; convert 401 to GithubReauthRequired."""
    try:
        return await fn()
    except RequestFailed as exc:
        if exc.response.status_code == 401:
            raise GithubReauthRequired() from exc
        raise
```

**`__init__.py`** exports both. **No App JWT, no token cache, no webhook verifier.** Drop `pyjwt` from this package's `pyproject.toml` (it was added for the App path; not needed now).

### 5. Routes — `apps/orchestrator/src/orchestrator/routes/repos.py`

One module. No `routes/github.py`, no `lib/github.py`.

A small helper for the 401-driven re-auth flow:

```python
from github_integration import GithubReauthRequired

async def _clear_token_and_503(user: User) -> None:
    user.github_access_token = None
    await user.save()
```

Wrap every GitHub call with `call_with_reauth`. On `GithubReauthRequired`, clear the token and raise `HTTPException(status_code=403, detail="github_reauth_required")`.

Endpoints:

- **`GET /api/repos/available`** (auth required) — if `user.github_access_token is None`, return `403 github_reauth_required` immediately. Otherwise, paginate `gh.rest.repos.async_list_for_authenticated_user(affiliation="owner,collaborator,organization_member", per_page=100)`. Filter out repos already in `Repo` for this user. Return `list[AvailableRepo]`.
- **`GET /api/repos`** (auth required) — return `list[ConnectedRepo]` from Mongo. Does **not** hit GitHub. Works even if the token is expired (the user can still see what they connected previously).
- **`POST /api/repos/connect`** (auth required) — body `ConnectRepoRequest`. Process:
  1. If `user.github_access_token is None` → 403.
  2. If `Repo` with same `github_repo_id` already exists → 409.
  3. `owner, name = body.full_name.split("/", 1)` (validate format → 400).
  4. `gh.rest.repos.async_get(owner, name)` to verify access. Catch `GithubReauthRequired`. On 404 → 404 `repo not accessible`.
  5. Verify `repo_data.id == body.github_repo_id` (anti-spoof) → 400 if mismatch.
  6. Insert `Repo` with `clone_status="pending"`, `clone_path=None`.
  7. Return `ConnectedRepo`.
- **`DELETE /api/repos/{repo_id}`** (auth required) — confirm `Repo.user_id == current_user.id` (404 otherwise). Delete. Return 204.

Mount in `app.py`:

```python
app.include_router(repos.router, prefix="/api/repos", tags=["repos"])
```

### 6. `/api/me` updates — `apps/orchestrator/src/orchestrator/routes/me.py`

Compute `needs_github_reauth = user.github_access_token is None` and include it in `UserResponse`. (Slice 1's existing handler just passes through user fields — add this one derivation.)

### 7. Web — `apps/web/src/lib/`

**`queries.ts`**: add `availableReposQueryOptions` and `connectedReposQueryOptions`. Treat 403 with body `{"detail":"github_reauth_required"}` as a non-error sentinel — surface a typed flag so the page can switch to the Reconnect view.

```ts
export const availableReposQueryOptions = queryOptions({
  queryKey: ['repos', 'available'],
  queryFn: async () => {
    const { data, response, error } = await api.GET('/api/repos/available');
    if (response.status === 403) return { reauth: true as const };
    if (error) throw error;
    return { reauth: false as const, repos: data ?? [] };
  },
  retry: false,
});
```

(Apply the same pattern to `connectedReposQueryOptions`.)

**`repos.ts`** (new): `connectRepo({github_repo_id, full_name})`, `disconnectRepo(id)`. Mutations also detect 403 and trigger the same reconnect path.

### 8. Web pages — `apps/web/src/routes/_authed/`

- **`_authed/repos.tsx`** — header + two sections.
  - If `meQueryOptions.data.needs_github_reauth === true` OR any repo query returns the reauth sentinel: render a single full-card prompt — "Reconnect GitHub to continue" + a "Reconnect GitHub" button that calls `startGithubLogin()` (top-level redirect, same flow as slice 1).
  - Otherwise: "Connected" list (with Disconnect buttons) and a CTA "Browse repositories" → `/repos/connect`.
- **`_authed/repos/connect.tsx`** — list of `AvailableRepo` with Connect buttons + a search filter. If the available query returns the reauth sentinel, show the same reconnect card.
- **`_authed/dashboard.tsx`** — keep the slice-1 redesign. Add a "Connect repositories" CTA pointing at `/repos`. **If `needs_github_reauth === true`, also show a small inline reconnect banner above the profile card** so the user notices without navigating.

Styling per [AGENTS.md §2.8](../../AGENTS.md): light-mode palette, `bg-black text-white` for primary CTAs (Connect, Reconnect), `bg-white border border-gray-300` for secondary.

### 9. Tests — `apps/orchestrator/tests/`

`test_repos.py`:

- `GET /api/repos` 401 without session, `[]` for fresh user, returns connected list after seeding.
- `GET /api/repos/available` 401 without session, **403 `github_reauth_required` when `User.github_access_token is None`**, returns repos when seeded with a fake token (mock `githubkit.GitHub.rest.repos.async_list_for_authenticated_user`).
- **401 → reauth: when the mocked GitHub call raises `RequestFailed(status_code=401)`, the endpoint clears `User.github_access_token` and returns 403 `github_reauth_required`.** Verify the User doc in Mongo has `github_access_token=None` after.
- `POST /api/repos/connect`: 403 when token is None; 409 on duplicate; 400 on full_name/github_repo_id mismatch; happy path inserts `Repo` with `clone_status="pending"`, `clone_path=None`.
- `DELETE /api/repos/{id}`: 204 happy path; 404 for someone else's repo; 404 for nonexistent.

`test_auth.py` — extend the existing callback test to assert `User.github_access_token == "gh-token"` after the OAuth callback.

`test_me.py` (or extend `test_auth.py`): `/api/me` returns `needs_github_reauth=true` when token is None, `false` when set.

**No `test_webhook.py`, no `test_github_routes.py`** — those are deleted in this slice. (See §10.)

### 10. Code to delete

If you previously implemented the GitHub App path, delete:

- `python_packages/db/src/db/models/github_installation.py` and its references.
- `python_packages/github_integration/src/github_integration/auth.py` (App JWT + InstallationTokenCache).
- `python_packages/github_integration/src/github_integration/webhook.py`.
- The `client.py` from the old App path — replace with the OAuth-token version above.
- `apps/orchestrator/src/orchestrator/lib/github.py` (App client singleton).
- `apps/orchestrator/src/orchestrator/routes/github.py` (install-url, installations, refresh, webhook).
- `apps/orchestrator/tests/test_webhook.py`, `apps/orchestrator/tests/test_github_routes.py`.
- `Repo.installation_id` field if present.
- `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_WEBHOOK_SECRET`, `GITHUB_APP_SLUG` from `Settings`, `.env.example`, and `tests/conftest.py`.
- `pyjwt` from `python_packages/github_integration/pyproject.toml`.
- `smee-client` devDep from root `package.json` and the `pnpm dev:webhook` script.
- README sections "Setting up the GitHub App (local dev)" and "Webhook delivery in local dev".

### 11. Regenerate API types

End of slice, with the orchestrator running:

```bash
pnpm --filter @vibe-platform/api-types gen:api-types
```

Verify `schema.d.ts` exposes `/api/repos`, `/api/repos/available`, `/api/repos/connect`, `/api/repos/{repo_id}` and that `UserResponse` includes `needs_github_reauth`. Confirm none of `/api/github/...` paths are present.

### 12. README

Update the existing "Setting up GitHub OAuth (local dev)" section: change the documented scope from `read:user user:email` to `read:user user:email repo`. Add one paragraph "Connecting repositories" describing the dashboard → `/repos` flow and the Reconnect prompt.

No new sections about GitHub Apps or smee.

---

## What's intentionally out of scope

- Cloning anywhere. `Repo.clone_status` stays `"pending"`, `clone_path` stays `None`. (Slice 4.)
- Sandbox provisioning. (Slice 4.)
- Repo introspection. (Slice 3.)
- The `/api/repos/{id}/reintrospect` and `/api/repos/{id}/sync` endpoints. (Slices 3 + 4.)
- Encrypting `User.github_access_token` at rest. **Followup for v1.1** — added to `progress.md` followups when this slice ships.
- Refresh tokens. GitHub OAuth Apps issue **non-expiring** access tokens by default; refresh tokens only apply to "OAuth apps with expiring user access tokens" (opt-in). We do **not** opt in.
- Org SSO auto-detection / "this org needs you to authorize" messaging. We surface 404s on individual repos and let the user click through to GitHub themselves.
- A "switch GitHub account" flow. Reconnecting just re-authorizes the same account.
- shadcn/ui components. Plain Tailwind + AGENTS.md palette only.
- WebSockets, tasks, agent runs.

---

## Acceptance criteria

1. `pnpm typecheck && pnpm lint && pnpm test` all green.
2. `pnpm build` builds every workspace.
3. `pnpm install` from root completes cleanly. `smee-client` is gone from `package.json`.
4. `uv sync --all-packages --all-extras` completes. `pyjwt` is gone from `python_packages/github_integration/pyproject.toml`.
5. `curl http://localhost:3001/openapi.json` includes `/api/repos`, `/api/repos/available`, `/api/repos/connect`, `/api/repos/{repo_id}` and **does not** include any `/api/github/*` paths.
6. After `gen:api-types`, `schema.d.ts` reflects the above and `UserResponse` includes `needs_github_reauth: boolean`.
7. End-to-end manual run with all three apps (`pnpm dev`):
   - Sign out (if signed in from slice 1) → Sign in → consent screen now requests `repo` scope alongside `read:user user:email`.
   - `users` doc in Mongo has `github_access_token` populated.
   - `/dashboard` → "Connect repositories" → `/repos` shows the empty connected list and a "Browse repositories" link (no installations section).
   - `/repos/connect` lists repos from `GET /user/repos`. Connect three.
   - Each connected repo lands in Mongo with `clone_status="pending"`, `clone_path=null`, **no `installation_id`**.
   - Disconnect one → it's deleted; the others remain.
   - On GitHub, revoke the OAuth grant (Settings → Applications → Authorized OAuth Apps → Revoke). Refresh `/repos`. The page renders the Reconnect prompt; `users` doc has `github_access_token=null`. Click Reconnect → through OAuth → token is restored, the previously-connected `Repo` rows are still there.
8. Pyright strict zero errors. TS strict zero errors.

---

## Hard rules — do not violate

- **Do not register a GitHub App.** No `GITHUB_APP_*` env vars, no PEMs, no installation tokens, no `/api/github/*` routes.
- **Do not run a webhook server.** No HMAC verification code, no smee tunnel.
- **Do not store the OAuth access token in cookies, logs, or API responses.** Only in `User.github_access_token` (Mongo) and only inside `githubkit` calls. The web app sees `needs_github_reauth: bool`, never the token itself.
- **Do not silently delete `Repo` rows when the token expires.** Connected repos are user state that must survive token churn — the user reconnects and finds them intact.
- **Do not skip 401 handling.** Every GitHub call must run through `call_with_reauth` (or equivalent) so a revoked token surfaces as `github_reauth_required`, not a 500.
- **Do not relax Pyright strict.** Use targeted `# type: ignore[<rule>]` only if a real upstream typing gap forces it.
- **Do not introduce a different GitHub library.** githubkit only.
- **Do not rebuild `dashboard.tsx`** beyond adding the "Connect repositories" CTA and the inline reconnect banner.

---

## When done

Write a brief summary covering:

1. The token-persistence + 401-clear flow — anything subtle about ordering between "save token" and "use token"?
2. The reconnect UX — how the dashboard, `/repos`, and `/repos/connect` all converge on the same `startGithubLogin()` path without duplicating logic.
3. Any GitHub-side surprises (org SSO friction, `affiliation` parameter quirks, pagination edge cases).
4. Any decision points where this brief was ambiguous and you made a judgment call.
5. Confirm each acceptance criterion with command output or verified-behavior description.
6. Flag followups for v1.1 (e.g., encrypt `User.github_access_token` at rest).

Do not start slice 3 automatically. Wait for user review and approval.
