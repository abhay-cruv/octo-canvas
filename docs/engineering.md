# Engineering handbook

The **end-to-end change flow** for this repo: how a feature crosses from the database, through the orchestrator, through the type-generation step, into the frontend. Read it once before making your first change, then keep it open as a reference.

For testing instructions see [TESTING.md](TESTING.md). For agent rules see [../AGENTS.md](../AGENTS.md). For active state see [progress.md](progress.md). For the contributions log see [Contributions.md](Contributions.md).

---

## Architecture rules (humans + agents)

Both human contributors and AI coding agents must follow these. Agent-specific extras live in [../AGENTS.md](../AGENTS.md).

### Reuse before you write

Before adding any new function, type, component, route, or package, search the repo:

```bash
grep -rn "<thing-you-want-to-name>" apps/ packages/ python_packages/
```

If something close exists, **use or extend it**. Don't fork. Don't copy-paste. If a structural change is needed to fit your case, surface it before refactoring.

### Modular, not monolithic

- One responsibility per file. If a module does two unrelated things, split it.
- Soft caps: Python module ≤ 300 lines, TS module ≤ 250 lines, function ≤ 50 lines. Signals, not laws.
- Routes: one file per resource (`routes/auth.py`, `routes/repos.py`). No monolithic `routes.py`.
- React components: one component per file unless trivially co-located.
- No kitchen-sink `utils.py` / `helpers.py`. Name modules by what they do, not what they are.

### Strictness

- Pyright **strict**. No untyped functions. No `Any` outside generated code. Targeted `# pyright: ignore[<rule>]` is acceptable for known third-party type gaps; never disable strict globally.
- TypeScript: `strict: true`, `noUncheckedIndexedAccess: true`. No `any` outside generated code.

### Don't add what wasn't asked for

- No defensive error handling for cases that can't happen.
- No backwards-compatibility shims when you can change the code in place.
- No TODO scaffolding for "future" features.
- No comments explaining what well-named code already says.

---

## Documentation update policy

Some docs are **live state**. Update them. Others are **stable** — touch only on explicit instruction.

| File | Policy |
| --- | --- |
| [progress.md](progress.md) | **Always update** when you ship code or change slice state |
| [Contributions.md](Contributions.md) | **Always update** — append a one-line entry every session (human or agent) |
| [engineering.md](engineering.md) (this file) | **Always update** when you set a new convention |
| [agent_context.md](agent_context.md) | **Always update** when the repo's "shape" changes (new package, new boundary, new gotcha) |
| [Plan.md](Plan.md) | **Touch only when explicitly asked** — design lock during slice execution |
| [scaffold.md](scaffold.md), [slice/*.md](slice/) | **Touch only when explicitly asked** — historical briefs, append-only |
| [../CLAUDE.md](../CLAUDE.md) | **Touch only when explicitly asked** — thin entry-point pointer, stable |
| [../README.md](../README.md) | **Touch only when explicitly asked** — user-facing setup |
| [../AGENTS.md](../AGENTS.md) | **Touch only when explicitly asked** — canonical agent rules |

Don't create new top-level `.md` files without a clear reader. If you need to capture something, append to one of the always-update files above.

---

## Mental model — where types come from

Types flow in one direction:

```
Pydantic models (python_packages/shared_models, db/models)
   │
   ▼
FastAPI routes (apps/orchestrator)
   │  uses the Pydantic models as request/response shapes
   ▼
/openapi.json  (served at runtime by FastAPI)
   │
   ▼  pnpm --filter @octo-canvas/api-types gen:api-types
   │
   ▼
packages/api-types/generated/schema.d.ts  (TypeScript)
   │
   ▼
apps/web (uses `paths`/`components` types via openapi-fetch)
```

**Pydantic is the source of truth.** TS types are derived. You never hand-edit `schema.d.ts`.

Database shape is **separate** from API shape:

- `db/models/User` (Beanie `Document`) — the Mongo schema. Has `_id`, indexes, internal fields.
- `shared_models/UserResponse` (Pydantic `BaseModel`) — the API shape. What the frontend receives.

Don't merge them. The orchestrator route is responsible for converting `User` → `UserResponse` at the boundary. This keeps the public API decoupled from internal storage.

---

## Backend change flow

The five steps below cover the typical "add or modify an endpoint" change. Skip the steps that don't apply to your specific change.

### Step 1 — Define the wire shape

If your endpoint introduces a new request body or response shape, add it to [python_packages/shared_models/](python_packages/shared_models/).

```python
# python_packages/shared_models/src/shared_models/repo.py
from pydantic import BaseModel

class RepoResponse(BaseModel):
    id: str
    full_name: str
    default_branch: str
```

Re-export from [shared_models/__init__.py](python_packages/shared_models/src/shared_models/__init__.py):

```python
from shared_models.repo import RepoResponse
__all__ = ["UserResponse", "RepoResponse"]
```

**Why this layer exists:** the orchestrator and the bridge will both speak the same wire protocol over WebSocket later. By keeping wire shapes in a shared package, both apps can `import shared_models` and get the same Pydantic class. The frontend gets the same shape via codegen.

### Step 2 — Define the storage shape (if needed)

If your feature persists data, add a Beanie `Document` in [python_packages/db/src/db/models/](python_packages/db/src/db/models/).

```python
# python_packages/db/src/db/models/repo.py
from datetime import UTC, datetime
from typing import Annotated
from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field

def _now() -> datetime: return datetime.now(UTC)

class Repo(Document):
    user_id: PydanticObjectId
    github_repo_id: Annotated[int, Indexed(unique=True)]
    full_name: str
    created_at: datetime = Field(default_factory=_now)
    class Settings:
        name = "repos"
```

Then:

1. Re-export from [db/models/__init__.py](python_packages/db/src/db/models/__init__.py).
2. **Register the model with Beanie** in [db/connect.py](python_packages/db/src/db/connect.py) — add it to the `document_models` list passed to `init_beanie`. If you skip this step the document will not be queryable.
3. Re-export from [db/__init__.py](python_packages/db/src/db/__init__.py) if it should be importable as `from db import Repo`.

**Style notes:**

- Always use `datetime.now(UTC)` via a `_now()` helper, never `datetime.utcnow()` (deprecated, fails Pyright strict).
- Mark every uniquely-keyed field with `Annotated[T, Indexed(unique=True)]`.
- Keep the `Settings.name` plural and snake_cased — that's the Mongo collection name.

### Step 3 — Implement the route

Routes live in [apps/orchestrator/src/orchestrator/routes/](apps/orchestrator/src/orchestrator/routes/). One file per resource.

```python
# apps/orchestrator/src/orchestrator/routes/repos.py
from fastapi import APIRouter, Depends
from db.models import Repo, User
from shared_models import RepoResponse
from ..middleware.auth import require_user

router = APIRouter()

@router.get("", response_model=list[RepoResponse])
async def list_repos(user: User = Depends(require_user)) -> list[RepoResponse]:
    repos = await Repo.find(Repo.user_id == user.id).to_list()
    return [RepoResponse(id=str(r.id), full_name=r.full_name, default_branch=r.default_branch) for r in repos]
```

Then mount it in [apps/orchestrator/src/orchestrator/app.py](apps/orchestrator/src/orchestrator/app.py):

```python
from .routes import auth, me, repos

app.include_router(repos.router, prefix="/api/repos", tags=["repos"])
```

**Conventions:**

- Always use `response_model=...` on endpoints. This is what makes the response shape land in `/openapi.json` correctly. Without it the codegen produces `unknown`.
- Always use `user: User = Depends(require_user)` for protected endpoints. Don't reach into cookies directly — the dependency is the only blessed path.
- Convert `User` (Beanie) → `UserResponse` (Pydantic) at the route boundary. Do not return the Beanie document directly.
- Return `dict[str, str]`, `list[X]`, or a Pydantic model. Never return `dict[str, Any]` from a typed endpoint.

### Step 4 — Add env config (if needed)

If your feature needs a new env var, extend [apps/orchestrator/src/orchestrator/lib/env.py](apps/orchestrator/src/orchestrator/lib/env.py):

```python
class Settings(BaseSettings):
    ...
    new_thing_url: str = Field(alias="NEW_THING_URL")
```

Then:

1. Add it to [.env.example](.env.example) with a descriptive comment.
2. Add it to your local `.env` so the orchestrator boots.
3. Document it in [README.md](README.md) if it requires external setup.

Required env vars (no default) make the orchestrator fail-fast at startup. That's correct — silent fallback to a wrong default is much worse than a clear startup error.

### Step 5 — Run typecheck and tests

```bash
pnpm --filter @octo-canvas/orchestrator typecheck
pnpm --filter @octo-canvas/orchestrator test
```

If Pyright complains about a third-party library's types (Authlib is a known weak-types case), use targeted `# pyright: ignore[reportUnknownMemberType]` rather than disabling strict mode.

If a test that touches the database fails with `RuntimeError: Task ...`, you've hit the event-loop trap — see [TESTING.md](TESTING.md). Use the `client` fixture in [apps/orchestrator/tests/conftest.py](apps/orchestrator/tests/conftest.py), don't import `TestClient` directly.

---

## Type generation flow

After **any** change to:

- A FastAPI route (added, removed, signature changed)
- A `response_model` (added, removed, fields changed)
- A Pydantic model used in a request or response

…you need to regenerate the TypeScript types.

```bash
# Terminal 1 — keep the orchestrator running
pnpm --filter @octo-canvas/orchestrator dev

# Terminal 2 — regenerate
pnpm --filter @octo-canvas/api-types gen:api-types
```

What this does:

1. Hits `http://localhost:3001/openapi.json` (FastAPI generates this from your routes + `response_model` declarations).
2. Runs `openapi-typescript` against that schema.
3. Writes [packages/api-types/generated/schema.d.ts](packages/api-types/generated/schema.d.ts).

The generated file is **gitignored** — it's an artifact, not source. You regenerate it locally; CI regenerates it on its own when needed (slice 2+ will automate this).

After regenerating, run `pnpm --filter @octo-canvas/web typecheck` — if a route's response shape changed, the frontend's `openapi-fetch` calls will fail to compile and you'll see the exact callsite that needs updating. That's the type-system pulling its weight.

**Common mistake:** forgetting `response_model=...` on a new route. The route works, but `gen:api-types` produces `unknown` for the response, and the frontend can't use it. Always set `response_model`.

---

## Frontend change flow

The frontend follows a layered structure. Working from the bottom up:

### Layer A — API client (`apps/web/src/lib/api.ts`)

Already set up. You almost never edit this. It exports a typed `api` instance backed by `openapi-fetch`. Every HTTP call goes through it.

```ts
import { api } from './lib/api';

const { data, response } = await api.GET('/api/me');
//                                  ^ autocompleted from generated paths
//        ^ typed as UserResponse | undefined
```

If you call a path that doesn't exist, TypeScript fails. If you mistype the method (`api.PUT` on a GET-only path), TypeScript fails.

### Layer B — Query options (`apps/web/src/lib/queries.ts`)

Wrap each backend call in a TanStack Query options factory. Add new ones next to `meQueryOptions`.

```ts
// apps/web/src/lib/queries.ts
import { queryOptions } from '@tanstack/react-query';
import { api } from './api';

export const reposQueryOptions = queryOptions({
  queryKey: ['repos'],
  queryFn: async () => {
    const { data, response } = await api.GET('/api/repos');
    if (response.status === 401) return null;
    if (!data) throw new Error('Failed to fetch /api/repos');
    return data;
  },
  staleTime: 30_000,
  retry: false,
});
```

**Conventions:**

- 401 returns `null` (signed-out is a state, not an error). Other failures throw.
- `retry: false` for auth-gated reads — a 401 won't become a 200 by retrying.
- `staleTime: 30_000` is a sane default for "this data doesn't change often." Tune per query.
- Keep the `queryKey` flat and serializable.

### Layer C — Mutations and side-effect helpers (`apps/web/src/lib/auth.ts` and similar)

For things that aren't queries — login redirects, logout, anything that triggers a side effect — write a small helper module.

```ts
// apps/web/src/lib/repos.ts
import { api } from './api';

export async function disconnectRepo(id: string): Promise<void> {
  const { response } = await api.DELETE('/api/repos/{id}', {
    params: { path: { id } },
  });
  if (!response.ok) throw new Error(`Disconnect failed: ${response.status}`);
}
```

Components import these. They don't call `api` directly.

### Layer D — Routes (`apps/web/src/routes/`)

TanStack Router uses **file-based routing**. The folder structure is the URL structure, with these special prefixes:

- `__root.tsx` — global root layout. Defines context (the `QueryClient`).
- `_authed.tsx` — pathless layout. Anything inside `_authed/` is protected behind the auth check.
- `index.tsx` — the index for that segment.
- `$param.tsx` — dynamic segment named `param`.

Add a new protected route by creating a file:

```tsx
// apps/web/src/routes/_authed/repos.tsx
import { createFileRoute } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { reposQueryOptions } from '../../lib/queries';

export const Route = createFileRoute('/_authed/repos')({
  loader: ({ context }) => context.queryClient.ensureQueryData(reposQueryOptions),
  component: ReposPage,
});

function ReposPage() {
  const { data: repos } = useQuery(reposQueryOptions);
  if (!repos) return null;
  return (
    <ul>
      {repos.map((r) => <li key={r.id}>{r.full_name}</li>)}
    </ul>
  );
}
```

After adding a route file, `tsr generate` rebuilds `apps/web/src/routeTree.gen.ts`. This runs automatically inside `pnpm dev` and `pnpm typecheck` and `pnpm build`. You don't run it by hand.

**Auth gating:** drop the file under `_authed/`. The guard in [_authed.tsx](apps/web/src/routes/_authed.tsx) runs before any route inside loads, redirects to `/login` if there's no session. Anywhere outside `_authed/` is public.

**Preloading:** The `loader: ({ context }) => context.queryClient.ensureQueryData(...)` pattern primes the query cache before the component renders. The `useQuery(...)` inside the component reads from that already-warm cache, so the page renders without a loading flash.

### Layer E — Components and shared UI

For now: plain Tailwind, written inline. shadcn/ui is configured (see [components.json](apps/web/components.json)) but not initialized — slice 2+ will start adding components there.

Folder is [apps/web/src/components/](apps/web/src/components/). When it grows, organize by feature, not by type.

---

## Common cross-cutting tasks

### Adding a new env var that the frontend needs

Vite only exposes env vars prefixed with `VITE_` to the browser. If the frontend needs a value:

1. Add it to `.env.example` with the `VITE_` prefix.
2. Add it to your local `.env`.
3. Declare its type in [apps/web/src/vite-env.d.ts](apps/web/src/vite-env.d.ts).
4. Read it via `import.meta.env.VITE_FOO`.

Server-only secrets must **never** have the `VITE_` prefix — Vite would inline them into the bundle.

### Adding a Python dependency

```bash
# Orchestrator-only:
uv add --package orchestrator some-library

# Bridge-only:
uv add --package bridge some-library

# Shared (a python_package):
uv add --package db some-library
```

This edits the right `pyproject.toml`, updates [uv.lock](uv.lock), and installs into the shared `.venv`. Commit both the manifest change and the lock change.

If pyright complains about missing type stubs for the new library, prefer (in order):
1. The library's own type stubs if it has them (re-run `uv sync --all-packages --all-extras --reinstall`).
2. A `types-<library>` stub package on PyPI (`uv add --package <pkg> --dev types-foo`).
3. Targeted `# pyright: ignore[reportUnknownMemberType]` on the specific line.
4. Last resort: a `reportMissingTypeStubs = false` entry in the package's `pyrightconfig.json` for that one library.

Never disable strict mode globally.

### Adding a TypeScript dependency

```bash
# Web app only:
pnpm --filter @octo-canvas/web add some-library

# Dev dep:
pnpm --filter @octo-canvas/web add -D some-library

# Workspace dependency between packages:
# pnpm picks this up automatically because of pnpm-workspace.yaml.
```

### Adding a workspace package

**Python:**

1. Create `python_packages/<pkg>/pyproject.toml` (copy an existing one for shape).
2. Create `python_packages/<pkg>/src/<pkg>/__init__.py` and `py.typed`.
3. Create `python_packages/<pkg>/package.json` (copy an existing one — Turbo glue only).
4. Add to root [pyproject.toml](pyproject.toml)'s `[tool.uv.sources]`.
5. `uv sync --all-packages --all-extras`.

**TypeScript:**

1. Create `packages/<pkg>/package.json` with name `@octo-canvas/<kebab>`.
2. Create `packages/<pkg>/tsconfig.json` extending `@octo-canvas/tsconfig/library.json`.
3. Add to root [tsconfig.json](tsconfig.json) `references` array.
4. `pnpm install`.

Both ecosystems automatically pick up new workspace packages because of the glob in [pnpm-workspace.yaml](pnpm-workspace.yaml) and [pyproject.toml](pyproject.toml).

---

## Testing your change

For every change:

```bash
pnpm typecheck && pnpm lint && pnpm test
```

For backend route changes specifically:

```bash
# 1. Run the focused test suite first
pnpm --filter @octo-canvas/orchestrator test

# 2. Then regenerate types and run the frontend typecheck
pnpm --filter @octo-canvas/orchestrator dev   # terminal 1
pnpm --filter @octo-canvas/api-types gen:api-types  # terminal 2 (one-shot)
pnpm --filter @octo-canvas/web typecheck

# 3. Click through the affected page in a browser
pnpm dev
```

For frontend-only changes the loop is just `pnpm dev` and the browser dev tools.

See [TESTING.md](TESTING.md) for the full test matrix and the manual GitHub OAuth round-trip.

---

## Code review hygiene

Before opening a PR:

- [ ] `pnpm typecheck` passes (Pyright strict + tsc strict, both zero errors)
- [ ] `pnpm lint` passes (ruff + ESLint)
- [ ] `pnpm test` passes (real Mongo, mocked GitHub)
- [ ] If you touched a route or response model, you regenerated types and the frontend still typechecks
- [ ] If you added an env var, you updated `.env.example` and the README
- [ ] You did **not** disable Pyright strict mode globally
- [ ] You did **not** introduce a banned dependency (see [../AGENTS.md](../AGENTS.md) §2.6)
- [ ] No business logic in scaffolding paths (placeholder `__init__.py`-only directories should stay that way until they're naturally filled)
- [ ] No `npm`, `yarn`, `pip`, or `poetry` invocations — only `pnpm` and `uv`

---

## Why these conventions exist

| Convention | Reason |
| --- | --- |
| Pydantic is source of truth for wire shapes | One change updates the OpenAPI schema, the generated TS types, and Pyright's view of the world simultaneously. No drift. |
| `response_model` always set | Without it, OpenAPI emits `unknown` and the frontend gets `any`. Half the value of the codegen pipeline depends on this. |
| `User` (Beanie) ≠ `UserResponse` (Pydantic) | API stability. Mongo schema can change (add an internal field, denormalize) without breaking clients. |
| `require_user` dependency, never raw cookie reads | Single auth path means session/cookie/expiry logic lives in one place. Easier to audit, easier to add features (per-route role checks, etc.) later. |
| Cookies hold only opaque session ID | If anyone steals a cookie they can be revoked server-side. If we put user data in the cookie, we have to invalidate the entire signing key to revoke. |
| Strict TS + Strict Pyright | The whole product depends on the type bridge between Python and TypeScript. If either side has untyped escape hatches, the bridge falls apart and you're back to runtime crashes. |
| `uv run` and `pnpm` only | One package manager per language, one source of truth. Mixed-tool repos drift fast. |
| File-based routes | The URL structure *is* the file structure. No "where is the route for `/dashboard`?" hunt. |
