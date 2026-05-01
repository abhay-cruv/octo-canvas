# Slice 3 — Repo introspection

Slice 2 lets a signed-in user connect any number of repos. Each `Repo` document lands in Mongo with `clone_status="pending"`, `clone_path=null`, and **`introspection=None`**. This slice fills that `introspection` field.

The job: when a repo is connected (and on an explicit re-introspect call), the orchestrator inspects the repo via the **GitHub Trees + Contents API** — *not* by cloning — and populates `Repo.introspection_detected` with `primary_language`, `package_manager`, `test_command`, `build_command`, `dev_command`, and `detected_at`. The web UI surfaces those five fields on each connected-repo row plus a "Re-introspect" affordance and an "Edit fields" panel where the user can **override** any field with their own value.

There is no clone, no sandbox, no agent SDK in this slice. Detection is filename-driven first (Trees API), with a narrow fallback to fetching specific manifest blobs (`package.json`, `pyproject.toml`) when the filename alone can't disambiguate the test/build command.

**Do not build features beyond this slice.** No clone, no sandbox, no Sprite, no WebSocket, no tasks, no agent runs.

---

## Why no clone

Cloning belongs to slice 4 (sandbox provider). We do not clone in the orchestrator process — the orchestrator is stateless w.r.t. repo working copies. Tradeoffs accepted:

- ❌ Some heuristics (e.g., parsing `Makefile` recipes, walking a `tests/` tree, detecting monorepo workspace splits) are weaker without a working copy.
- ❌ Two extra GitHub API calls per repo (one Trees call + at most one Contents call for the manifest).
- ✅ Introspection runs in milliseconds in the orchestrator, with no Sprite dependency.
- ✅ The same code works in slice 4 by swapping the "fetch tree/blob" adapter for a filesystem-backed one — no rewrite.

This decision is recorded in [Plan.md §18 — Slice 3](../Plan.md). If we later need richer detection, slice 4's sandboxed working copy lets us upgrade without changing the API surface.

---

## Context from slice 2

Slice 2 is signed off. Read it ([slice2.md](slice2.md)) before starting if you don't have it in conversation history. Key things now in place:

- `Repo` Beanie document at [python_packages/db/src/db/models/repo.py](../../python_packages/db/src/db/models/repo.py) with `introspection: None = None`. **You will widen the field type to `RepoIntrospection | None` and update the default to `None`.**
- `python_packages/github_integration/` exposes `user_client(token)` and `call_with_reauth(fn)` plus `GithubReauthRequired`. **Use these — every GitHub call goes through `call_with_reauth`.** No new client patterns.
- `apps/orchestrator/src/orchestrator/routes/repos.py` already implements connect / disconnect / list / available. **You will: (a) call introspection from inside the connect handler before returning, and (b) add `POST /api/repos/{repo_id}/reintrospect`.**
- `python_packages/repo_introspection/` is empty (just `__init__.py` with a docstring + `py.typed`). **You will fill it.**
- `packages/api-types/generated/schema.d.ts` is real. **You will regenerate it again at the end of this slice.**
- TanStack Router file routes live under `apps/web/src/routes/_authed/`. The connected-repo list is in [apps/web/src/routes/_authed/dashboard.tsx](../../apps/web/src/routes/_authed/dashboard.tsx).
- Pyright strict and TS strict are the bar.

---

## What "done" looks like

After this task, a signed-in user can:

1. Visit `/dashboard` → `/repos/connect` → click "Connect" on a TypeScript repo.
2. The connect response (and the connected-repos list) now includes a populated `introspection` block: `primary_language="TypeScript"`, `package_manager="pnpm"`, `test_command="pnpm test"`, `build_command="pnpm build"` (or `null` for fields the heuristics couldn't determine), and `detected_at` set to "now".
3. The connected-repo row on the dashboard renders those four fields under the repo name (compact pills/labels).
4. Click "Re-introspect" on a row → the row briefly shows a loading state, then re-renders with a fresh `detected_at`. Mongo's `Repo` doc reflects the new values.
5. **Token revocation handling** survives this slice unchanged: if a re-introspect call hits a 401, the existing `call_with_reauth` machinery clears the token and returns 403 `github_reauth_required`. The web app surfaces the same Reconnect prompt.
6. Disconnecting a repo continues to work; introspection state is removed with the row.

That is the entire user-facing scope.

---

## What to build

### 0. Scope amendment — dev_command + per-field overrides (added in-flight)

After the initial draft was approved, scope was expanded to include:

- **`dev_command`** field on `RepoIntrospection` (sibling to `test_command` / `build_command`). Detected per package manager: JS family reads `scripts.dev` then falls back to `scripts.start`; Rust → `cargo run`; Go → `go run .`; Gradle → `gradle run`; otherwise `None`.
- **Per-field user overrides**. The user can pin any of the five fields (`primary_language`, `package_manager`, `test_command`, `build_command`, `dev_command`) to a value of their choice. Detection still runs; overrides take precedence on the wire.

Storage split:

- `Repo.introspection_detected: RepoIntrospection | None` — refreshed on every detect/reintrospect.
- `Repo.introspection_overrides: IntrospectionOverrides | None` — sparse; non-null fields override the detected counterpart. v1 has no "force-clear a non-null detected value to null" — to silence one, set the override to a placeholder string.

Wire shape on `ConnectedRepo`:

- `introspection`: the **effective merged** value (what slice 4+ callers should read for "the test command to run"). `None` only if there's no detection yet.
- `introspection_detected`: raw detection (so the UI can show "Detected: pnpm test" alongside an override and a Reset reverts cleanly).
- `introspection_overrides`: sparse — the UI uses this to flag overridden fields and pre-fill the edit form.

New endpoint: `PATCH /api/repos/{repo_id}/introspection` — body is a `IntrospectionOverrides` (full replacement, not patch-merge of overrides). Send `{}` to clear all overrides. Re-introspect preserves overrides — only `detected` is refreshed.

### 1. `RepoIntrospection` model — `python_packages/shared_models/src/shared_models/`

The detection result is **wire-shaped first** (it ships in API responses) and embedded as-is on the Mongo `Repo` document. Keep it in `shared_models` — `db.models.repo` imports it.

**`introspection.py`**:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

PackageManager = Literal[
    "pnpm", "npm", "yarn", "uv", "poetry", "pip", "cargo", "go", "bundler"
]


class RepoIntrospection(BaseModel):
    primary_language: str | None
    package_manager: PackageManager | None
    test_command: str | None
    build_command: str | None
    detected_at: datetime
```

Export from `shared_models/__init__.py`. **Do not** add it to `github.py` — it's a distinct concern.

Update `ConnectedRepo` in [github.py](../../python_packages/shared_models/src/shared_models/github.py) to include:

```python
class ConnectedRepo(BaseModel):
    # ... existing fields ...
    introspection: RepoIntrospection | None
```

### 2. `Repo` document update — `python_packages/db/src/db/models/repo.py`

Widen the field:

```python
from shared_models.introspection import RepoIntrospection

class Repo(Document):
    # ... existing fields ...
    introspection: RepoIntrospection | None = None
```

No new index. No migration script — existing rows already have `introspection: None` (Mongo stores it as `null`), which is type-compatible after the widen.

### 3. `repo_introspection` package — `python_packages/repo_introspection/src/repo_introspection/`

This is the meat of the slice. Module layout (one responsibility per file, per [AGENTS.md §2.1](../../AGENTS.md)):

```
src/repo_introspection/
├── __init__.py              # exports introspect_via_github + RepoIntrospection
├── github_source.py         # adapter: fetch_tree(owner, name, ref) -> set[str]
│                            # adapter: fetch_blob_text(owner, name, path, ref) -> str | None
├── language.py              # detect primary_language from filename set
├── package_manager.py       # detect package_manager from filename set
├── commands.py              # detect test_command + build_command (uses pm + manifest fallback)
└── orchestrate.py           # introspect_via_github(gh, owner, name, ref) -> RepoIntrospection
```

#### 3a. `github_source.py` — narrow adapter, easy to swap in slice 4

```python
from collections.abc import Awaitable, Callable
from githubkit import GitHub, TokenAuthStrategy

from github_integration import call_with_reauth


async def fetch_tree(
    gh: GitHub[TokenAuthStrategy], owner: str, name: str, ref: str
) -> set[str]:
    """Return the set of repo-relative paths at HEAD of `ref` (recursive)."""
    resp = await call_with_reauth(
        lambda: gh.rest.git.async_get_tree(owner, name, ref, recursive="1")
    )
    return {item.path for item in resp.parsed_data.tree if item.path is not None}


async def fetch_blob_text(
    gh: GitHub[TokenAuthStrategy], owner: str, name: str, path: str, ref: str
) -> str | None:
    """Fetch a single file's contents as utf-8 text. Returns None on 404 or
    decode failure (caller treats as 'no signal')."""
    # Implementation: gh.rest.repos.async_get_content(...) with media-type 'raw'
    # and call_with_reauth wrapping. Return None on non-200 / non-text.
```

The adapter is the **only** code in this package that talks to GitHub. Slice 4 will introduce a sibling `filesystem_source.py` with the same two function signatures — and `orchestrate.py` will accept either via duck-typing (or a thin Protocol if you prefer; the brief leaves that judgment open).

#### 3b. `language.py` — deterministic, list-based

```python
LANGUAGE_BY_EXT: dict[str, str] = {
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".py": "Python",
    ".rs": "Rust",
    ".go": "Go",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".swift": "Swift",
    ".c": "C", ".h": "C",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++",
    ".cs": "C#",
}


def detect_primary_language(paths: set[str]) -> str | None:
    """Pick the language with the most files. Tie → alphabetical (deterministic).
    Ignore files in common vendor dirs (node_modules, .venv, vendor, dist, build,
    target, .git). Returns None if no recognised extension is present."""
```

Vendor-dir filtering is mandatory — without it, every TS repo with a checked-in `node_modules` (rare but fatal) misclassifies as JavaScript.

#### 3c. `package_manager.py` — lockfile-driven, with one disambiguation rule

Order matters: lockfiles first, then manifest-only signals.

```python
def detect_package_manager(paths: set[str]) -> PackageManager | None:
    """
    Priority order (first match wins):
      pnpm-lock.yaml          → "pnpm"
      yarn.lock               → "yarn"
      package-lock.json       → "npm"
      uv.lock                 → "uv"
      poetry.lock             → "poetry"
      Cargo.lock              → "cargo"
      go.sum                  → "go"
      Gemfile.lock            → "bundler"

    No-lockfile fallback (manifest only):
      package.json (no JS lockfile) → "npm"          # the GitHub default
      pyproject.toml (no py lockfile) → check [tool.uv|tool.poetry] section
                                                      via fetch_blob_text;
                                                      else "pip" if requirements.txt
                                                      present, else None
      requirements.txt only         → "pip"

    Returns None if nothing matches.
    """
```

The `pyproject.toml` ambiguity is the **only** case where filename alone is insufficient; `commands.py` reuses the fetched blob text, so we don't fetch it twice.

#### 3d. `commands.py` — manifest-aware

`test_command` / `build_command` derive from `(package_manager, manifest_contents)`:

```python
async def detect_commands(
    paths: set[str],
    pm: PackageManager | None,
    fetch_blob: Callable[[str], Awaitable[str | None]],
) -> tuple[str | None, str | None]:
    """
    Return (test_command, build_command). Strategy:

    JS family (pnpm/yarn/npm):
      Fetch package.json. Read .scripts.test and .scripts.build.
      If .scripts.test exists, test_command = "<pm> test"; else None.
      Same for build.

    Python:
      uv      → ("uv run pytest", None)         # build deferred to slice 6+
      poetry  → ("poetry run pytest", None)
      pip     → ("pytest", None) iff `tests/` dir or `pytest.ini` / `pyproject.toml`
                with [tool.pytest.ini_options] section present; else None.

    Rust:    ("cargo test", "cargo build")
    Go:      ("go test ./...", "go build ./...")
    Ruby:    ("bundle exec rspec", None) iff Gemfile mentions "rspec"; else None
    Otherwise: (None, None)
    """
```

The `fetch_blob` argument is the curry of `github_source.fetch_blob_text` bound to the right `(owner, name, ref)` — keeping `commands.py` GitHub-agnostic so slice 4 can pass a filesystem-backed reader instead.

**Crucial:** parsing `package.json` uses `json.loads` with a try/except → return `(None, None)` on malformed JSON. Pyright strict; no `Any` — type the parsed shape narrowly:

```python
class _PkgJson(TypedDict, total=False):
    scripts: dict[str, str]
```

#### 3e. `orchestrate.py` — the one function the orchestrator calls

```python
from datetime import UTC, datetime

async def introspect_via_github(
    gh: GitHub[TokenAuthStrategy], owner: str, name: str, ref: str
) -> RepoIntrospection:
    paths = await fetch_tree(gh, owner, name, ref)
    language = detect_primary_language(paths)
    pm = detect_package_manager(paths)
    fetch = partial(fetch_blob_text, gh, owner, name, ref=ref)
    test_cmd, build_cmd = await detect_commands(paths, pm, fetch)
    return RepoIntrospection(
        primary_language=language,
        package_manager=pm,
        test_command=test_cmd,
        build_command=build_cmd,
        detected_at=datetime.now(UTC),
    )
```

**One function, one purpose.** The orchestrator route does *not* know about Trees API or filenames — it just calls `introspect_via_github`.

Add `github_integration` and `shared_models` to `python_packages/repo_introspection/pyproject.toml` `dependencies`. Add `githubkit` too (already a transitive dep via `github_integration`, but be explicit).

### 4. Routes — `apps/orchestrator/src/orchestrator/routes/repos.py`

Two changes:

#### 4a. Connect path runs introspection inline

After the `Repo` document is inserted in the existing connect handler, call `introspect_via_github` with `(owner, name, repo_data.default_branch)`, set `repo.introspection = result`, `await repo.save()`. **The connect response includes the populated introspection.**

If introspection raises (network blip, malformed tree, etc.) **other than** `GithubReauthRequired`: log the exception, leave `introspection=None`, and still return the `ConnectedRepo`. Connection is more important than introspection — the user can hit "Re-introspect" later. `GithubReauthRequired` propagates as 403 like elsewhere.

#### 4b. New endpoint — `POST /api/repos/{repo_id}/reintrospect`

```python
@router.post("/{repo_id}/reintrospect", response_model=ConnectedRepo)
async def reintrospect(repo_id: str, current_user: Annotated[User, Depends(require_user)]) -> ConnectedRepo:
    # 1. Fetch the Repo doc; 404 if missing or user_id mismatch.
    # 2. If user.github_access_token is None → 403 github_reauth_required.
    # 3. owner, name = repo.full_name.split("/", 1).
    # 4. Call introspect_via_github(gh, owner, name, repo.default_branch).
    # 5. repo.introspection = result; await repo.save().
    # 6. Return ConnectedRepo (re-marshalled from the updated doc).
```

Same `call_with_reauth` discipline. No body. Idempotent.

No other endpoints. `GET /api/repos` already returns `ConnectedRepo` with the new optional `introspection` field for free.

### 5. Web — `apps/web/src/`

#### 5a. Queries / mutations — `apps/web/src/lib/`

- **`repos.ts`**: add `reintrospectRepo(repoId)` mutation. Same 403-reauth handling pattern as `connectRepo` / `disconnectRepo`.
- **`queries.ts`**: no changes — `connectedReposQueryOptions` already returns the typed `ConnectedRepo[]` from generated types; the new `introspection` field rides along.

#### 5b. UI — `apps/web/src/routes/_authed/dashboard.tsx`

In the connected-repos list, render under each repo's name a row of compact pills:

- `primary_language` → e.g. `"TypeScript"` (gray pill)
- `package_manager` → e.g. `"pnpm"` (gray pill)
- `test_command` → e.g. `"pnpm test"` (mono font, slightly muted)
- `build_command` → e.g. `"pnpm build"` (mono font, slightly muted)

Fields that are `null` render as a muted `"—"` placeholder, **not** hidden — the user should see what we couldn't detect.

Add a "Re-introspect" button per row beside the existing "Disconnect" button. Light-mode palette per [AGENTS.md §2.8](../../AGENTS.md):

- Re-introspect: `bg-white border border-gray-300 text-gray-900 hover:bg-gray-50` (secondary)
- Disconnect: stays as-is

Loading state: while the mutation is pending, the row's pills get `opacity-60` and the button disables.

If `introspection === null` on a row (e.g., introspection failed silently during connect), render a single "Detect repo info" button in place of the pills — clicking it triggers the same re-introspect mutation.

**Do not rebuild `dashboard.tsx`** beyond adding the introspection display + the new button. Keep the slice-2 layout intact.

### 6. Tests — `apps/orchestrator/tests/`

`test_repos.py` extensions:

- `POST /api/repos/connect` happy path now asserts the response body has a populated `introspection` block. Mock `gh.rest.git.async_get_tree` to return a fixture tree containing `pnpm-lock.yaml`, `package.json`, `src/index.ts`. Mock `async_get_content` for `package.json` returning `{"scripts": {"test": "vitest", "build": "tsc"}}`. Expect `primary_language="TypeScript"`, `package_manager="pnpm"`, `test_command="pnpm test"`, `build_command="pnpm build"`.
- `POST /api/repos/connect` with introspection-API failure (mock `async_get_tree` to raise a non-401 `RequestFailed`): the row is still inserted, response has `introspection=None`.
- `POST /api/repos/{id}/reintrospect`: 401 without session; 403 when `github_access_token=None`; 404 for someone else's repo; 404 for nonexistent; happy path updates `introspection` and `detected_at`. Verify the Mongo doc has the new fields.
- **401 → reauth on reintrospect**: mocked `async_get_tree` raises `RequestFailed(status_code=401)` → endpoint clears the token and returns 403 `github_reauth_required`. (Same machinery as slice 2 — no new code needed; the test just confirms no regression.)

`python_packages/repo_introspection/tests/` (new): pure unit tests, no GitHub. Each detector function fed a hand-built `set[str]` and (where relevant) a stub `fetch_blob` callable returning canned manifest text.

- `test_language.py`: TS-heavy repo, Python-heavy repo, mixed (TS wins), node_modules ignored, empty → None.
- `test_package_manager.py`: each lockfile case, manifest-only fallbacks, `pyproject.toml` with `[tool.uv]` → uv, with `[tool.poetry]` → poetry, with neither + `requirements.txt` → pip.
- `test_commands.py`: JS scripts present/absent, malformed `package.json` → `(None, None)`, Python uv → `("uv run pytest", None)`, Rust → `("cargo test", "cargo build")`.

### 7. Regenerate API types

End of slice, with the orchestrator running:

```bash
pnpm --filter @octo-canvas/api-types gen:api-types
```

Verify `schema.d.ts` exposes:
- `POST /api/repos/{repo_id}/reintrospect`
- `ConnectedRepo.introspection: RepoIntrospection | null`
- `RepoIntrospection` with the five fields (`primary_language`, `package_manager`, `test_command`, `build_command`, `detected_at`)

### 8. Docs

- Update [docs/agent_context.md](../agent_context.md) if introspection introduces a new "shape" fact (it should — repo connection now triggers an inline GitHub call beyond the existing access check).
- Update [docs/progress.md](../progress.md) slice status table when the slice goes ✅. List any followups discovered.
- Append a one-line entry to [docs/Contributions.md](../Contributions.md).
- This brief is editable while slice 3 is in flight; freeze it on user sign-off.

---

## What's intentionally out of scope

- **Cloning anywhere.** Detection runs against the GitHub API only. (Slice 4.)
- **Sandbox provisioning.** (Slice 4.)
- **Background re-introspection.** No periodic re-detect, no webhook-triggered refresh — only inline-on-connect and explicit user-initiated re-introspect.
- **Monorepo workspace detection.** Treat the whole repo as one unit. (If the user complains, slice 5+ followup.)
- **Framework detection** (React vs Vue vs Svelte; Django vs Flask; etc.). Language + package manager + test/build is enough for v1.
- **Lint command, format command.** Detection covers `dev_command` (added scope amendment §0) but lint/format remain out of scope.
- **Rate-limit handling beyond what `call_with_reauth` already provides.** GitHub's 5000-req/hour user-token budget is plenty for v1.
- **Encrypting the OAuth token at rest.** Still a v1.1 followup.
- **WebSockets, tasks, agent runs.**

---

## Acceptance criteria

1. `pnpm typecheck && pnpm lint && pnpm test` all green.
2. `pnpm build` builds every workspace.
3. `uv sync --all-packages --all-extras` completes; `repo_introspection` resolves.
4. `pytest python_packages/repo_introspection` passes (pure unit tests, no network).
5. `curl http://localhost:3001/openapi.json` includes `POST /api/repos/{repo_id}/reintrospect` and `RepoIntrospection` as a referenced schema.
6. After `gen:api-types`, `schema.d.ts` reflects the above and `ConnectedRepo.introspection` is `RepoIntrospection | null`.
7. End-to-end manual run with all three apps (`pnpm dev`):
   - Sign in → `/repos/connect` → connect a known TS repo with `pnpm-lock.yaml` + a `scripts.test`/`scripts.build` in `package.json`. The dashboard row shows `TypeScript / pnpm / pnpm test / pnpm build`. Mongo's `Repo` doc shows the populated `introspection` subdocument.
   - Connect a Python repo with `uv.lock` and `pyproject.toml`. The row shows `Python / uv / uv run pytest / —`.
   - Click "Re-introspect" on the TS row → `detected_at` advances; pills re-render.
   - Revoke the OAuth grant on GitHub → click "Re-introspect" → row turns into Reconnect prompt; `users` doc has `github_access_token=null`. Reconnect → introspection state is preserved (never deleted by token clearing).
8. Pyright strict zero errors. TS strict zero errors.

---

## Hard rules — do not violate

- **Do not clone.** No GitPython, no `subprocess(["git", ...])`, no working copies. Detection is GitHub-API-only in this slice.
- **Do not bypass `call_with_reauth`.** Every GitHub call (Trees, Contents) goes through it so 401s clear the token uniformly.
- **Do not delete `Repo` rows on introspection failure.** Connection > introspection. A repo with `introspection=None` is valid state.
- **Do not deepen the GitHub adapter.** `github_source.py` exposes exactly two functions: `fetch_tree` and `fetch_blob_text`. If a heuristic needs something else, surface it — don't grow the adapter.
- **Do not introduce a new GitHub library.** githubkit only.
- **Do not relax Pyright strict.** Targeted `# pyright: ignore[<rule>]` only for genuine third-party gaps.
- **Do not rebuild `dashboard.tsx`** beyond adding the introspection pills and the Re-introspect button.
- **Do not store introspection state outside the `Repo` document.** No new collection. No Redis cache.
- **Do not hold the orchestrator's request handler open for arbitrarily long introspection runs.** Trees + at most one Contents call ≤ 2s in practice; if a single repo's detection exceeds ~5s, log it and bail with `introspection=None` rather than blocking the connect response.

---

## When done

Write a brief summary covering:

1. The connect-vs-reintrospect symmetry — anything subtle about how the same `introspect_via_github` function is reused?
2. Detection accuracy on the manually-tested repos: what was detected correctly, what was missed, and why.
3. Any GitHub-side surprises (Trees API truncation for huge repos, Contents API rate-limit quirks, default-branch edge cases).
4. Decision points where this brief was ambiguous and you made a judgment call.
5. Confirm each acceptance criterion with command output or verified-behavior description.
6. Flag followups for v1.1 (e.g., framework detection, monorepo workspace splits, periodic refresh).

Do not start slice 4 automatically. Wait for user review and approval.
