# Slice 8 — Chats + Bridge + `claude` CLI driven by `claude-agent-sdk` (passthrough)

The first slice that makes the agent actually run. Builds on slice 6 (the IDE shell — filesystem panel, file editor, terminal) and slice 7 (sprite image bake — Node + `claude` CLI binary + bridge wheel; runtime install via nvm/pyenv/etc). The dummy agent panel from slice 6 becomes a real chat surface: a user opens a Chat, the agent inside the sandbox writes code on a branch, the user chats follow-ups, and the bridge keeps the CLI alive across messages.

The runtime is **`claude` (Claude Code CLI)** baked into the Sprite image (slice 7), **driven by `claude-agent-sdk`**, **supervised by a long-lived `bridge` Python process** that dials home to the orchestrator over a single WSS. `Chat ↔ Claude session 1:1` (a Chat is one Claude Code session, one branch, eventually one PR). A sandbox hosts **many concurrent Chats**; the user can switch between them. The bridge multiplexes all of a sandbox's chats over one WSS.

**Architectural pivot from earlier drafts.** Old plan said "agent invocation = `provider.exec_oneshot(['python', '-m', 'agent_runner', task_json])` per run; parse JSON-lines off stdout." Discarded — Claude Code is a long-lived process with on-disk session state and `--resume` semantics; subprocess-per-run pays cold-start + cache-miss every turn and gives us no message-level idempotency. The bridge daemon (deleted in the slice-4 rewrite) is back, owning the WSS leg, the CLI subprocesses, and the in-process MCP server. See [Plan.md §14](../Plan.md), [§10.4b](../Plan.md), [§10.7](../Plan.md), [§14.7](../Plan.md).

**Renamed unit-of-work**: what earlier drafts called `Task` is now `Chat`. A `Chat` is a single Claude Code conversation, a single branch (`octo/chat-<slug>`), and (slice 9) a single PR. Many Chats per sandbox; the user picks which one to send to.

This slice ends at "**a user opens a Chat → bridge spawns a CLI session → agent edits files (visible live in the slice-6 file tree + editor) → user sends follow-ups → CLI stays alive across messages → multiple chats run side-by-side and the user switches between them.**" It deliberately does **not** include the User Agent (slice 8b), git push / PR-open (slice 9), bridge-token rotation as a real ops endpoint, or User-API-key / OAuth credential modes (reserved by Protocol; not implemented).

**Do not build features beyond this slice.** No User Agent. No prompt enhancement. No `AgentAnsweredClarification`/`OverrideAgentAnswer`. No git push. No PR creation. No HTTP preview proxy beyond Sprites' built-in URL. The IDE shell — file tree, editor, terminal — is **already shipped by slice 6**; the sprite image with Node + CLI + bridge wheel is **already shipped by slice 7**; this slice only adds the chat panel wiring and the bridge runtime behind it.

---

## Calls baked in (push back if any are wrong)

1. **`Chat ↔ Claude session 1:1`.** New `Chat` doc per [Plan.md §8](../Plan.md) (replaces the slice-5a `Task` stub conceptually; we ship a one-time rename in this slice). `Chat.claude_session_id: str | None` — null until the first SDK turn completes; the SDK assigns it; subsequent messages reuse the same id. Each user message creates a `ChatTurn` row but they all share the chat's session id. Branch is also 1:1 with chat: `octo/chat-<slug>` (slug = 8 chars of `chat_id`). The user can have **many chats open** per sandbox (no per-repo cap; two chats on the same repo use git **worktrees** — see #12 below).
2. **CLI stays alive while the user is connected; we do NOT kill on idle.** The bridge keeps the `claude-agent-sdk` `ClaudeAgentClient` open between user messages — follow-ups feed text directly to the live SDK client (no `--resume`, no cache miss). `--resume` is the cold-path fallback used only when the CLI process is gone. Per-session liveness state machine:

   ```
   none ─► cold ─► warming (--resume) ─► live ─► live (next message: direct feed)
                       ▲                 │
                       │                 ▼
                       └────────  cold (process gone)
   ```

   Triggers that move `live → cold` (the CLI is killed and the JSONL on disk is the only state):
   - All web subscribers for this `Chat` disconnect AND the `IDLE_AFTER_DISCONNECT_S = 300` (5 min) grace timer fires. Reconnecting within the grace window keeps `live`.
   - The user explicitly closes / archives the Chat.
   - Hard cap reached: `MAX_LIVE_CHATS_PER_SANDBOX = 5` (env-tunable). LRU `cold`-eligible chat is evicted *only* if it has no live web subscriber. If all 5 have subscribers, new chat creation queues with a `BackpressureWarning{kind:"chat_cap_reached"}` until one disconnects.
   - Sprite hibernation (sandbox-wide event) — bridge SIGTERM handles this cleanly.
   - Crash / OOM (involuntary).

   Triggers that do **not** kill the CLI:
   - User idle in a connected web tab (no message for hours). Connected = alive.
   - Brief WSS flap with reconnect inside grace.

   Per-chat dispatch decision in the bridge:
   ```python
   if chat.proc is not None and chat.proc.is_alive():
       await chat.proc.send(UserMessage(text=...))    # direct feed; cache stays warm
   else:
       chat.proc = await self.spawn(resume=chat.claude_session_id)  # cold path
       await chat.proc.send(UserMessage(text=...))
   ```

   `Chat.dispatch_mode` is **derived** state, not stored — the bridge inspects `proc.is_alive()` per send. We do persist `Chat.last_alive_at` and `Chat.cold_since_at` for debugging + UI hints.
3. **One bridge↔orchestrator WSS per sprite, multiplexing all sessions.** Endpoint `/ws/bridge/{sandbox_id}`. Bridge dials home; orchestrator never opens. Auth: `Authorization: Bearer ${BRIDGE_TOKEN}` minted at sprite provision time, persisted as `Sandbox.bridge_token_hash` (sha256). All inbound/outbound frames (except `Hello`/`Goodbye`/`Ping`/`Pong`) carry `session_id`. Wire schema: Pydantic discriminated union in `python_packages/shared_models/src/shared_models/wire_protocol/bridge.py` per [Plan.md §10.4b](../Plan.md). `seq` is per `(sandbox_id, session_id)`.
4. **Bridge owns ring-buffer replay.** 1000 frames or 1 MB per session, whichever smaller. On WSS reconnect: `Hello{last_acked_seq}` → orchestrator replies with the last `seq` it has in Mongo for that session and what state to converge to (`SessionState[]`). Bridge re-emits any frames with `seq > orchestrator_last_seq`. Inbound commands are idempotent on `frame_id` (uuid4 from orchestrator).
5. **Cross-instance bridge ownership via Redis.** Bridge connects to whichever orchestrator instance Fly's LB picks; that instance writes `bridge_owner:{sandbox_id} = {instance_id, expires_at}` (TTL 60s, refreshed every 20s). Other instances forward outbound commands (`UserMessage`, `AnswerClarification`, `Cancel`, `Pause`) via Redis pub/sub on `bridge_in:{sandbox_id}`. Inbound bridge events publish to `task:{task_id}` (looked up via `session_id → task_id` from `SessionStarted`). Mongo is canonical.
6. **`ClaudeCredentials` is a Protocol; v1 ships only `PlatformApiKeyCredentials`.** `User.claude_auth_mode: Literal["platform_api_key","user_oauth","user_api_key"] = "platform_api_key"` is added in this slice (§8 schema migration) but is hard-coded to `platform_api_key`; UI to flip it is post-v1. The Protocol lives at `python_packages/agent_config/src/agent_config/credentials.py`.

   **Anthropic key NEVER enters the sprite (slice-7 invariant; slice 8 honors it).** The user has terminal + agent-Bash access inside the sprite, so anything in process env / `/proc/<pid>/environ` is presumed leaked. The bridge talks to api.anthropic.com via the orchestrator's reverse proxy at `/api/_internal/anthropic-proxy/{sandbox_id}/{path:path}` (built in this slice — see "What to build" §3a). Env piped to the bridge from `BridgeRuntimeConfig.env_for(sandbox_id, bridge_token)`:
   - `CLAUDE_CODE_API_BASE_URL = <orch>/api/_internal/anthropic-proxy/<sandbox_id>` (priority var the CLI v2.1.118 checks first)
   - `ANTHROPIC_BASE_URL = <same>` (fallback for older CLI builds + the SDK)
   - `ANTHROPIC_AUTH_TOKEN = <bridge_token>` (Bearer mode; takes priority over `ANTHROPIC_API_KEY` which we deliberately omit)

   The proxy validates `Authorization: Bearer <bridge_token>` (sha256 + `hmac.compare_digest` against `Sandbox.bridge_token_hash`), strips it, sets `x-api-key: <real_key>` outbound, reverse-proxies streaming to api.anthropic.com. Async-correctness contract is in [slice7.md #6b](slice7.md) — must be honored verbatim. The reserved `SessionEnv` WSS frame (orchestrator → bridge) is declared in the wire schema but unused in v1 — path for user-scoped credentials in future modes (still proxied; they swap a different upstream auth).
7. **CLI tools = built-ins, plus one custom MCP tool.** Built-in: `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`. Custom (registered via in-process MCP server): `ask_user_clarification(question, context?) -> str`. **No `read_file`/`write_file`/`apply_patch`/`run_shell` re-implementations** — that was the old subprocess-per-run design. Permission mode: `acceptEdits`. Hooks:
   - `PreToolUse[Bash]` — parse the command; reject `cd /etc`, paths outside `/work/<repo>/`, `git push` to base branch, `rm -rf /` patterns. Cap wall-clock at 5 min, output at 50 KB.
   - `PreToolUse[Write|Edit]` — reject paths outside the session's repo subdir.
   These hooks are bridge-side, run in the SDK callback, return `{"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "..."}}` to block.
8. **`AskUserClarification` is in-process, not stdio.** The MCP tool implementation creates an `asyncio.Future` keyed by `clarification_id`, sends `AskUserClarification` over WSS, awaits the future. Orchestrator routes per [Plan.md §14.3](../Plan.md). 5-min timeout → `ErrorEvent{kind:"clarification_timeout"}` and abort the run. No stdin parsing, no sentinel lines.
9. **Token usage** is read off each `ResultMessage.usage` from the SDK and emitted as `TokenUsageEvent{input_delta, output_delta}`. Per-chat budget defaults `Chat.token_budget_input=1_000_000`, `token_budget_output=500_000` — slice 8 emits warning events at 80%; **hard cut-off lands in slice 8b** (when User Agent's spend cap also lands).
10. **Sprite image bake is slice 7's job, not this slice.** Slice 7 owns the Dockerfile and bakes Node ≥ 20, the pinned `claude` CLI, the bridge wheel, and runtime managers (nvm/pyenv/etc). This slice **assumes** the image is ready and consumes its outputs (the `claude` binary on PATH, `python -m bridge.main` as the entrypoint, `Hello.bridge_version` reflecting the baked CLI version). If you find yourself editing the Dockerfile here, push it back into slice 7.
11. **`AgentEvent` widening + `Task → Chat` rename.** Slice 5a's `AgentEvent` carries `task_id, seq, payload, created_at`; slice 8 renames `task_id → chat_id` and adds `claude_session_id: str | None` (null on `DebugEvent`-class rows that aren't session-scoped). Index changes to `(chat_id, claude_session_id, seq)`. The `seq_counters` collection's keying changes from `_id=task_id` to `_id="{chat_id}:{claude_session_id or '_global'}"` — slice 8 ships a one-time migration. Slice 5a left a stub `Task` collection with a handful of dev rows; rename them to `Chat`. The web subscription endpoint flips from `/ws/web/tasks/{task_id}` to `/ws/web/chats/{chat_id}` — slice 5a's plumbing carries over unchanged behind the rename.
12. **Multi-chats per repo via git worktrees**. The user can have multiple chats open on the same repo concurrently. Each chat owns its own working tree under `/work/<repo>/.octo-worktrees/chat-<slug>/` (created via `git worktree add`), branch = `octo/chat-<slug>`. The CLI's `cwd` is the worktree path, not the bare repo dir. Chats are first-class concurrent objects — there is no "one task per repo" cap. Worktree cleanup on chat archive/cancel: `git worktree remove --force` then drop the branch (or keep it if a PR is open, slice 9). The repo at `/work/<repo>/` (slice 5b's clone target) hosts the worktrees; the working tree on the default branch stays untouched by chats. One-time migration on slice-8 boot: convert the existing `/work/<repo>/` clones into the new layout — a `git worktree add` of the default branch into `.octo-worktrees/main/` so the slice-6 IDE keeps showing the same files.
13. **Git ops live in slice 9.** This slice lets the agent commit on the chat's branch + leave the worktree dirty; the actual `git push` + `repos.create_pull_request` are slice 9's job. Slice 8 ships when the agent edits files, commits locally, and the FE shows the diff via `FileEditEvent`. The slice plan ([Plan.md §18](../Plan.md)) is updated to match.
14. **Bridge-token rotation** is `POST /api/sandboxes/{id}/rotate-bridge-token`, gated by `ALLOW_INTERNAL_ENDPOINTS`. v1 ops surface (rate limit, audit log) is post-v1; the endpoint exists for tests + emergency manual rotation.

---

## Context from slices 5b, 6, 7

Read [slice5b.md](slice5b.md), slice6.md, slice7.md before starting. Key things in place that slice 8 builds on:

- **Slice 5b**: Provider Protocol has `exec_oneshot`, `fs_list`, `fs_read`, `fs_write`, `fs_delete`, `snapshot`, `restore`. Slice 8 uses **none of these for agent work** — agent runs go through the bridge↔WSS leg. `exec_oneshot` is still used for git config setup and reconciliation; the bridge uses `git worktree` ops via plain shell on the sprite (it's local).
- **Slice 5b**: Reconciliation places repos at `/work/<full_name>/` reliably. Slice 8 wraps these in worktrees on first chat creation per repo.
- **Slice 5b**: `git` is set up with fixed config at `/etc/octo-canvas/gitconfig` + `…/git-credentials`. Every git op exports `GIT_CONFIG_GLOBAL`. Bridge inherits this convention.
- **Slice 6** ships the IDE shell: file tree, file editor, terminal — plus the dummy "Chats" panel that slice 8 wires up. The orchestrator's `/api/sandboxes/{id}/fs` (REST) and `/ws/web/sandboxes/{id}/pty/{terminal_id}` (PTY broker) are slice 6's surface; slice 8 reuses them.
- **Slice 7** ships the sprite image: Node ≥ 20, the pinned `claude` CLI binary, the bridge wheel installed at `/opt/bridge`, runtime managers (nvm/pyenv/etc) usable by the agent. Entrypoint is `python -m bridge.main`. Slice 8 *consumes* this image; it does not modify it.
- **Slice 5a**: `/ws/web/chats/{chat_id}` (renamed from `/ws/web/tasks/{task_id}` in slice 8 per call #11) + `seq`-replay + Redis pub/sub on `chat:{chat_id}` (renamed too) are the FE wire. Slice 8 widens the producer side: bridge frames → `agent_events` rows → the chat channel.
- **Slice 5a**: `python_packages/shared_models/src/shared_models/wire_protocol/` has `events.py` + `commands.py` (web-leg). Slice 8 adds `bridge.py` as a sibling, uses the same JSON-Schema → TS codegen step.
- **Slice 5a**: `Sandbox` doc has the 7-state machine. Slice 8 adds `bridge_token_hash: str`, `bridge_version: str | None`, `bridge_connected_at: datetime | None`, `bridge_last_acked_seq_per_chat: dict[str, int]`.
- Pyright strict + TS strict + `noUncheckedIndexedAccess` are the bar. `pnpm --filter @octo-canvas/api-types gen:api-types` regenerates both `wire.d.ts` (now covers web + bridge unions) and `schema.d.ts`.

---

## What "done" looks like

After this slice, a developer with a connected repo can:

1. Sign in, ensure their sandbox is `warm` and `repo-a` is cloned.
2. `POST /api/tasks {repo_id, prompt: "add a HELLO.md"}` → `Task` row with `status="running"`, `claude_session_id=null` initially.
3. Watch `/ws/web/tasks/{task_id}` stream:
   - `StatusChangeEvent("running")`
   - `AssistantMessage` blocks streaming as the agent thinks
   - `ToolCallStarted{tool_name:"Write", args:{path:"HELLO.md", ...}}`
   - `FileEditEvent{path:"HELLO.md", before_sha:null, after_sha:"...", summary:"+1 -0"}`
   - `ToolCallStarted{tool_name:"Bash", args:{cmd:"git add -A && git commit -m '...'"}}`
   - `ShellExecEvent{cmd:"git commit ...", exit_code:0}`
   - `TokenUsageEvent{input_delta:..., output_delta:...}`
   - `StatusChangeEvent("completed")`
4. Verify in Mongo: `Task.claude_session_id` is now populated, `AgentRun(is_follow_up=false)` is `completed`.
5. `POST /api/tasks/{id}/messages {prompt:"make it a heading 1"}` → second `AgentRun` with `is_follow_up=true`, **same `claude_session_id`**, more events arrive on the same WS, second commit lands on the same branch.
6. Open a third task on `repo-b` while the first session is idle → bridge spawns a second CLI; both sessions remain live; LRU-eviction works once a 4th would be opened (verifiable via bridge log + `agent_events`).
7. Send the agent into a clarification: a prompt like "what color theme do you prefer?" → bridge emits `AskUserClarification` → FE shows the dialog → user replies → agent unblocks and continues.
8. **Resilience checks**:
   - Force-kill the orchestrator mid-turn → bridge buffers events; orchestrator restart → bridge `Hello{last_acked_seq}` replays missed frames; `agent_events` shows continuous `seq`.
   - `docker compose restart` the bridge mid-turn → CLI subprocess dies; on next `UserMessage` the session re-spawns via `--resume`; transcript intact.
   - Tab close + reopen during the run → `Resume{after_seq}` from the FE catches up via Mongo.
9. Auth checks:
   - Wrong `BRIDGE_TOKEN` on bridge handshake → close `4001`.
   - Right token but `sandbox_id` mismatch → close `4003`.
   - Web client subscribes to a task they don't own → close `4003`.
10. `pnpm typecheck && pnpm lint && pnpm test && pnpm build` and orchestrator + bridge pytest all green.

---

## What to build

### 1. Wire protocol — `python_packages/shared_models/src/shared_models/wire_protocol/bridge.py`

Two discriminated unions:

- `BridgeToOrchestrator` — `Hello`, `Goodbye`, `SessionStarted`, `SessionEvicted`, `AssistantMessage`, `ToolCallStarted`, `ToolCallFinished`, `FileEditEvent`, `ShellExecEvent`, `GitOpEvent`, `TokenUsageEvent`, `StatusChangeEvent`, `AskUserClarification`, `ErrorEvent`, `Pong`. Each event-class member carries `session_id: str` and `seq: int`; connection-class members (Hello/Goodbye/Pong) skip them.
- `OrchestratorToBridge` — `SessionState`, `UserMessage`, `AnswerClarification`, `CancelSession`, `PauseSession`, `SessionEnv` (declared, unused in v1), `Ack`, `Ping`. Inbound commands carry `frame_id: str` for idempotency.

Pydantic v2 `Field(discriminator='type')`; `model_config = ConfigDict(extra="ignore")` on every variant for forward-compat (per slice 5a's risk #1). `BridgeToOrchestratorAdapter = TypeAdapter(BridgeToOrchestrator)` and dual for the other direction.

Extend `python_packages/shared_models/src/shared_models/scripts/gen_wire_schema.py` to dump both adapters → JSON Schema → `packages/api-types/generated/wire.d.ts` (existing pipeline).

### 2. Beanie model widening — `python_packages/db/src/db/models/`

- `task.py` — widen the slice-5a stub: `repo_id`, `title`, `status` (literal: `pending|running|awaiting_input|completed|failed|cancelled`), `initial_prompt`, `base_branch`, `work_branch`, `claude_session_id`, `pr_number`, `pr_url`, `token_budget_input/output`. Index on `(user_id, repo_id, status)` to enforce the per-(user,repo) one-open-task rule.
- `agent_run.py` — new collection per [Plan.md §8](../Plan.md). Index on `(task_id, started_at)`.
- `agent_event.py` — widen with `session_id: str | None`. Index becomes `(task_id, session_id, seq)`. Migration: existing dev-mode rows get `session_id=None`.
- `seq_counter.py` — re-key `_id` to `f"{task_id}:{session_id or '_global'}"`. Migration: same one-time renumber.
- `sandbox.py` — add `bridge_token_hash: str` (sha256 of plaintext, never store plain), `bridge_version: str | None`, `bridge_connected_at: datetime | None`, `bridge_last_acked_seq_per_session: dict[str, int] = Field(default_factory=dict)`.
- `user.py` — add `claude_auth_mode: Literal[...] = "platform_api_key"`.

Register all new docs in `db/mongo.py:_DOCUMENT_MODELS`. New typed accessors on `mongo.tasks`, `mongo.agent_runs`, `mongo.agent_events`, `mongo.seq_counters`. Add `Collections.AGENT_RUNS` constant.

### 3. Event store — `apps/orchestrator/src/orchestrator/services/event_store.py`

Widen `append_event(task_id, session_id, payload, *, redis)`:

1. Allocate seq atomically against `_id=f"{task_id}:{session_id or '_global'}"`.
2. Insert `AgentEvent(task_id, session_id, seq, payload, created_at)`.
3. Publish to `task:{task_id}` (unchanged channel — payload now carries session_id so subscribers can route).
4. Return the event.

Add `ack_bridge_session(sandbox_id, session_id, seq)` — writes `Sandbox.bridge_last_acked_seq_per_session[session_id] = seq` (used by bridge owner to know what to ack back).

### 3a. Anthropic reverse proxy — `apps/orchestrator/src/orchestrator/routes/anthropic_proxy.py`

The slice-7 invariant ("real Anthropic key never enters the sprite") rests on this route. Implementation contract is locked in [slice7.md §6b](slice7.md) — read it before writing a line. Summary:

- Route: `@router.api_route("/api/_internal/anthropic-proxy/{sandbox_id}/{path:path}", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"], include_in_schema=False)`.
- Auth: read `Authorization: Bearer <token>`; reject if missing. `hashlib.sha256(token).hexdigest()` + `hmac.compare_digest` against `Sandbox(sandbox_id).bridge_token_hash`. 401 on any mismatch (no diagnostic detail — same response for missing-sandbox / wrong-token / wrong-format to deny probe info).
- Real-key swap: strip `Authorization` from inbound; set outbound `x-api-key: <real>` from `request.app.state.bridge_config._anthropic_api_key`. 503 on missing real key.
- Lifespan: `app.state.anthropic_proxy_client = httpx.AsyncClient(http2=True, timeout=httpx.Timeout(connect=10, read=600, write=60, pool=10))` started in `app.lifespan`, `await client.aclose()` on shutdown.
- Async streaming end-to-end (the *only* acceptable shape):
  - Inbound body: `content=request.stream()` — never `request.body()`/`request.json()`.
  - Upstream: `req = client.build_request(method=request.method, url=upstream_url, headers=swapped_headers, content=request.stream()); upstream = await client.send(req, stream=True)` — never `client.post(...)`/`response.aread()`.
  - Response: `async def relay(): try: async for chunk in upstream.aiter_raw(): yield chunk; finally: await upstream.aclose()` wrapped in `StreamingResponse(relay(), status_code=upstream.status_code, headers=filtered_outbound, background=BackgroundTask(upstream.aclose))`.
  - Inject `Cache-Control: no-cache` + `X-Accel-Buffering: no` on the response so any nginx in front doesn't buffer SSE.
- Header filtering (both directions): drop hop-by-hop (`connection`, `keep-alive`, `proxy-authenticate`, `proxy-authorization`, `te`, `trailers`, `transfer-encoding`, `upgrade`, `host`, `content-length`) + `authorization` + `x-api-key`. Forward everything else verbatim (incl. `anthropic-version`, `anthropic-beta`, `content-type`).
- Path / query: forward `path` verbatim; preserve `request.url.query`.
- Cancellation: bridge disconnect → handler cancelled → `finally: aclose()` → upstream HTTP/2 RST → Anthropic stops billing.
- Error mapping: upstream 5xx + `httpx.RequestError` → 502; real-key missing → 503; auth failure → 401. Never echo upstream error bodies that might mention key prefixes.
- **Async-correctness audit**: nothing in the module imports `requests`, `urllib`, or `time.sleep`. Any sync I/O is a regression — CI grep should fail on those imports in this file.

Verified-2026-05 against `claude` CLI v2.1.118 binary env-parsing. The CLI sends `Authorization: Bearer <ANTHROPIC_AUTH_TOKEN>` (we omit `ANTHROPIC_API_KEY`); the proxy validates Bearer, swaps to `x-api-key` for upstream because Anthropic's API expects `x-api-key` for non-OAuth tokens.

### 4. Bridge WSS handler — `apps/orchestrator/src/orchestrator/ws/bridge.py`

`@router.websocket("/ws/bridge/{sandbox_id}")`:

1. Accept the WS first (FastAPI 4xxx codes only meaningful post-accept — same lesson as slice 5a).
2. Read `Authorization: Bearer ...` from headers; sha256 → compare against `Sandbox.bridge_token_hash`. Mismatch → close `4001`. Sandbox is `destroyed` → close `4003`.
3. Spawn a `BridgeSession` task. Three concurrent loops via `asyncio.TaskGroup`:
   - `read_inbound`: validate `BridgeToOrchestrator` frames, persist via `event_store.append_event`, ack via `Ack{ack_seq}` periodically.
   - `pump_outbound`: read commands from a queue (filled by `BridgeOwner` Redis subscription + direct in-process appends), serialize, send.
   - `heartbeat`: 30s `Ping`, 90s rx-deadline (same as slice 5a).
4. Claim ownership: `redis.set(f"bridge_owner:{sandbox_id}", instance_id, ex=60, nx=True)`. If somebody else holds it, close `4009` (rare; bridge will reconnect → other instance gets the new connection if it lost the bridge's TCP).
5. Refresh ownership every 20s; release on disconnect.

### 5. Bridge owner / cross-instance routing — `apps/orchestrator/src/orchestrator/services/bridge_owner.py`

Per-instance singleton, started in lifespan:

- Subscribes to `bridge_in:*` Redis pattern; for each frame, looks up the local `BridgeSession` (if owned here, deliver) or drops (someone else owns it).
- Publishes outbound commands from non-owner instances via `redis.publish(f"bridge_in:{sandbox_id}", payload)`.
- Provides `async def send_to_bridge(sandbox_id, frame) -> None` — checks ownership locally first, falls back to publish.

### 6. Task service — `apps/orchestrator/src/orchestrator/services/task_runner.py`

- `create_task(user, repo, prompt) -> Task`: enforce one-open-per-(user, repo) (409 otherwise), create `Task` and first `AgentRun(is_follow_up=False)`, send `UserMessage{session_id=task_id_str, task_id, repo_full_name, claude_session_id=None, text}` to the bridge via `bridge_owner.send_to_bridge`. **Note**: `session_id` on the wire is the orchestrator-assigned id (we use `str(task_id)`); the CLI's own `claude_session_id` is set later when `SessionStarted` arrives back.
- `add_follow_up(task, prompt) -> AgentRun`: creates a new `AgentRun(is_follow_up=True)`, sends `UserMessage` with the task's known `claude_session_id`.
- `cancel_task(task)`: sends `CancelSession`, marks the run `cancelled`.

### 7. Routes — `apps/orchestrator/src/orchestrator/routes/tasks.py`

- `POST /api/tasks` — body `{repo_id, prompt}`. Calls `task_runner.create_task`. Returns `TaskResponse`.
- `GET /api/tasks` — list user's tasks (paginated).
- `GET /api/tasks/{task_id}` — single task.
- `POST /api/tasks/{task_id}/messages` — body `{prompt}`. Follow-up.
- `POST /api/tasks/{task_id}/cancel` — cancel.

Plus dev-only `POST /api/sandboxes/{id}/rotate-bridge-token` behind `ALLOW_INTERNAL_ENDPOINTS` (returns the new plaintext once; updates `bridge_token_hash`; bridge will reconnect on next `Hello` and fail until env is updated — operator restarts the sprite).

### 8. Bridge process — `apps/bridge/`

New tree:

```
apps/bridge/
├── pyproject.toml          # uv workspace member
├── Dockerfile.sprite       # bakes Node + CLI + bridge wheel
└── src/bridge/
    ├── main.py             # entrypoint; reads env; constructs WsClient + SessionMux; runs forever
    ├── ws_client.py        # WSS dialer; ring buffer; reconnect; Hello/Ack/Ping
    ├── session_mux.py      # ClaudeSession dataclass; spawn/evict/route logic
    ├── ringbuf.py          # per-session 1000-frame / 1MB ring
    ├── credentials/
    │   ├── __init__.py     # re-exports
    │   └── platform_api_key.py
    └── mcp/
        └── octo_server.py  # in-process MCP server with ask_user_clarification
```

`session_mux.py` orchestrates per-session `ClaudeAgentClient`s from `claude-agent-sdk`:

- On `UserMessage`: if no live session for `session_id`, check eviction (LRU + cap); spawn new client with `cwd=/work/{repo_full_name}`, `resume=claude_session_id` (None on first turn), `system_prompt=render(...)`, `allowed_tools=[...]`, `permission_mode="acceptEdits"`, `mcp_servers={"octo": OctoMcpServer(self)}`, `env=await self.creds.env()`.
- Stream `client.receive_response()`, translate each SDK message to a `BridgeToOrchestrator` frame, push to ws_client's outbound queue (which assigns `seq` per session and writes to ring buffer before sending).
- Capture `claude_session_id` from `ResultMessage.session_id`; emit `SessionStarted` on first capture.
- Handle `CancelSession` → call `client.interrupt()` then close.

### 9. System prompt — `python_packages/agent_config/src/agent_config/dev_agent_prompt.py`

Render-time inputs: `repo_full_name`, `default_branch`, `language`, `package_manager`, `test_command`, `build_command`, `dev_command`, in-repo `CLAUDE.md` text (if exists, fetched via `provider.fs_read` once at session spawn). Hard rules: don't push to base branch, don't `rm -rf /`, don't reach outside `/work/<repo>/`, call `ask_user_clarification` when truly blocked rather than guessing.

### 10. Frontend — `apps/web/`

- `src/routes/_authed/tasks/index.tsx` — task list per user. "New task" CTA opens a modal: pick repo, type prompt.
- `src/routes/_authed/tasks/$taskId.tsx` — replaces the slice-5a debug page. Shows: title, repo, status pill, full event stream (`AssistantMessage`, tool calls collapsed by default, `FileEditEvent` with diff link, etc.), follow-up message box (disabled while `status="running"` unless `awaiting_input`), `AskUserClarification` modal.
- `src/components/TaskEventList.tsx` — event renderer with per-type components.
- `src/lib/tasks.ts` — typed mutations: `createTask`, `addFollowUp`, `cancelTask`, `answerClarification`.

Light theme only ([AGENTS.md §2.8](../../AGENTS.md)).

### 11. Sprite image — `apps/bridge/Dockerfile.sprite`

Base from Sprites' image expectation (Ubuntu LTS + passwordless sudo). Add:
- Node ≥ 20 via NodeSource.
- `npm i -g @anthropic-ai/claude-code@<pinned>` — pin a specific version; record in `apps/bridge/CLAUDE_CLI_VERSION`.
- Python 3.12, uv.
- Build the bridge wheel locally, install with `uv pip install`.
- `ENTRYPOINT ["python", "-m", "bridge.main"]`.

CI: build + push the sprite image on every merge to main. The orchestrator's `SandboxProvider.create()` picks up the image tag from `BRIDGE_IMAGE_TAG` env var (slice 5b's `Sandbox` provision call gets a new arg).

### 12. Tests

Bridge unit tests (`apps/bridge/tests/`):
- `test_session_mux.py`: spawn → message → ResultMessage → frames; eviction at cap; LRU pick; resume path.
- `test_ringbuf.py`: 1000-frame eviction, 1MB byte-size eviction, replay-after-ack.
- `test_ws_client.py`: reconnect with `Hello{last_acked_seq}`, ack pruning, idempotent inbound `frame_id`.
- `test_mcp_clarification.py`: tool-blocks-on-future, future resolves on AnswerClarification, 5-min timeout.
- `test_credentials.py`: `PlatformApiKeyCredentials` resolves env from `ANTHROPIC_API_KEY`.

Orchestrator tests (`apps/orchestrator/tests/`):
- `test_ws_bridge_handshake.py`: bad token → 4001; valid → ownership claimed in Redis.
- `test_ws_bridge_replay.py`: send 5 frames, `Ack{3}`, disconnect, reconnect with `Hello{3}` → frames 4,5 replayed.
- `test_task_create.py`: 409 on duplicate-open-task-per-repo; happy path creates `Task` + `AgentRun` + sends `UserMessage` to mocked bridge.
- `test_task_followup.py`: second message reuses `claude_session_id` from `SessionStarted`.
- `test_bridge_owner.py`: two orchestrator instances + one Redis; commands routed to owner via pub/sub.
- `test_clarification_routing.py`: passthrough mode (slice 8) — `AskUserClarification` from bridge → `chat:{id}` Redis → web subscriber sees it; `AnswerClarification` from web → bridge frame.
- `test_anthropic_proxy.py`:
  - 401 on missing/wrong/badly-formatted `Authorization: Bearer ...` (single response shape — no probe channel).
  - Valid bearer → upstream call made with `x-api-key: <real_key>`, `Authorization` stripped.
  - Real-key string never appears in any response body or header sent back to the bridge (audit assertion against a sentinel `sk-ant-real-secret`).
  - SSE streaming: in-process fake-Anthropic emits 10 chunks 50ms apart; assert each chunk arrives at the bridge mock within 100ms of being emitted (proves no buffering). Use `httpx.MockTransport` or a tiny ASGI stub.
  - Bridge disconnect mid-stream → `upstream.aclose()` runs (assert via spy on the mock). Anthropic stops billing.
  - Header filter drops hop-by-hop on both directions. Verify `Cache-Control: no-cache` + `X-Accel-Buffering: no` set on the response.
  - Static check: `import requests` / `import urllib` / `time.sleep` absent from the proxy module.

Full-stack smoke (manual, documented):
- One real sprite, one orchestrator, one web tab. File a task → see PR-less commits. Follow-up.
- Inside the sprite: `env | grep -i anthrop` shows only `CLAUDE_CODE_API_BASE_URL`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`. The real `sk-ant-...` key is absent. `cat /proc/$(pgrep -f bridge)/environ | tr '\\0' '\\n' | grep -i sk-ant` returns nothing.

---

## Out of scope (explicit)

- **User Agent**: prompt enhancement, `AgentAnsweredClarification`, `OverrideAgentAnswer`, `claude_auth_mode` settings UI. Slice 8b.
- **PR creation**: `git push` + `repos.create_pull_request` via githubkit. Slice 9.
- **PTY**: `/ws/web/sandboxes/{id}/pty/{terminal_id}`. Already shipped in slice 6.
- **File ops REST**: `GET/PUT /api/sandboxes/{id}/fs`. Already shipped in slice 6.
- **HTTP preview proxy**: already absorbed via Sprites' built-in URL.
- **OAuth and BYOK Claude credentials**: Protocol exists; impls don't.
- **Hard token-budget enforcement**: warning events only in slice 8; hard cut-off in slice 8b.
- **Bridge-token rotation as ops surface**: slice 8 ships endpoint behind `ALLOW_INTERNAL_ENDPOINTS`; user-facing rotate flow is post-v1.
- **Multi-task-per-repo via worktrees**: post-v1.
- **Cross-repo tasks**: post-v1.
- **24h Mongo / S3 archive**: slice 10.

---

## Risks

1. **Worktree-vs-clone-layout migration is risky.** Slice 5b shipped clones at `/work/<repo>/`; slice 8 introduces `.octo-worktrees/` underneath. The migration must be idempotent (don't re-add the main worktree if it exists) and it changes what slice 6's IDE file tree displays. Coordinate with slice 6 owners: file tree must root at `/work/<repo>/.octo-worktrees/<active-worktree>/`, not `/work/<repo>/` directly. If this turns out to be too disruptive, a fallback is "one chat per repo at a time" using the bare clone — but we lose multi-chats per repo. Decide before code.
2. **CLI binary version drift.** Pin in `apps/bridge/CLAUDE_CLI_VERSION` and check at bridge boot (`claude --version`); refuse to start on mismatch.
3. **Bridge-owner failover under churn.** Two orchestrator instances racing for ownership when a sprite restarts: `set NX EX 60` is atomic; whoever wins owns it. The loser closes `4009` and the bridge reconnects (LB reroute possible). Worst-case: a few seconds of dropped commands → Mongo replay fixes any web-side gap; bridge ring buffer fixes any bridge-side gap.
4. **MCP `ask_user_clarification` deadlock.** 5-min timeout is the hard stop. Bridge logs the open-clarification list every 60s for ops visibility.
5. **CLI cache miss on evict-resume.** Evicted sessions re-pay prompt cache when the next `--resume` happens. Acceptable for v1; revisit if eviction frequency grows (lower the cap or bump the idle window).
6. **`acceptEdits` permission mode is permissive.** Hooks are the safety net (Bash jail, path validation). Audit hook coverage in code review; add tests for each rejected pattern.
7. **Two concurrent chats touching the same repo.** Allowed in v1 via git worktrees (see call #12). The risk is worktree state divergence (someone runs `git checkout` in a terminal and detaches a worktree's HEAD). Mitigation: bridge `git status` checks before each agent turn and rejects with `ErrorEvent{kind:"worktree_dirty_externally"}` if the worktree isn't on its expected branch.
8. **Wire schema evolution.** `BridgeToOrchestrator` adds many message types; future slices (6b especially) widen further. `extra="ignore"` per variant is the forward-compat lever (same as slice 5a). Old bridges seeing new orchestrator commands MUST gracefully ignore unknown types, not crash. Test explicitly.
9. **Bridge reconnect storms after orchestrator deploy.** Jittered backoff (1→16s ±25%) like slice 5a's web client. Pin the same backoff util.
10. **Sandbox doc growth.** `bridge_last_acked_seq_per_chat: dict[str, int]` grows with every chat. Cleanup job: prune entries for chats that are `completed`/`failed`/`cancelled`/`archived` and older than 7d. Slice 8 adds a TODO; cleanup job lands with slice 10.
11. **Image bake cost in CI.** `npm i -g @anthropic-ai/claude-code` + a wheel build adds minutes to CI. Cache the npm install layer; build the wheel separately and `COPY --from=...`.
12. **Orchestrator restart drops in-flight `UserMessage` if the owning instance crashes between accepting `POST /api/tasks/{id}/messages` and forwarding to the bridge.** Mitigation: write the `AgentRun` row first, then send the `UserMessage`; on orchestrator boot, scan for `AgentRun(status="queued")` rows and re-send their `UserMessage` to the bridge. Idempotency on `frame_id` prevents double-execution.

---

## Acceptance — copy-paste checklist

- [ ] `pnpm typecheck` clean.
- [ ] `pnpm lint` clean.
- [ ] `pnpm --filter @octo-canvas/api-types gen:api-types` regenerates `wire.d.ts` (now includes `BridgeToOrchestrator` + `OrchestratorToBridge`); `pnpm typecheck` still clean.
- [ ] `uv run pytest apps/orchestrator/tests/` and `uv run pytest apps/bridge/tests/` both green. Required tests:
  - bridge handshake auth: bad token → 4001; mismatched sandbox_id → 4003.
  - replay: 5 frames, ack 3, disconnect, reconnect → 4-5 replayed; no dupes on overlap.
  - bridge-owner: cross-instance command routing via Redis.
  - task-create: 409 on duplicate-open-per-repo.
  - follow-up: reuses `claude_session_id`.
  - clarification: passthrough WS round-trip, 5-min timeout abort.
  - eviction: 4th session forces LRU eviction; resumed session rehydrates transcript.
  - frame_id idempotency: replayed `AnswerClarification` resolves the same future once.
- [ ] Manual smoke (real sprite + real Anthropic key): file a task, see commits land. Follow-up. Cancel mid-run. Force-restart orchestrator → bridge replays.
- [ ] Sprite image builds in CI; `claude --version` matches `apps/bridge/CLAUDE_CLI_VERSION`.
- [ ] [docs/progress.md](../progress.md) row updated.
- [ ] [docs/Contributions.md](../Contributions.md) entry added.
- [ ] [docs/agent_context.md](../agent_context.md) updated: TL;DR mentions the bridge daemon revival; gotchas list the bridge↔orchestrator WSS leg + `MAX_LIVE_SESSIONS_PER_SANDBOX`.
- [ ] User signs off → this brief is frozen; corrections live in `progress.md`.
