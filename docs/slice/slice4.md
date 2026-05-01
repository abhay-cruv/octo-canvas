# Slice 4 — Sandbox provisioning (the box exists)

Slice 3 left every connected `Repo` with `clone_status="pending"`, `clone_path=null`, and no sandbox bound to it. This slice introduces the **`Sandbox`** — the per-user Fly Sprite that will eventually host all of that user's connected repos under `/work/<full_name>/` — and the REST endpoints that spawn, hibernate, and destroy it.

This slice ends at "**the box exists**." It deliberately does **not** include WebSocket transport, the bridge runtime dialing home, repo cloning, or reconciliation. Those need a wire, and the wire lands in slice 5a; cloning lands in 5b. After this slice, a user can `POST /api/sandboxes` → `POST /api/sandboxes/{id}/wake` and watch their Sprite go to `running` in Fly's dashboard. Nothing more.

The point is to wire the provisioning path end-to-end on the simplest possible surface — provider impl, Mongo state, Redis hot cache, REST API, idle-hibernation job — so slice 5a can plug a real WS server into a working orchestrator-side state machine.

**Do not build features beyond this slice.** No WS endpoint, no bridge WS client, no clone, no reconciliation, no `Repo.sandbox_id` binding, no PTY, no file ops, no tasks.

---

## Calls baked in (push back if any are wrong)

> **Mid-slice rewrite (2026-05-01):** the brief was first drafted assuming Fly Sprites with a custom HTTP wrapper. After the user pointed at the real `sprites-py` SDK docs (rc43), the implementation was rewritten to use the SDK directly. The contract — "the box exists" — is unchanged; the env vars, provider impl, status enum, and several state-machine details are simpler than the original draft. The points below reflect the **post-rewrite** decisions.

1. **Sprites SDK** — `sprites-py` (latest rc on PyPI as of 2026-05-01 is `rc37`; rc43 docs at [`docs/sprites/v0.0.1-rc43/python.md`](../sprites/v0.0.1-rc43/python.md) describe the Python SDK and [`http.md`](../sprites/v0.0.1-rc43/http.md) the raw HTTP/WSS surface — same shape for everything slice 4 touches). Pinned `>=0.0.1rc37` with `[tool.uv] prerelease = "allow"` at the workspace root because the SDK ships only as rc tags. The SDK is the only Sprites import in the codebase; everything outside `python_packages/sandbox_provider/sprites.py` goes through the `SandboxProvider` Protocol with an opaque `SandboxHandle`.
2. **Region / resources / image** — **none of these are configured by us.** Sprites manages CPU/RAM/disk/region/image internally. We dropped the `FLY_REGION`, `SPRITE_CPU`, `SPRITE_RAM_MB`, `SPRITE_DISK_GB`, and `BRIDGE_IMAGE` env vars introduced in the first draft.
3. **Naming-collision strategy** — Sprite name is `vibe-sbx-{sandbox_id}` (sandbox_id is the Mongo `Sandbox._id`). On destroy we keep the Mongo doc with `status="destroyed"`; the next provision inserts a *new* `Sandbox` doc with a *new* ObjectId, so the Sprite name is unique by construction. **Reset reuses the same `Sandbox._id` and Sprite name** but the SDK assigns a fresh sprite UUID — `provider_handle.id` rotates while `provider_handle.name` stays the same.
4. **Filesystem persistence** — Sprites have a built-in persistent filesystem; we don't mount a volume. The filesystem survives auto-pause (Sprites' `cold` state) and explicit wake. It is destroyed by exactly two operations: `POST /api/sandboxes/{id}/reset` (replaced with fresh) and `POST /api/sandboxes/{id}/destroy` (not replaced).
5. **Redis schema** — three keys per active sandbox; Mongo is source of truth, Redis is hot cache only.
   - `sandbox:{sandbox_id}` — hash `{status, public_url, last_active_at}`. Refreshed on any state transition; **90s TTL**.
   - `sandbox:{sandbox_id}:owner` — string `instance_id`. **60s TTL** refreshed on heartbeat. For sticky-by-sandbox routing in slice 5a; written here so the schema is defined from the start.
   - `orchestrator_capacity:{instance_id}` — hash `{ws_connections, sandboxes_owned}`. **60s TTL**. For hot-shedding decisions in slice 5a.
   - **No queue keys yet.** `sandbox:{user_id}:queue` and `sandbox:{user_id}:active_run` land in slice 6.
6. **Sandbox doc creation timing — lazy.** `POST /api/sandboxes` is idempotent: returns the user's existing non-destroyed sandbox or creates one *and immediately calls `provider.create()`* if missing. (Sprites' SDK creates immediately and the sprite shows up `warm` right away — there's no separate `wake` step before the box exists.) The `Wake` button still exists as a UX nicety; internally it issues a no-op exec to force `cold → running`.
7. **Hibernate is gone.** Sprites auto-pauses on idle; there is no `PUT /sprites/{name}` API to force-pause. The `Pause` button from the first draft is removed. Users see the live Sprites status (`cold` ≡ "Paused"); a new `POST /api/sandboxes/{id}/refresh` resyncs status from Sprites without polling.
8. **Reset and Destroy are two distinct operations, not one button with a label tweak.** Reset wipes the filesystem + respawns a fresh sprite for the same `Sandbox` doc (preserves `_id`, increments `reset_count`, rotates `provider_handle.id`). Destroy fully tears down and marks the doc destroyed; the user must `Provision sandbox` to get a new one (with a new `_id`). Two separate API endpoints; two UI buttons with separate confirmation dialogs.
9. **Provider selection is explicit, not silent.** Env var `SANDBOX_PROVIDER ∈ {"sprites", "mock"}`, defaults to `sprites`. With `sprites`, an empty `SPRITES_TOKEN` aborts startup. With `mock`, the orchestrator boots and emits a `sandbox_provider.mock_in_use` warning every boot. **No silent fallback** when the token is empty.
10. **Idle-hibernation job — deleted.** Sprites does idle hibernation server-side; we don't run our own scan. The `SANDBOX_IDLE_MINUTES` env var is gone.
11. **Public URL** — Sprites ships every sandbox with `https://{name}-{org}.sprites.app`. We surface it on the dashboard; this absorbs slice 9's "HTTP preview proxy" requirement entirely.

---

## Context from slice 3

Slice 3 is signed off. Read it ([slice3.md](slice3.md)) before starting if you don't have it in conversation history. Key things now in place:

- `Repo` Beanie document at [../../python_packages/db/src/db/models/repo.py](../../python_packages/db/src/db/models/repo.py) has a `sandbox_id: PydanticObjectId | None` field. **Slice 4 leaves it None for every row.** Slice 5b is what actually binds it.
- `python_packages/sandbox_provider/src/sandbox_provider/` exposes only an empty Protocol stub at [interface.py](../../python_packages/sandbox_provider/src/sandbox_provider/interface.py). **You will fill it in.**
- `apps/orchestrator/src/orchestrator/lib/env.py` is `pydantic-settings`. **You will add new env vars** (`SPRITES_API_KEY`, `SPRITES_ORG`, `REDIS_URL`, `FLY_REGION`, `SPRITE_CPU`, `SPRITE_RAM_MB`, `SPRITE_DISK_GB`, `BRIDGE_IMAGE`).
- `python_packages/db/src/db/collections.py` has `Collections.SANDBOXES = "sandboxes"` reserved already. **You will add the `Sandbox` Document and register it in `_DOCUMENT_MODELS`** in [mongo.py](../../python_packages/db/src/db/mongo.py).
- `apps/orchestrator/src/orchestrator/middleware/auth.py` exports `require_user`. **Use it on every endpoint.**
- `packages/api-types/generated/schema.d.ts` is real. **You will regenerate it again at the end of this slice.**
- TanStack Router file routes live under `apps/web/src/routes/_authed/`. The dashboard at [../../apps/web/src/routes/_authed/dashboard.tsx](../../apps/web/src/routes/_authed/dashboard.tsx) is where the new sandbox status pill goes.
- Pyright strict and TS strict are the bar.
- Plan.md §10 and §18 were rewritten on 2026-05-01 to reflect the multi-WS architecture and the new slice split. **Read [Plan.md §13 (sandbox lifecycle)](../Plan.md#13-sandbox-lifecycle-slice-4) and [§18 slice 4 entry](../Plan.md#slice-4--sandbox-provisioning-the-box-exists) before starting.** §10 you can skim — the WS work is slice 5a.

---

## What "done" looks like

After this task, a signed-in user can:

1. Visit `/dashboard` and see a new "Sandbox" panel showing `none` (no sandbox yet) with a "Provision sandbox" button.
2. Click "Provision sandbox" → behind the scenes, `POST /api/sandboxes` creates a `Sandbox` doc with `status="none"`. The panel updates to show the doc id and a "Wake sandbox" button.
3. Click "Wake sandbox" → `POST /api/sandboxes/{id}/wake` calls `provider.spawn`. The panel transitions through `spawning` → `running`. The Fly dashboard shows a Sprite named `vibe-sbx-<sandbox_id>` in the `iad` region with a 20 GB volume mounted at `/work`.
4. Click "Pause" (UI label for hibernate — see §10b) → `POST /api/sandboxes/{id}/hibernate`. Panel shows `paused`. The Sprite in Fly is dormant (no compute charged). **The volume is preserved.**
5. Close the browser, walk away, sign back in tomorrow → the dashboard shows the same sandbox in `paused` state. Click "Resume" → `POST /api/sandboxes/{id}/wake`, the Sprite restarts with the *same volume* still mounted at `/work`. Anything written there before pause is still there.
6. Wait 10 minutes after a wake without any heartbeat → the idle-hibernation job auto-pauses. Panel updates on next refresh. User can resume on demand.
7. Click "Reset sandbox" (UI label for destroy — see §10b) → `POST /api/sandboxes/{id}/destroy`. The Sprite **and its volume** are gone; the Mongo doc is *kept* with `status="destroyed"` (audit trail). The panel shows "Sandbox reset" and the "Provision sandbox" button reappears (clicking creates a *new* `Sandbox` doc with a *new* id and a fresh volume).
8. Connected `Repo` rows (from slice 2/3) are unaffected by hibernate/wake/destroy — `clone_status` stays `"pending"`, `clone_path` stays `null` throughout. *Cloning is slice 5b.*

That is the entire user-facing scope. **No WS, no clone, no agent runs, no terminal.**

### State preservation contract

This contract is the load-bearing UX promise — a user must be able to walk away mid-session and come back to the same box. Document and uphold it from slice 4 onward.

| Action | Sprite | `/work` volume | `Sandbox` doc | `Repo` rows |
|---|---|---|---|---|
| `wake` (from `none` / `destroyed-then-new` / `paused`) | created or resumed | mounted (or freshly created) | mutated | unchanged |
| **idle-hibernation auto-fires** | stopped | preserved | `paused`, `hibernated_at` set | unchanged |
| `hibernate` (manual) | stopped | preserved | `paused`, `hibernated_at` set | unchanged |
| sign-out | unchanged | preserved | unchanged | unchanged |
| sign-in later | unchanged (likely `paused` by idle) | preserved | unchanged | unchanged |
| orchestrator restart | unchanged | preserved | unchanged | unchanged |
| `reset` | terminated then respawned | **dropped, then fresh empty** | **same `_id`**; `reset_count++`, `last_reset_at` set, `sprite_id` rotated | unchanged (slice 5b will flip `clone_status` back to `pending` so the bridge re-clones into the fresh volume) |
| `destroy` | terminated | **dropped** | `destroyed`, `destroyed_at` set | unchanged |
| disconnect repo (slice 2 endpoint) | unchanged | unchanged (clone removal is slice 5b) | unchanged | row deleted |

**The only volume-destroying action is explicit `destroy`.** Everything else preserves it. Slice 4 verifies this contract with the volume *empty* (no clones yet); slice 5b's clone work proves the same contract end-to-end with real data.

---

## What to build

### 1. New env vars + Settings — `apps/orchestrator/src/orchestrator/lib/env.py`

Add these fields to `Settings`:

```python
sandbox_provider: Literal["fly", "mock"] = Field(default="fly", alias="SANDBOX_PROVIDER")
sprites_api_key: str = Field(default="", alias="SPRITES_API_KEY")
sprites_org: str = Field(default="", alias="SPRITES_ORG")  # Fly org slug
fly_region: str = Field(default="iad", alias="FLY_REGION")
redis_url: str = Field(alias="REDIS_URL")
sprite_cpu: int = Field(default=2, alias="SPRITE_CPU")
sprite_ram_mb: int = Field(default=4096, alias="SPRITE_RAM_MB")
sprite_disk_gb: int = Field(default=20, alias="SPRITE_DISK_GB")
bridge_image: str = Field(alias="BRIDGE_IMAGE")            # OCI image ref for the bridge
sandbox_idle_minutes: int = Field(default=10, alias="SANDBOX_IDLE_MINUTES")
```

`SPRITES_API_KEY` and `SPRITES_ORG` default to empty so dev configs without them load — but `SANDBOX_PROVIDER=fly` (the default) refuses to start when they're empty (see §9). `SANDBOX_PROVIDER=mock` ignores them.

Update [.env.example](../../.env.example) with sensible placeholder values + a comment block explaining `BRIDGE_IMAGE` (slice 4 uses a no-op image; slice 5a swaps in the real bridge).

### 2. Beanie model — `python_packages/db/src/db/models/sandbox.py`

```python
from datetime import UTC, datetime
from typing import ClassVar, Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from db.collections import Collections


def _now() -> datetime:
    return datetime.now(UTC)


SandboxStatus = Literal[
    "none",         # doc exists, no Sprite has been spawned yet
    "spawning",     # provider.spawn in progress
    "running",      # Sprite is up; heartbeat fresh (slice 5a will populate heartbeat)
    "paused",       # Sprite is dormant; volume preserved. Was internally called
                    # "hibernated" in earlier drafts — renamed to match the UX
                    # promise that pause is non-destructive. The provider call
                    # is still `provider.hibernate` (Fly's term).
    "resuming",     # provider.resume in progress
    "resetting",    # reset in progress: tearing down current Sprite + volume
                    # before respawning. Same Sandbox doc; the row stays.
    "destroyed",    # Sprite + volume gone; doc kept for audit
    "failed",       # provider.spawn or .resume errored; needs manual reset/destroy
]


class Sandbox(Document):
    user_id: PydanticObjectId
    sprite_id: str | None = None         # Fly Sprite id; None until first spawn
    status: SandboxStatus = "none"
    region: str                          # Fly region; set at create time from Settings
    bridge_version: str | None = None    # populated by slice 5a's ClientHello
    last_active_at: datetime | None = None
    spawned_at: datetime | None = None
    hibernated_at: datetime | None = None
    destroyed_at: datetime | None = None
    last_reset_at: datetime | None = None
    reset_count: int = 0
    failure_reason: str | None = None    # set when status="failed"
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = Collections.SANDBOXES
        indexes: ClassVar[list[IndexModel]] = [
            # NOT unique — multi-sandbox forward-compat per Plan.md §4. v1
            # enforces "one running per user" at the orchestrator routing
            # layer (services/sandbox_manager.py), not here.
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("status", ASCENDING)]),  # for the idle-hibernation scan
        ]
```

Register in [`db/mongo.py`](../../python_packages/db/src/db/mongo.py)'s `_DOCUMENT_MODELS` list and add a `sandboxes` typed property. Add `Sandbox` to `db/collections.py` `ALL` tuple. Export from `db/models/__init__.py` and `db/__init__.py`.

### 3. Pydantic API models — `python_packages/shared_models/src/shared_models/sandbox.py`

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SandboxStatus = Literal[
    "none", "spawning", "running", "paused", "resuming", "resetting", "destroyed", "failed"
]


class SandboxResponse(BaseModel):
    id: str
    user_id: str
    sprite_id: str | None
    status: SandboxStatus
    region: str
    bridge_version: str | None
    last_active_at: datetime | None
    spawned_at: datetime | None
    hibernated_at: datetime | None
    destroyed_at: datetime | None
    last_reset_at: datetime | None
    reset_count: int
    failure_reason: str | None
    created_at: datetime
```

Export from `shared_models/__init__.py`. **No request bodies** — every endpoint in this slice is either path-only or empty body.

### 4. `SandboxProvider` Protocol + Fly impl — `python_packages/sandbox_provider/src/sandbox_provider/`

#### 4a. `interface.py` — replace the stub

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SpawnResult:
    sprite_id: str          # Fly's id for the spawned Sprite
    region: str             # actual region (Fly may have remapped)


class SandboxProvider(Protocol):
    """Sandbox provider abstraction. Slice 4 implements `FlySpritesProvider`
    + a `MockSandboxProvider` for tests/local. Slice 5b will add `clone_repo`
    + `remove_repo`; slice 6 will add `exec`. Don't broaden this protocol
    until those slices need it."""

    async def spawn(
        self,
        *,
        sandbox_id: str,
        env: dict[str, str],
        cpu: int,
        ram_mb: int,
        disk_gb: int,
        region: str,
        image: str,
    ) -> SpawnResult: ...

    async def resume(self, sprite_id: str) -> None: ...

    async def hibernate(self, sprite_id: str) -> None: ...

    async def destroy(self, sprite_id: str) -> None: ...

    async def status(self, sprite_id: str) -> str:
        """Return Fly's view of the Sprite ('running'|'stopped'|'destroyed'|...).
        Used by the idle-hibernation job and reconciliation in slice 5a."""
```

#### 4b. `fly.py` — new file

`FlySpritesProvider(api_key, org)` implementing the Protocol against the Fly Sprites HTTP API via `httpx.AsyncClient`. One method per Protocol method, each is one HTTP call plus error mapping. Wrap everything in a `_call_sprites(method, path, body) -> dict` helper for retry + error normalization.

Errors map to a single `SpritesError(message, retriable: bool)` exception type — let routes decide how to surface. **Do not** swallow Fly errors silently; the orchestrator's caller logs + flips `Sandbox.status="failed"`.

If the SDK exists as a real pypi package and is well-typed, swap the httpx implementation for SDK calls — but the wrapper boundary stays the same.

#### 4c. `mock.py` — new file

`MockSandboxProvider` that:
- `spawn()` returns a fake `SpawnResult(sprite_id=f"mock-{sandbox_id}", region=region)`. State tracked in a process-local dict.
- `resume`/`hibernate`/`destroy` mutate the dict, no-ops otherwise.
- `status()` returns whatever was last set.

This is what tests use and what local dev uses when `SPRITES_API_KEY` is empty. Surface the fallback in [services/sandbox_manager.py](#5-services-sandbox-manager) with a single conditional at provider-construction time.

#### 4d. `__init__.py`

Export `SandboxProvider`, `SpawnResult`, `SpritesError`, `FlySpritesProvider`, `MockSandboxProvider`.

### 5. Sandbox manager — `apps/orchestrator/src/orchestrator/services/sandbox_manager.py`

The orchestrator's *application-level* layer over the provider. Encapsulates the "v1 routing rule: one running sandbox per user" so it doesn't bleed into routes.

```python
class SandboxManager:
    def __init__(self, provider: SandboxProvider, redis: Redis): ...

    async def get_or_create(self, user_id: PydanticObjectId) -> Sandbox:
        """Return the user's sandbox (most recent non-`destroyed`), creating
        one with status='none' if none exists. Idempotent."""

    async def list_for_user(self, user_id: PydanticObjectId) -> list[Sandbox]:
        """All sandboxes for a user, including destroyed ones (audit trail)."""

    async def wake(self, sandbox: Sandbox) -> Sandbox:
        """Spawn (status='none'|'destroyed') or resume (status='hibernated').
        Atomic on Mongo state transition; rollback to 'failed' on provider error.
        Refuses (HTTP 409) if status is already in {'spawning','running','resuming'}."""

    async def hibernate(self, sandbox: Sandbox) -> Sandbox:
        """Pause the Sprite. Volume preserved. Status flips to 'paused'."""

    async def reset(self, sandbox: Sandbox) -> Sandbox:
        """Wipe and respawn. Tears down the current Sprite + volume, then
        spawns a fresh Sprite (new sprite_id, fresh empty volume) for the
        SAME Sandbox doc. The doc's _id is preserved — the user keeps the
        same logical sandbox, just with a clean filesystem.

        Status path: running|paused|failed → resetting → spawning → running.
        Records `reset_count` (incremented) and `last_reset_at` on the doc.
        """

    async def destroy(self, sandbox: Sandbox) -> Sandbox:
        """Tear down the Sprite + volume permanently. Mark doc 'destroyed'
        (kept for audit). The user must call get_or_create to provision a
        new sandbox — they get a NEW Sandbox doc with a NEW _id."""
```

State-transition rules (enforce in code; tests cover the matrix):

| from | wake | hibernate | reset | destroy |
|---|---|---|---|---|
| `none` | → `spawning` → `running` | 409 | 409 (nothing to reset) | 204 (no-op, mark `destroyed`) |
| `spawning` | 409 | 409 | 409 | 409 (must wait or `failed`) |
| `running` | 409 (already running) | → `paused` | → `resetting` → `spawning` → `running` | → `destroyed` |
| `paused` | → `resuming` → `running` | 409 (already paused) | → `resetting` → `spawning` → `running` | → `destroyed` |
| `resuming` | 409 | 409 | 409 | 409 |
| `resetting` | 409 | 409 | 409 | 409 |
| `destroyed` | 409 (caller should `get_or_create` a new doc) | 409 | 409 | 409 |
| `failed` | 409 (caller must `reset` or `destroy` first) | 409 | → `resetting` → `spawning` → `running` | → `destroyed` |

Redis side effects on every successful transition: write `sandbox:{id}` hash with `{sprite_id, status, last_active_at}` and TTL 90s. **Never read sandbox state from Redis as primary** — Mongo is the truth. Redis is for slice 5a's hot path.

### 6. Routes — `apps/orchestrator/src/orchestrator/routes/sandbox.py`

One module. Path-parameterized from day one (no `/api/sandbox/wake` shortcuts) so multi-sandbox post-v1 doesn't need a route rename.

- **`GET /api/sandboxes`** (auth required) — returns `list[SandboxResponse]` of all the user's sandboxes (including destroyed). Most-recent first.
- **`POST /api/sandboxes`** (auth required) — calls `manager.get_or_create(user.id)`. Idempotent: returns the user's existing non-destroyed sandbox or creates one. Returns `SandboxResponse`.
- **`POST /api/sandboxes/{sandbox_id}/wake`** (auth required) — verify ownership (404 otherwise), call `manager.wake(doc)`. Returns `SandboxResponse`. 409 on illegal state transition.
- **`POST /api/sandboxes/{sandbox_id}/hibernate`** (auth required) — same shape; 409 if not running.
- **`POST /api/sandboxes/{sandbox_id}/reset`** (auth required) — wipe the Sprite + volume and respawn fresh, **same `Sandbox` doc**. Returns `SandboxResponse` with `reset_count` incremented and the new `sprite_id`. 409 if status is in `{spawning, resuming, resetting, none, destroyed}`.
- **`POST /api/sandboxes/{sandbox_id}/destroy`** (auth required) — full teardown, mark doc `destroyed`. User must `POST /api/sandboxes` to provision a new sandbox doc. Idempotent on already-destroyed (200 with the existing doc).

Mount in `app.py`:

```python
app.include_router(sandbox.router, prefix="/api/sandboxes", tags=["sandboxes"])
```

**No DELETE for sandbox** — destroy is a state transition, not a hard delete. The doc is kept. (Distinct from disconnect-repo where the row is removed.)

### 7. Idle-hibernation job — `apps/orchestrator/src/orchestrator/jobs/hibernate_idle.py`

Periodic background task started from the FastAPI lifespan. Runs every **2 minutes**. Logic:

```python
cutoff = datetime.now(UTC) - timedelta(minutes=settings.sandbox_idle_minutes)
candidates = await Sandbox.find(
    Sandbox.status == "running",
    {"$or": [
        {"last_active_at": {"$lt": cutoff}},
        {"last_active_at": None, "spawned_at": {"$lt": cutoff}},
    ]},
).to_list()
for sandbox in candidates:
    try:
        await manager.hibernate(sandbox)
    except Exception:
        logger.warning("hibernate_idle.failed", ...)
```

Slice 4 only checks time-since-spawn (`last_active_at` is null because slice 5a populates it via heartbeat). **The job is correct from day one** because the fallback `spawned_at < cutoff` works without any heartbeat data.

Started/stopped from `app.py`'s lifespan via `asyncio.create_task` + cancellation on shutdown. **Cancel cleanly**: surface a `CancelledError` from the loop and let it propagate; don't swallow.

### 8. Redis client — `apps/orchestrator/src/orchestrator/lib/redis_client.py`

```python
import redis.asyncio as redis_asyncio

from .env import settings


class RedisClient:
    def __init__(self) -> None:
        self._client: redis_asyncio.Redis | None = None

    async def connect(self, url: str | None = None) -> None: ...
    async def disconnect(self) -> None: ...
    @property
    def client(self) -> redis_asyncio.Redis: ...

redis_client = RedisClient()  # process singleton, mirrors db.mongo's pattern
```

Lifecycle in `app.py`'s lifespan: connect on startup, disconnect on shutdown. Reuse the existing `redis>=5.0` dependency.

### 9. Provider construction — `apps/orchestrator/src/orchestrator/lib/provider_factory.py`

**Explicit selection — no silent fallback.** The provider is chosen by `SANDBOX_PROVIDER` env var with values `fly` (default) and `mock`. Falling back to mock just because `SPRITES_API_KEY` is empty is forbidden — it's a footgun that masks a misconfigured prod deploy.

```python
def build_sandbox_provider() -> SandboxProvider:
    match settings.sandbox_provider:
        case "fly":
            if not settings.sprites_api_key:
                raise RuntimeError(
                    "SANDBOX_PROVIDER=fly but SPRITES_API_KEY is empty. "
                    "Set the key, or set SANDBOX_PROVIDER=mock for local dev."
                )
            return FlySpritesProvider(
                api_key=settings.sprites_api_key,
                org=settings.sprites_org,
            )
        case "mock":
            logger.warning("sandbox_provider.mock_in_use",
                           hint="local dev only — never set SANDBOX_PROVIDER=mock in prod")
            return MockSandboxProvider()
```

`Settings.sandbox_provider: Literal["fly", "mock"] = Field(default="fly", alias="SANDBOX_PROVIDER")`. **No default value of "mock"**, ever. Local dev's `.env.example` ships with `SANDBOX_PROVIDER=mock` commented in alongside the Fly key — the developer makes a deliberate choice. Prod deploys must set `SANDBOX_PROVIDER=fly` (the default) AND a non-empty `SPRITES_API_KEY`; otherwise the orchestrator refuses to start. Ship a CI smoke check that asserts `SANDBOX_PROVIDER != "mock"` in prod manifests.

Construct once in `app.py`'s lifespan; inject into `SandboxManager` via FastAPI dependency.

### 10. Web — `apps/web/src/`

#### 10a. Queries / mutations — `apps/web/src/lib/`

- **`sandbox.ts`** (new): `listSandboxes`, `getOrCreateSandbox`, `wakeSandbox(id)`, `hibernateSandbox(id)`, `resetSandbox(id)`, `destroySandbox(id)`. Plain mutations + a `sandboxesQueryOptions` for the list.
- 409 on illegal transitions: surface as a typed `SandboxStateError` so the UI can show "already running" inline rather than treating it as a generic error.

#### 10b. Dashboard — `apps/web/src/routes/_authed/dashboard.tsx`

Add a **"Sandbox" section** above the existing repos section. The button labels use **user-facing language**, not the internal status names — see the mapping below.

| Internal status | UI label | UI controls shown |
|---|---|---|
| `none` (doc exists, never spawned) | "Sandbox provisioned" | **Start** (calls `wake`) · **Delete sandbox** (calls `destroy`) |
| no doc yet OR most recent is `destroyed` | "No sandbox yet" | **Provision sandbox** (calls `getOrCreateSandbox`) |
| `spawning` / `resuming` / `resetting` | "Starting…" / "Resuming…" / "Resetting…" | spinner; poll every 2s until terminal |
| `running` | "Running" | **Pause** (calls `hibernate`) · **Reset** (calls `reset`) · **Delete sandbox** (calls `destroy`) |
| `paused` | "Paused — your work is preserved" | **Resume** (calls `wake`) · **Reset** (calls `reset`) · **Delete sandbox** (calls `destroy`) |
| `failed` | "Sandbox failed to start" + `failure_reason` | **Reset** (calls `reset`) · **Delete sandbox** (calls `destroy`) |

Reset and Delete are **two different operations**. Make the difference unmissable:

- **Reset** wipes `/work` and respawns a fresh Sprite. The same `Sandbox` doc keeps its id (so all bookmarks, dashboard URLs, and slice-5b `Repo.sandbox_id` references stay valid). Repo connections remain; their clones (once slice 5b lands) re-flow into the fresh volume. Confirmation copy: *"Reset will wipe this sandbox's filesystem (cloned repos, installed packages, in-progress work) and give you a fresh one. Your repo connections are preserved and will re-clone automatically. The sandbox itself stays the same."*
- **Delete sandbox** tears down the Sprite + volume *and* marks the `Sandbox` doc as destroyed. The user has to `Provision sandbox` to get a new one (with a new id). Confirmation copy: *"Delete will fully tear down this sandbox. To use coding features again you'll need to provision a new one. (Use Reset instead if you just want a clean filesystem.)"*

Critical UX rules:

- **"Pause" is the primary control on a running sandbox.** "Reset" is a secondary action. "Delete sandbox" is **tertiary** — visually smaller, slightly muted, placed at the right edge of the controls or behind a "More actions" disclosure.
- **Both Reset and Delete require a confirmation dialog.** Reset's dialog reinforces *"your repo connections survive"*; Delete's dialog reinforces *"you'll have to provision a new sandbox"*. The buttons in each dialog use the same word as the action ("Reset" / "Delete sandbox") — never a generic "Confirm" — so the user can read the dialog's button alone and know what they're about to do.
- **"Pause" does not need confirmation.** It's non-destructive; the explicit messaging "your work is preserved" reinforces the contract.
- **Sign-out behaviour is not configurable in this slice** — sign-out leaves the sandbox in whatever state it's in (the idle job will pause it after 10 minutes regardless). Document this in the panel: a small subtitle on the running state reads "Auto-pauses after 10 min idle."

Light-mode palette per [AGENTS.md §2.8](../../AGENTS.md): primary CTA is `bg-black text-white`, secondary is `bg-white border border-gray-300`. Status pill colors: gray for `none`/`paused`/`destroyed`, gray-500 for `spawning`/`resuming`/`resetting`, gray-900 for `running`, red text (not red fill) for `failed`. **Neither Reset nor Delete is red** — both stay `bg-white border border-gray-300 text-gray-700`. The visual hierarchy is established by *position* and *size*, not by color, because color signals (red) tend to make users either ignore the buttons (banner blindness) or panic away from the safe one (Reset).

**Do not rebuild `dashboard.tsx`** beyond adding this section. Keep slice-3's introspection panel intact.

#### 10c. Polling

For non-terminal states (`spawning`/`resuming`), TanStack Query's `refetchInterval: 2000` while `data.status` is in `{"spawning","resuming"}`. Stop on terminal. Slice 5a will replace this poll with WS-pushed updates; for now polling is fine.

### 11. Tests — `apps/orchestrator/tests/`

`test_sandbox.py`:

- `GET /api/sandboxes` 401 without session, `[]` for fresh user, returns list after create.
- `POST /api/sandboxes` 401 without session, creates `none` doc on first call, returns the same doc on second call (idempotent), creates a new doc if the existing one is `destroyed`.
- `POST /api/sandboxes/{id}/wake`: happy path `none → spawning → running` with `MockSandboxProvider` patched. 404 for someone else's sandbox. 409 if status is already `running` (or `spawning`/`resuming`). Verifies Mongo `sprite_id`, `spawned_at` populated; Redis `sandbox:{id}` hash written.
- **Provider failure path**: when `MockSandboxProvider.spawn` raises `SpritesError("boom", retriable=False)`, `Sandbox.status` flips to `failed` with `failure_reason="boom"`, endpoint returns 502.
- `POST /api/sandboxes/{id}/hibernate`: happy path `running → paused`. 409 from any other state.
- `POST /api/sandboxes/{id}/reset`: happy path from `running` / `paused` / `failed` flips status `running|paused|failed → resetting → spawning → running`. **Same `_id`** in the response as before; **`reset_count` increments** (was 0, now 1, then 2 on a second reset); **`sprite_id` rotates** (different value before vs. after); `last_reset_at` populated. 409 from `none` / `destroyed` / `spawning` / `resuming` / `resetting`. Mock provider's destroy + spawn are both called once per reset (verify call order).
- `POST /api/sandboxes/{id}/destroy`: happy path from any non-destroyed state. Mongo doc kept with `status="destroyed"`, `destroyed_at` set. Idempotent on already-destroyed (200, no provider call). After destroy, `POST /api/sandboxes` creates a **new** doc with a different `_id`.
- **Reset vs destroy don't collide**: after a reset the sandbox is on the *same* `_id` and a fresh sprite; after destroy the sandbox is `destroyed` and `POST /api/sandboxes` returns a *new* `_id`. Test both paths back-to-back on one user.
- **State machine matrix**: parameterized test that for every (from_status, action) pair asserts the correct outcome (transition or 409) per the table in §5. `reset` is a separate column from `destroy`.
- **Single-active-per-user routing rule**: with one `Sandbox` already `running`, calling `POST /api/sandboxes` returns the existing doc, not a new one.
- **Provider-selection startup check**: spinning up `app.py` with `SANDBOX_PROVIDER=fly` and empty `SPRITES_API_KEY` raises at startup (FastAPI lifespan abort). With `SANDBOX_PROVIDER=mock` it boots and emits the `sandbox_provider.mock_in_use` warning log.

`test_hibernate_idle_job.py`:

- Seeds three sandboxes: one `running` with `spawned_at` 30 min ago, one `running` with `spawned_at` 1 min ago, one `hibernated` with `spawned_at` 30 min ago. Runs the job once. Asserts only the first transitioned to `hibernated`.
- Provider failure during the loop: one sandbox raises, the next still gets processed; the failure is logged.

`python_packages/sandbox_provider/tests/`:

- `test_mock.py` — exercise the state dict round-trip, double-spawn, etc.
- `test_fly.py` — the real Fly impl, but with `httpx_mock` fixture asserting the exact REST calls + error mapping. **No real Fly hits in tests.**

### 12. Regenerate API types

End of slice, with the orchestrator running (or via the `app.openapi()` dump trick from slice 3):

```bash
pnpm --filter @octo-canvas/api-types gen:api-types
```

Verify `schema.d.ts` exposes the five sandbox endpoints + `SandboxResponse`.

### 13. Docs

- Update [../agent_context.md](../agent_context.md) §"Sandbox model" — slice 4 specifics (lazy creation, no salt, **explicit `SANDBOX_PROVIDER` selection — no silent fallback**, reset vs destroy as two distinct operations). Add a gotcha: "Setting `SANDBOX_PROVIDER=fly` with empty `SPRITES_API_KEY` aborts startup with a clear error. Setting `SANDBOX_PROVIDER=mock` emits a `sandbox_provider.mock_in_use` warning every boot — never set `mock` in prod manifests, and CI must assert it."
- Update [../progress.md](../progress.md) slice-status row when shipping. Add followups discovered.
- Append a one-line entry to [../Contributions.md](../Contributions.md).
- This brief is editable while in flight; freeze on user sign-off.
- README needs a new "Setting up Fly Sprites (local dev)" subsection — include both `SANDBOX_PROVIDER=mock` (no Fly account needed) and `SANDBOX_PROVIDER=fly` (real Sprites) recipes. Make explicit that empty `SPRITES_API_KEY` does **not** silently swap to mock — the orchestrator will refuse to start.

---

## What's intentionally out of scope

- **No WebSocket endpoints, no bridge runtime, no `ClientHello`.** Slice 5a.
- **No cloning.** `Repo.clone_status` stays `"pending"`, `clone_path` stays `null`. Slice 5b.
- **No `Repo.sandbox_id` binding.** Slice 5b sets it at connect time once the bridge is up.
- **No reconciliation.** Slice 5b.
- **No queue keys in Redis** (`sandbox:{user_id}:queue`, `sandbox:{user_id}:active_run`). Slice 6.
- **No PTY, no file ops.** Slice 8.
- **No HTTP preview proxy.** Slice 9.
- **No bridge token issuance.** Slice 5a — the `BRIDGE_IMAGE` env var exists so the Sprite has *something* to boot, but the bridge process is a no-op in slice 4 (a `sleep infinity` or equivalent is acceptable).
- **No multi-region.** `Settings.fly_region` exists but is read-only in v1; user can't pick. Post-v1.
- **No "switch sandbox account" flow.** One sandbox per user, period.
- **No metrics/Sentry yet** — `logger.info` / `logger.warning` is the audit trail.

---

## Hard rules — do not violate

- **Do not ship a WS endpoint.** Anything WS-shaped goes to slice 5a. If the brief requires it, the brief is wrong; surface it.
- **Do not clone any repo.** No `git clone`, no `provider.clone_repo` calls, no `Repo.clone_status` mutations. Cloning is slice 5b.
- **Do not bind `Repo.sandbox_id`.** Leaving it null is correct for this slice.
- **Do not silently swallow provider errors.** Every `SpritesError` flips `Sandbox.status="failed"` with `failure_reason` populated and returns 502 to the caller (5xx because the *provider* failed, not the user). Tests cover this path.
- **Do not store the Sprites API key in cookies, logs, or API responses.** Only in `Settings.sprites_api_key`. Mock provider has nothing to hide; real provider's HTTP errors must be sanitized before logging (no API key in the URL, no token in error bodies).
- **Do not enforce single-sandbox-per-user at the Mongo index.** The compound unique index would break the multi-sandbox forward-compat (Plan.md §4). Enforcement is in `SandboxManager.get_or_create`, not the schema.
- **Do not destroy via `DELETE`.** State-transition POST. Hard-delete a `Sandbox` doc only via a future admin tool; not from this API surface.
- **Do not relax Pyright strict.** Targeted `# pyright: ignore[<rule>]` only for genuine third-party gaps (httpx response typing in some Fly responses).
- **Do not introduce a different sandbox provider.** Fly Sprites only in v1. If we later need AWS/GCP, we add a new Provider impl behind the same Protocol — never an `if cloud == "aws"` branch in routes.
- **Do not rebuild `dashboard.tsx`** beyond the new Sandbox section.

---

## Acceptance criteria

1. `pnpm typecheck && pnpm lint && pnpm test` all green.
2. `pnpm build` builds every workspace.
3. `uv sync --all-packages --all-extras` completes; `redis>=5.0` resolves.
4. `pytest python_packages/sandbox_provider` passes (mock + Fly with `httpx_mock`).
5. `curl http://localhost:3001/openapi.json` includes `/api/sandboxes`, `/api/sandboxes/{sandbox_id}/wake`, `.../hibernate`, `.../destroy`, and `SandboxResponse` as a referenced schema.
6. After `gen:api-types`, `schema.d.ts` reflects the above.
7. End-to-end manual run with `pnpm dev` and **`SANDBOX_PROVIDER=mock`** (with `SPRITES_API_KEY` empty):
   - Sign in → dashboard shows "Provision sandbox" CTA.
   - Click → status transitions `none`. Click "Start" → `spawning` → `running`. Mongo `Sandbox` doc shows `status="running"`, `sprite_id` set to a mock id, `spawned_at` populated, `reset_count=0`. Redis `sandbox:{id}` hash exists with TTL 90s.
   - Click "Pause" → `paused`. `hibernated_at` populated. Click "Resume" → `resuming` → `running`. Old `sprite_id` preserved (resume doesn't rotate it).
   - **Reset flow**: click "Reset" → confirm dialog → `resetting` → `spawning` → `running`. Confirm in Mongo: same `_id` as before, `reset_count=1`, `last_reset_at` populated, **`sprite_id` is different** (rotated). `Repo` rows untouched (clone state is slice 5b).
   - **Delete flow**: click "Delete sandbox" → confirm dialog → `destroyed`. `destroyed_at` populated. Old doc remains in Mongo. The "Provision sandbox" CTA reappears; clicking it creates a *new* `Sandbox` doc with a new `_id` and `reset_count=0`. Two docs now exist for the user — old destroyed, new fresh.
   - Wait 12 minutes after a wake without doing anything → idle-hibernation job auto-pauses.
8. End-to-end manual run with **`SANDBOX_PROVIDER=fly`** + a real `SPRITES_API_KEY` (where available): same flow, the Fly dashboard shows `vibe-sbx-<sandbox_id>` in `iad` with a 20 GB volume, transitioning through `started`/`stopped`/`destroyed`. After Reset, the Fly dashboard shows the *old Sprite is gone and a new one with the same name pattern but a new sprite id is up*; the old volume is gone, the new one is empty.
9. **Provider-selection misconfiguration**: starting the orchestrator with `SANDBOX_PROVIDER=fly` and empty `SPRITES_API_KEY` aborts at startup with a clear `RuntimeError`. Starting with `SANDBOX_PROVIDER=mock` emits the `sandbox_provider.mock_in_use` log warning. There is **no silent fallback**.
10. Two-user check: user A's sandbox is invisible to user B (`GET /api/sandboxes` for B returns `[]`), and B can't `wake`/`hibernate`/`reset`/`destroy` A's sandbox by guessing the id (404).
11. Pyright strict zero errors. TS strict zero errors.

---

## When done

Write a brief summary covering:

1. The state-machine implementation — anything subtle about how `wake` from `destroyed` interacts with `get_or_create` (whether a fresh doc is the responsibility of the caller or the manager).
2. Mock-vs-real provider handoff — what the dev experience actually feels like with `SPRITES_API_KEY` empty, and whether that surface is solid enough that slice 5a's bridge work can stay in mock-mode for most testing.
3. Idle-hibernation correctness in absence of heartbeats — does the `spawned_at`-based fallback fire for sandboxes that have been waked-then-idled, or only for never-active ones? Confirm.
4. Sprites SDK / REST API surprises (auth, regions remapped, async start, pricing weirdness) — anything that would change slice 5a's bridge boot path.
5. Decision points where this brief was ambiguous and you made a judgment call.
6. Confirm each acceptance criterion with command output or verified-behavior description.
7. Flag followups for v1.1 / later slices (e.g., disk-cap eviction job — that's slice 5b territory but the cap is set here).

Do not start slice 5a automatically. Wait for user review and approval.
