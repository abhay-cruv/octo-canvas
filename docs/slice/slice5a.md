# Slice 5a — Web ↔ orchestrator WS (control + events channel)

Slice 4 left us with sandboxes that can be created, paused, reset, destroyed — but everything happens over REST polling. This slice introduces the **first persistent connection** between the FE and the backend: `/ws/web/tasks/{task_id}`, a Pydantic discriminated-union event stream with `seq`-replay, heartbeat, and Redis pub/sub fan-out across orchestrator instances.

This slice ends at "**a web client can subscribe to a task's event stream, drop the connection, reconnect with `Resume{after_seq}`, and catch up.**" It deliberately does **not** include real agents, real tasks beyond a placeholder doc, real PTY, real file ops, or any user-visible task UI beyond a debug page.

The point is to bake in the wire — message shapes, seq-replay, heartbeat, reconnect, cross-instance fan-out — on the simplest possible content (test events injected via a dev-only endpoint). When slice 6 starts producing real agent events, they slot into a transport that has already been hardened.

**Do not build features beyond this slice.** No agent-runner. No `Task.repo_id` or `Task.run_status` fields. No real user-facing task page. No PTY broker (slice 8). No User Agent (slice 6b).

---

## Calls baked in (push back if any are wrong)

1. **Minimal `Task` and `AgentEvent` collections now.** Slice 6 owns the full surface; slice 5a needs *something* keyed by `task_id` to subscribe to.
   - `Task`: `_id`, `user_id`, `created_at`, `status: Literal["pending","running","completed","failed","cancelled"] = "pending"`. Nothing else. Slice 6 widens with `repo_id`, `prompt`, `current_run_id`, etc.
   - `AgentEvent`: `_id`, `task_id`, `seq` (monotonic per `task_id`), `payload: dict[str, Any]` (the discriminated union, stored as JSON), `created_at`. Slice 6 may widen with `run_id`, but `seq` is per-task in 5a so the WS subscriber doesn't need a `run_id` to do replay yet.
   - Both go in [python_packages/db/src/db/models/](../../python_packages/db/src/db/models/) and register in `_DOCUMENT_MODELS`. Add `Collections.TASKS` and `Collections.AGENT_EVENTS` to `ALL` (already declared in [db/collections.py](../../python_packages/db/src/db/collections.py)).
2. **Auth on the WS handshake = session cookie via `Depends(require_user)`.** FastAPI supports cookie-based deps on `WebSocket` the same way as `Request`. Reject with close code `4001` (auth) on no/bad session, `4003` (forbidden) when the user doesn't own the `Task`, `4004` (not found) when `task_id` doesn't exist.
3. **Wire protocol lives in `python_packages/shared_models/src/shared_models/wire_protocol/`** (the package already exists, empty). Two discriminated unions, both keyed on `type`:
   - `OrchestratorToWeb` — the events the FE consumes. Slice 5a defines: `StatusChangeEvent`, `SandboxStatusEvent`, `ErrorEvent`, `BackpressureWarning`, `Pong`, plus a slice-5a-only `DebugEvent { type: "debug.event", run_id: None, seq, message }` that the dev-inject endpoint emits. The full event taxonomy from [Plan.md §10.4](../Plan.md) lands incrementally in 6/6b/7/8 — declaring them all now would be dead code.
   - `WebToOrchestrator` — slice 5a defines: `Resume { after_seq }`, `Ping { nonce }`, `Pong { nonce }`. `SendFollowUp`, `CancelTask`, `RequestOpenPty` etc. land in their respective slices.
   - Schemas are Pydantic v2 with `Field(discriminator='type')`. Wrapper class `OrchestratorToWebMessage = TypeAdapter[OrchestratorToWeb]` for parsing/serializing.
4. **`seq` is monotonic per `task_id`, assigned at insert time.** Implementation: a Mongo `findOneAndUpdate` on a `seq_counters` collection (`{_id: task_id, next: int}`) with `$inc: {next: 1}` upsert. The returned `next` is the new event's `seq`. Atomic across instances. Cheaper than a per-task in-memory lock + safer under multi-instance.
5. **Replay reads from Mongo, not Redis.** `Resume { after_seq }` → `find({task_id, seq > after_seq}).sort([("seq", 1)])` → stream each as a frame, then flip into live mode (subscribe to Redis channel + forward). Mongo retains 24h hot per [Plan.md §10.6](../Plan.md); slice 10 adds S3 archive. Slice 5a does *not* implement the 24h cleanup job — flagged as a followup.
6. **Heartbeat: 30s tx + 90s rx-deadline.** Each side sends `Ping{nonce}` every 30s; the other side must reply `Pong{nonce}` within 90s of the last received frame *of any kind*. On timeout, close `1011`. Implementation: an `asyncio.create_task(heartbeat_loop(ws))` per connection plus a `last_rx_at` watchdog.
7. **Redis pub/sub topology — channel `task:{task_id}`.** Producer side: every event written to Mongo is also published to Redis on `task:{task_id}` with the JSON-serialized payload. Subscriber side: each orchestrator instance lazily subscribes to the channel on **first** local web subscriber for that task, unsubscribes on **last**. Single `redis.asyncio.client.PubSub` per instance, multiplexing all channels — not one PubSub per task. A small `TaskFanout` class in `services/task_fanout.py` owns this.
8. **Backpressure — 1000-event buffer per (task, web subscriber).** If the FE's WS write queue overflows: drop intermediate events, advance `last_seq_sent`, emit `BackpressureWarning { last_dropped_seq }`. The FE's reconnect logic catches up via `Resume`. Implementation: per-subscriber `asyncio.Queue(maxsize=1000)`; `put_nowait` with `QueueFull` → drop + warn.
9. **Dev-only inject endpoint — `POST /api/_internal/tasks/{task_id}/events`.** Body: `{type: "debug.event", message: str}`. Gated on `settings.allow_internal_endpoints` (defaults `True` in dev, `False` in prod via env). Writes to Mongo via the same `append_event` path the real producers will use; that path also publishes to Redis. The endpoint requires session auth and ownership (same as the WS).
10. **Frontend: `useTaskStream(taskId)` hook + debug page `/_authed/tasks/$taskId`.** The hook owns the WS lifecycle: open, send `Resume{after_seq}` on (re)connect, manage heartbeat, jittered exponential backoff (1s → 2s → 4s → 8s → 16s, capped + ±25% jitter). The debug page renders the live event log + a "Force disconnect" button (closes the WS to test reconnect) + an "Inject event" button hitting the internal endpoint. **No styling polish** — this is a developer page, not a user feature.
11. **Cross-instance test in CI is best-effort.** True multi-instance acceptance needs `docker compose` with two orchestrator services + shared Redis. Slice 5a ships a `pytest` test that spins up two `TaskFanout` instances against a real Redis (via a fixture) and asserts B's local subscriber receives A's published event. The "two real orchestrator processes" test is documented as a manual smoke step.

---

## Context from slice 4

Slice 4 is signed off. Read it ([slice4.md](slice4.md)) before starting if you don't have it in conversation history. Key things now in place:

- `python_packages/shared_models/src/shared_models/wire_protocol/` exists but is empty (just `__init__.py`). **You will fill it in.**
- `apps/orchestrator/src/orchestrator/ws/` exists but is empty. **You will add `web.py` and `task_fanout.py` here.** (`task_fanout.py` could equally live in `services/`; placing under `ws/` keeps WS plumbing co-located.)
- Redis is connected in the lifespan ([apps/orchestrator/src/orchestrator/app.py](../../apps/orchestrator/src/orchestrator/app.py)) and the `redis_client` singleton is available. Pub/Sub uses `redis_client.client.pubsub()`.
- `db.Collections.TASKS` and `db.Collections.AGENT_EVENTS` constants already exist; `ALL` does **not** yet include them. **You will append them.**
- `apps/orchestrator/src/orchestrator/middleware/auth.py:require_user` is the auth dep. **Use it on the WS handshake.**
- Pyright strict + TS strict + `noUncheckedIndexedAccess` are the bar.
- `pnpm --filter @octo-canvas/api-types gen:api-types` regenerates [packages/api-types/generated/schema.d.ts](../../packages/api-types/generated/schema.d.ts) — run at the end. It only covers REST; **the WS message types must also be exported as TS** via a separate codegen step.
- **WS-message TS codegen.** Add a one-shot script `scripts/gen-wire-types.py` in the orchestrator app (or `python_packages/shared_models`) that dumps the wire-protocol Pydantic models as JSON Schema, then run `pnpm dlx json-schema-to-typescript` to produce `packages/api-types/generated/wire.d.ts`. Wired into `pnpm --filter @octo-canvas/api-types gen:api-types`. Engineering decision: the alternative (re-using `openapi-typescript` by exposing a fake REST endpoint that returns the schemas) is hackier — direct JSON-Schema → TS is cleaner.

---

## What "done" looks like

After this slice, a developer can:

1. Sign in.
2. Visit `/_authed/tasks/$taskId` for a `Task` they own → page connects to the WS, shows "connected, last_seq=0".
3. Click "Inject event" 5 times → 5 `DebugEvent` rows appear in the page log, `last_seq=5`.
4. Click "Force disconnect" → page shows "reconnecting in 1.2s..." → reconnects → `Resume{after_seq=5}` is sent → no replay (no new events) → live mode.
5. Open a second tab on the same task → also shows `last_seq=5` (full replay from Mongo).
6. From a second terminal, `curl -X POST .../api/_internal/tasks/$taskId/events ...` → both tabs show the new event (cross-tab fan-out via Redis on the same instance, single-instance OK for 5a's primary acceptance).
7. Forced manual smoke (not in CI): two orchestrator processes on different ports, FE on instance A, curl to instance B → A receives B's event via Redis pub/sub.
8. `pnpm typecheck && pnpm lint && pnpm test && pnpm build` and orchestrator pytest all green.

A user who is NOT signed in:

- Hits the WS without a session cookie → close `4001`.
- Signs in as user X, tries to subscribe to user Y's task → close `4003`.
- Subscribes to a non-existent `task_id` → close `4004`.

---

## What to build

### 1. Wire protocol — `python_packages/shared_models/src/shared_models/wire_protocol/`

Three files:

- `events.py` — `OrchestratorToWeb` discriminated union: `StatusChangeEvent`, `SandboxStatusEvent`, `ErrorEvent`, `BackpressureWarning`, `Pong`, `DebugEvent`. Each has `type: Literal["..."]`, plus `seq: int` where applicable (system messages like `Pong` skip `seq`).
- `commands.py` — `WebToOrchestrator` discriminated union: `Resume`, `Ping`, `Pong`.
- `__init__.py` — re-export both unions + a `OrchestratorToWebAdapter = TypeAdapter[OrchestratorToWeb]` and `WebToOrchestratorAdapter = TypeAdapter[WebToOrchestrator]` for serialize/parse on the wire.

Every field is annotated; Pydantic v2 strict; no `Any` except `DebugEvent.message: str`. Pyright-clean.

### 2. New Beanie models — `python_packages/db/src/db/models/`

- `task.py` — `Task` document. Fields per §1 above.
- `agent_event.py` — `AgentEvent` document. Index on `(task_id, seq)` ascending, unique. Plus an index on `(task_id, created_at)` for time-range queries (the 24h cleanup job's read path).
- `seq_counter.py` — `SeqCounter` document. `_id: PydanticObjectId` (= task_id), `next: int = 0`. Used by `append_event` for atomic seq allocation.

Register all three in `_DOCUMENT_MODELS` in [db/mongo.py](../../python_packages/db/src/db/mongo.py). Append `TASKS`, `AGENT_EVENTS`, `SEQ_COUNTERS` to `ALL` in [db/collections.py](../../python_packages/db/src/db/collections.py) (note: `SEQ_COUNTERS` is new; add the constant). Add typed accessors `mongo.tasks`, `mongo.agent_events`, `mongo.seq_counters`.

### 3. Event store — `apps/orchestrator/src/orchestrator/services/event_store.py`

```python
async def append_event(
    task_id: PydanticObjectId,
    payload: OrchestratorToWeb,
    *,
    redis: Redis,
) -> AgentEvent:
    """Allocate next seq atomically, insert event, publish to Redis."""
```

Implementation:
1. `seq = await SeqCounter.find_one_and_update({_id: task_id}, {"$inc": {"next": 1}}, upsert=True, return_document=AFTER)["next"]`.
2. Insert `AgentEvent(task_id=task_id, seq=seq, payload=payload.model_dump(mode="json"), created_at=now())`.
3. `await redis.publish(f"task:{task_id}", payload.model_dump_json())`.
4. Return the inserted event.

### 4. Fanout — `apps/orchestrator/src/orchestrator/ws/task_fanout.py`

`TaskFanout`: per-instance singleton. Owns one `redis.asyncio.client.PubSub`. API:
- `async subscribe(task_id, queue: asyncio.Queue) -> int` — registers the queue; if first subscriber for that task, calls `pubsub.subscribe(channel)`. Returns subscriber id (for unsubscribe).
- `async unsubscribe(task_id, subscriber_id) -> None` — drops the queue; if last subscriber, calls `pubsub.unsubscribe(channel)`.
- Private `async _reader_task()` — `async for msg in pubsub.listen()`, fan out to all queues for that channel via `put_nowait` (drop + emit `BackpressureWarning` on `QueueFull`).

Started/stopped via lifespan: `app.state.task_fanout = TaskFanout(redis); await fanout.start()` in lifespan, `await fanout.stop()` in shutdown.

### 5. WS handler — `apps/orchestrator/src/orchestrator/ws/web.py`

`@router.websocket("/ws/web/tasks/{task_id}")`. Flow:

1. `await websocket.accept()` (after auth — actually FastAPI lets you accept-then-close-on-fail or close pre-accept; we close pre-accept on 4001/4003/4004).
2. Resolve `User` via cookie. Reject 4001 if missing.
3. `Task.get(task_id)`. Reject 4004 if missing, 4003 if `task.user_id != user.id`.
4. Receive first frame, must be `Resume{after_seq}`. (Schema-mismatch → close 4400.)
5. Stream replay: `AgentEvent.find({task_id, seq > after_seq}).sort([("seq", 1)])`. Convert each to its discriminated union via `OrchestratorToWebAdapter.validate_python(event.payload)`, send.
6. Subscribe to fanout. Spawn three concurrent tasks with `asyncio.TaskGroup`:
   - `pump_outbound`: drain queue → `ws.send_json`, drop+warn on backpressure.
   - `read_inbound`: `ws.receive_json` → parse `WebToOrchestrator`. Handle `Ping` (reply `Pong`), `Pong` (reset rx watchdog), `Resume` (re-replay; rare but legal).
   - `heartbeat`: every 30s send `Ping{nonce=uuid4()}`. Track `last_rx_at`; if `now - last_rx_at > 90s`, raise `HeartbeatTimeout`.
7. On any task exit: cancel siblings, unsubscribe fanout, close WS with appropriate code.

### 6. Internal inject endpoint — `apps/orchestrator/src/orchestrator/routes/internal.py`

`POST /api/_internal/tasks/{task_id}/events`. Body `{message: str}`. Gated on `settings.allow_internal_endpoints` (404 otherwise). Auth + ownership same as WS. Calls `event_store.append_event(task_id, DebugEvent(seq=0, message=...))` (the actual seq is assigned by `append_event`, the input value is ignored — note the API quirk in the docstring).

Add `allow_internal_endpoints: bool = Field(default=True, alias="ALLOW_INTERNAL_ENDPOINTS")` to `Settings`. Set `ALLOW_INTERNAL_ENDPOINTS=false` in any prod env.

### 7. Test helpers — `apps/orchestrator/tests/conftest.py`

- Existing fixtures continue to work.
- New fixture `make_task(user)` — inserts a `Task` with the given `user._id`, returns it.
- New fixture `task_event_subscriber(task_id, after_seq=0)` — async context manager that opens a WS via `httpx_ws` (or `starlette.testclient.TestClient.websocket_connect`), authenticates via test session cookie, sends `Resume`, yields the WS for assertions.

### 8. WS-message TS codegen — `python_packages/shared_models/scripts/gen_wire_schema.py`

Dumps the two `TypeAdapter`s as JSON Schema to stdout. Pipe into `pnpm dlx json-schema-to-typescript` from `packages/api-types/`'s `gen:api-types` script (extend it). Output: `packages/api-types/generated/wire.d.ts`.

### 9. Frontend — `apps/web/`

- `src/lib/wire.ts` — re-exports types from `@octo-canvas/api-types/generated/wire.d.ts`.
- `src/hooks/useTaskStream.ts` — connect, replay, heartbeat, reconnect with jittered backoff. Returns `{events, status: "connecting"|"live"|"reconnecting"|"closed", lastSeq, forceDisconnect()}`.
- `src/routes/_authed/tasks/$taskId.tsx` — debug page per §11 above.

### 10. Docs

- [docs/progress.md](../progress.md) — slice 5a row → in flight.
- [docs/Contributions.md](../Contributions.md) — entry for slice 5a kickoff (added at end of session, not now).
- [docs/agent_context.md](../agent_context.md) — when this slice ships, update status line to "Slices 0–5a shipped" and note the WS leg is now live.
- This file (slice5a.md) is frozen on sign-off.

---

## Out of scope (explicit)

- Real agent runs and the full event taxonomy from [Plan.md §10.4](../Plan.md). Slice 6+.
- `SendFollowUp`, `CancelTask` web→orchestrator messages. Slice 6.
- PTY broker `/ws/web/sandboxes/{id}/pty/{terminal_id}`. Slice 8.
- File-watch event coalescing (`fs/watch` → `FileEditEvent`). Slice 8.
- 24h-Mongo / S3-cold archive cutover. Slice 10.
- User Agent (`PromptEnhancedEvent`, `AgentAnsweredClarification`, `OverrideAgentAnswer`). Slice 6b.
- Hot-shedding above the per-instance soft cap (5000 WS / 200 Exec sessions). Wire counters into Redis hash now? **No** — premature; add when slice 6 makes the cap meaningful.
- Real cross-instance acceptance test in CI. Documented as a manual smoke step instead.

---

## Risks

1. **Discriminated-union evolution.** Adding a new event variant in slice 6 must not break old web clients. Pydantic v2 + TypeAdapter validates strictly — set `model_config = ConfigDict(extra="ignore")` on the union members so older FE versions ignore unknown fields gracefully. Document in [engineering.md](../engineering.md) on first slice-6 schema change.
2. **`seq` collision under concurrent inserts.** The `find_one_and_update` upsert pattern is atomic in Mongo. Verified by an explicit test (100 concurrent `append_event` calls → seq is exactly 1..100, no gaps, no dupes).
3. **Redis pub/sub message loss.** Pub/Sub is fire-and-forget — if the orchestrator isn't subscribed when an event is published, it's gone. Mitigation: Mongo is the canonical store; pub/sub is the live fan-out. A subscriber that misses a message catches up on next reconnect via `Resume`. Risk only matters if a *currently-connected* subscriber misses a message — that requires the subscriber's instance to lose its pubsub connection mid-flight. Mitigation: `TaskFanout._reader_task` reconnects pubsub on error and replays the bucket of seqs it had on file before the error to all current subscribers.
4. **WS handshake auth has no `Depends` parity with HTTP routes.** FastAPI does support cookie deps on `WebSocket`, but the failure path is "close, don't HTTPException." Wrap `require_user` semantics in a `_resolve_user_for_ws(websocket)` helper.
5. **Heartbeat tax under load.** 5000 WS connections × 30s ping = ~166 pings/s outbound. Trivial for a single instance, but the rx-deadline watchdog must not allocate per tick. Track `last_rx_at` as a single mutable on the connection state, check in the heartbeat loop's existing 30s tick (not its own task).
6. **Reconnect storms.** A backend deploy disconnects every WS at once; if every FE retries at exactly 1s, we get a thundering herd. Mitigation: ±25% jitter from frame 0 (not just from frame 2 onward).
7. **`useTaskStream` re-fires on every render.** Standard React hook hazard. Use `useEffect([taskId])` and a ref-stable WS instance; no recreate on parent re-render.

---

## Acceptance — copy-paste checklist

- [ ] `pnpm typecheck` clean.
- [ ] `pnpm lint` clean.
- [ ] `pnpm --filter @octo-canvas/api-types gen:api-types` regenerates `wire.d.ts` and `schema.d.ts`; both committed; `pnpm typecheck` still clean.
- [ ] `uv run pytest apps/orchestrator/tests/` clean. New tests cover:
  - happy-path: subscribe, inject 5 events via internal endpoint, all 5 arrive in order with seq 1..5.
  - replay: subscribe with `after_seq=3`, only events 4 and 5 arrive.
  - reconnect: drop WS mid-stream, reconnect with `Resume{after_seq=last_seen}`, no duplicates, no gaps.
  - auth: no-cookie → 4001, wrong-user → 4003, missing-task → 4004.
  - seq concurrency: 100 concurrent `append_event` calls → seqs exactly 1..100.
  - cross-instance fan-out (in-process simulation): two `TaskFanout` instances against a single Redis → B's subscriber receives A's published event.
  - backpressure: subscriber queue fills → `BackpressureWarning` emitted, `last_dropped_seq` correct.
  - heartbeat: missed pong for 90s → server closes 1011.
- [ ] Manual smoke in browser: debug page reconnects after Force Disconnect, second tab catches up via replay.
- [ ] Manual smoke (multi-instance): two orchestrator processes on different ports + shared Redis; FE on instance A receives event injected via curl to instance B.
- [ ] [docs/progress.md](../progress.md) row updated.
- [ ] [docs/Contributions.md](../Contributions.md) entry added.
- [ ] [docs/agent_context.md](../agent_context.md) status line updated.
- [ ] User signs off → this brief is frozen; corrections live in `progress.md`.
