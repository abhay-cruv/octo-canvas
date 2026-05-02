# Slice 8 — Chats + Bridge + dual-agent runtime (dev agent + user agent)

The first slice that makes the agent actually run. Builds on slice 6 (the IDE shell — file tree, file editor, terminal) and slice 7 (reconciler-driven sandbox tooling — Node + npm-global `claude` CLI + nvm/pyenv/rbenv + rustup; **no Docker image bake**, Sprites is already a VM).

The dummy chat panel from slice 6 becomes a real chat surface. The user opens a Chat, types a prompt, the **user agent** (Haiku 4.5 on the orchestrator) optionally enhances/contextualizes the prompt and forwards it to the **dev agent** (`claude` CLI driven by `claude-agent-sdk`, running inside the sprite, supervised by the `bridge` daemon). The dev agent edits files on its own branch; the bridge keeps the CLI alive across messages; the user sees one unified transcript.

**Two agents, one UX.** From the user's perspective they're chatting with one entity. Internally:

```
                ┌──────────────────────────────────────────────┐
User types ───► │ BE: user agent (Haiku 4.5, in-process)        │
                │   • always sees user messages (when enabled)  │
                │   • reads/writes Mongo memory                 │
                │   • optionally enhances/contextualises prompt │
                │   • reviews IMPORTANT dev-agent output:       │
                │       AskUserClarification, ResultMessage,    │
                │       final AssistantMessage blocks (not       │
                │       streaming deltas, thinking, tool calls) │
                │   • can auto-answer clarifications            │
                └────────────────┬─────────────────────────────┘
                                 │ enhanced UserMessage
                                 ▼
                        /ws/bridge/{sandbox_id}
                                 │
                                 ▼
                       Bridge (long-lived in sprite)
                                 │ ClaudeSDKClient
                                 ▼
                     `claude` CLI ──HTTP──► orchestrator proxy ──► api.anthropic.com
                                 │ stream of events back
                                 ▼
                      Event store + Redis fan-out
                                 │            │
                                 ▼            ▼
                     user agent (filtered)   FE (full stream)
                                 │
                                 ▼
                     AgentAnsweredClarification (10s override)
```

**Architectural pivot from earlier drafts.** Two pivots from the original 2026-04 brief:
1. Old plan said "agent invocation = `provider.exec_oneshot(['python','-m','agent_runner', task_json])` per run." Discarded — Claude Code is a long-lived process; subprocess-per-run gives no message-level idempotency and pays cold-start every turn. The bridge daemon is back, owning the WSS leg, the CLI subprocesses, and the in-process MCP server.
2. Old slice 8 brief had `Chat.scope = "repo"` worktrees + per-chat branches. Discarded — slice 8 chats run at `cwd=/work/` always; multi-repo edits in one chat are allowed; branch + PR semantics defer to slice 9.

**This slice ends at:** "the user opens a chat → user agent enhances the prompt → bridge spawns a CLI session → dev agent edits files (visible live in the slice-6 file tree) → user sees a unified streaming transcript with thinking, tool calls, edits, and answers → user agent auto-handles some clarifications behind a 10s override → CLI stays alive across follow-ups → multiple chats run side-by-side."

**Out of scope** (deferred): git push / PR creation (slice 9), HTTP preview controls (slice 10), event-log archive (slice 11), OAuth / BYOK Claude credentials (Protocol exists, impls don't), bridge-token rotation as an ops surface (endpoint exists behind `ALLOW_INTERNAL_ENDPOINTS` for tests), hard token-budget cut-off (slice 8 is warn-only).

---

## Calls baked in (push back if any are wrong)

1. **Two agents, one user-facing transcript.** The web UI shows ONE merged event stream per chat. Dev-agent output (assistant text, thinking, tool calls, tool results, edits, clarifications) and user-agent output (prompt-enhancement notes, auto-answers with override countdown) are interleaved by timestamp on a single transcript. The user does not see two columns and does not pick which agent to talk to.
2. **User agent runs on the orchestrator (BE), not in the sandbox and not in the browser.** Why: the orchestrator already has the real Anthropic API key (the proxy is the slice-7 invariant); putting the user agent there avoids a second key-bearing process. The FE is a pure UX surface — it renders streamed user-agent decisions, the override countdown, and a settings toggle. **No in-browser LLM calls.**
3. **`UserAgent` on/off per user, provider-agnostic, model configurable.** `User.user_agent_enabled: bool = True`. `User.user_agent_provider: Literal["anthropic","openai","google",...] = "anthropic"`. `User.user_agent_model: str = "claude-haiku-4-5"`. The user agent is built against an `LLMProvider` Protocol at `python_packages/agent_config/src/agent_config/llm_provider.py` (`async def complete(messages, *, system, model, max_tokens, tools=None) -> CompleteResult` + a streaming variant). v1 ships `AnthropicProvider` as the only impl; OpenAI / Gemini land later as additional impls + a settings flip — no schema migration. When OFF: direct passthrough — the user's text becomes a `UserMessage` to the bridge unchanged; the dev agent's full stream goes straight to the FE; no Mongo memory writes. When ON: the rules in #4 + #5 apply.
4. **User agent sees ALL user messages (when enabled).** Every `POST /api/chats/{id}/messages` is processed by the user agent before being forwarded to the bridge. The user agent can:
   - **Pass through unchanged** — most common, low cost.
   - **Enhance** — append context retrieved from memory (`memory_list` → `memory_read` for relevant topics). The enhancement is visible to the user as a collapsible "User agent context" block in the transcript so it's never invisible.
   - **Refuse** — emit a clarification back to the user inline (e.g. "the chat is about repo A but your message says repo B; which?") instead of forwarding. Rare for v1.
5. **User agent sees only IMPORTANT dev-agent output (when enabled).** It does NOT see streaming `AssistantMessage` deltas, `ThinkingBlock`, `ToolUseBlock`, or `ToolResultBlock` events — those are noise for a Haiku-class model and would burn its context. It DOES see:
   - `AskUserClarification` — always (this is the moment the user agent might auto-answer)
   - `ResultMessage` — once, at the end of each dev-agent turn (the conclusion)
   - The final, non-streaming `AssistantMessage` block emitted at turn close
   - `ErrorEvent`
   The orchestrator's event-store layer routes the full stream to the FE and the filtered subset to the user agent. Filter rule lives in `apps/orchestrator/src/orchestrator/services/user_agent/filter.py`.
6. **User-agent memory is in Mongo, MEMORY.md-shaped.** New collection `user_agent_memory` — see §2 schema. The memory shape mirrors Claude Code's auto-memory: a top-level index doc per user (`name="MEMORY"`) lists pointers to topic docs (`name="prefs"` / `name="project_<repo>"` / `name="feedback_*"` / etc.), each with a one-line `description`. The user agent has four in-process tools (NOT MCP — same Python process):
   - `memory_list() -> [{name, kind, description}]`
   - `memory_read(name) -> str`
   - `memory_write(name, kind, description, body)` — upsert, updates index automatically
   - `memory_delete(name)`
   System prompt steers it to "always `memory_list` first, only `memory_read` topics that look relevant, write back after the chat, follow the user/feedback/project/reference convention with `Why:` + `How to apply:` lines for feedback and project."
7. **`Chat` runs at `cwd=/work/`. No worktrees, no per-repo binding, no branch in slice 8.** A chat is a long-lived `claude-agent-sdk` session against `cwd=/work/`. The dev agent can edit files across any repo under `/work/<full_name>/`. Local commits are allowed (`git commit`); push and PR creation defer to slice 9, which will inspect which repos got commits in a chat and open PRs accordingly. Concurrent chats touching the same repo are a known foot-gun for v1 — the worktree mitigation from earlier drafts is removed; users are trusted not to run two chats editing the same files. If it bites in practice, revisit.
8. **`Chat ↔ Claude session 1:1`.** New `Chat` doc per [Plan.md §8](../Plan.md). `Chat.claude_session_id: str | None` — null until the first SDK turn completes (the SDK assigns it via `ResultMessage.session_id`); subsequent messages reuse the same id. Each user message creates a `ChatTurn` row; all turns share the chat's session id.
9. **CLI stays alive while the user is connected; we do NOT kill on idle.** The bridge keeps the `claude-agent-sdk` `ClaudeSDKClient` open between user messages — follow-ups feed text directly to the live SDK client (no `--resume`, no cache miss). `--resume` is the cold-path fallback used only when the CLI process is gone.

   ```
   none ─► cold ─► warming (resume=session_id) ─► live ─► live (next msg: direct feed)
                       ▲                          │
                       └────────────  cold (process gone)
   ```

   Triggers that move `live → cold`:
   - All web subscribers for this chat disconnect AND `IDLE_AFTER_DISCONNECT_S = 300` (5 min) grace timer fires.
   - The user explicitly archives the chat.
   - Hard cap: `MAX_LIVE_CHATS_PER_SANDBOX = 5` (env-tunable). LRU `cold`-eligible chat is evicted only if it has no live web subscriber. If all 5 have subscribers, new chat creation queues with `BackpressureWarning{kind:"chat_cap_reached"}`.
   - Sprite hibernation — bridge SIGTERM handles cleanly.
   - Crash / OOM.

   Triggers that do NOT kill the CLI:
   - User idle in a connected web tab. Connected = alive.
   - Brief WSS flap with reconnect inside grace.
10. **One bridge↔orchestrator WSS per sprite, multiplexing all sessions.** Endpoint `/ws/bridge/{sandbox_id}`. Bridge dials home; orchestrator never opens. Auth: `Authorization: Bearer ${BRIDGE_TOKEN}` minted at bridge-launch time, persisted as `Sandbox.bridge_token_hash` (sha256). All inbound/outbound frames carry `chat_id` (event-class members) or skip it (`Hello`/`Goodbye`/`Pong`). Wire schema: Pydantic discriminated union in `python_packages/shared_models/src/shared_models/wire_protocol/bridge.py`. `seq` is per `(sandbox_id, chat_id)`.
11. **Bridge owns ring-buffer replay.** 1000 frames or 1 MB per chat, whichever smaller. On WSS reconnect: `Hello{last_acked_seq_per_chat}` → orchestrator replies with the last `seq` it has in Mongo per chat. Bridge re-emits any frames with `seq > orchestrator_last_seq`. Inbound commands are idempotent on `frame_id` (uuid4 from orchestrator).
12. **Cross-instance bridge ownership via Redis.** The orchestrator instance the bridge happens to dial owns it; that instance writes `bridge_owner:{sandbox_id} = {instance_id, expires_at}` (TTL 60s, refreshed every 20s). Other instances forward outbound commands via Redis pub/sub on `bridge_in:{sandbox_id}`. Inbound bridge events publish to `chat:{chat_id}` (looked up via `chat_id → sandbox_id`). Mongo is canonical.
13. **`ClaudeCredentials` is a Protocol; v1 ships only `PlatformApiKeyCredentials`.** `User.claude_auth_mode: Literal["platform_api_key","user_oauth","user_api_key"] = "platform_api_key"` is added in this slice but hard-coded. Future modes (OAuth, BYOK) are a Protocol impl + settings flip — not a schema migration. The Protocol lives at `python_packages/agent_config/src/agent_config/credentials.py` (already shipped in slice 7).

    **The real Anthropic key NEVER enters the sprite.** The bridge talks to api.anthropic.com via the orchestrator's reverse proxy at `/api/_internal/anthropic-proxy/{sandbox_id}/{path:path}` (built in this slice — see §4). Env piped to the bridge by `BridgeRuntimeConfig.env_for(sandbox_id, bridge_token)`:
    - `CLAUDE_CODE_API_BASE_URL = <orch>/api/_internal/anthropic-proxy/<sandbox_id>` (CLI v2.1.118 priority var)
    - `ANTHROPIC_BASE_URL = <same>` (fallback for older CLI builds + the SDK)
    - `ANTHROPIC_AUTH_TOKEN = <bridge_token>` (Bearer mode; takes priority over `ANTHROPIC_API_KEY` which we deliberately omit)

    The proxy validates `Authorization: Bearer <bridge_token>` (sha256 + `hmac.compare_digest` against `Sandbox.bridge_token_hash`), strips it, sets `x-api-key: <real_key>` outbound, reverse-proxies streaming to api.anthropic.com. Async-correctness contract is locked in §4.
14. **Dev-agent CLI tools = built-ins + one custom MCP tool.** Built-in: `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`. Custom (registered via in-process MCP server in the bridge): `ask_user_clarification(question, context?) -> str`. Permission mode: `acceptEdits`. Hooks (bridge-side, run in SDK callbacks):
    - `PreToolUse[Bash]` — parse the command; reject `cd /etc`, paths outside `/work/`, `git push` to base branch, `rm -rf /` patterns. Cap wall-clock at 5 min, output at 50 KB.
    - `PreToolUse[Write|Edit]` — reject paths outside `/work/`.
15. **`AskUserClarification` is in-process MCP, not stdio.** The MCP tool implementation creates an `asyncio.Future` keyed by `clarification_id`, sends `AskUserClarification` over WSS, awaits the future. Orchestrator routes:
    - If user agent enabled: sends to user agent first; if user agent decides "I can answer" → emits `AgentAnsweredClarification` to FE with a 10s override window → if not overridden, sends `AnswerClarification` back to bridge → tool's future resolves. If user agent decides "needs human" → forwards to FE for manual reply.
    - If user agent disabled: forwards directly to FE.
    - 5-min hard timeout → `ErrorEvent{kind:"clarification_timeout"}` and abort the run.
16. **Token usage** is read off each `ResultMessage.usage` from the SDK and emitted as `TokenUsageEvent{input_delta, output_delta}`. Per-chat budget defaults `Chat.token_budget_input=1_000_000`, `token_budget_output=500_000` — slice 8 emits warning events at 80%; **hard cut-off lands in slice 8b**.
17. **Sandbox bridge runtime.** No Docker image bake (slice 7 ripped that out). The reconciler's `installing_bridge` rest-step now also installs `uv` system-wide and creates `/opt/bridge/.venv` with a uv-managed Python 3.12 (`--python-preference only-managed`) — fully isolated from pyenv (so `pyenv global 3.13` cannot break the bridge). Then a separate per-pass step builds the bridge wheel + workspace deps on the orchestrator (`uv build --all-packages`), uploads them via `provider.fs_write` to `/opt/bridge/wheels/`, and runs `uv pip install --find-links /opt/bridge/wheels /opt/bridge/wheels/bridge-*.whl`. Idempotent on `Sandbox.bridge_wheel_sha` (combined sha of all uploaded wheels). Bridge entrypoint: `/opt/bridge/.venv/bin/python -m bridge.main`.
18. **`AgentEvent` widening + `Task → Chat` rename.** Slice 5a's `AgentEvent` carries `task_id, seq, payload, created_at`; slice 8 renames `task_id → chat_id` and adds `claude_session_id: str | None`. Index changes to `(chat_id, claude_session_id, seq)`. The `seq_counters` collection's keying changes from `_id=task_id` to `_id="{chat_id}:{claude_session_id or '_global'}"`. Slice 5a left a stub `Task` collection with a handful of dev rows — slice 8 renames + migrates. The web subscription endpoint flips from `/ws/web/tasks/{task_id}` to `/ws/web/chats/{chat_id}`.
19. **Bridge-token rotation** is `POST /api/sandboxes/{id}/rotate-bridge-token`, gated by `ALLOW_INTERNAL_ENDPOINTS`. v1 ops surface (rate limit, audit log) is post-v1; the endpoint exists for tests + emergency manual rotation.

---

## Context from slices 5b, 6, 7

Read [slice5b.md](slice5b.md), [slice6.md](slice6.md), [slice7.md](slice7.md) before starting. Key things slice 8 builds on:

- **5b** Provider Protocol has `exec_oneshot`, `fs_list`, `fs_read`, `fs_write`, `fs_delete`, `snapshot`, `restore`. Slice 8 uses `fs_write` for wheel upload + `exec_oneshot` for bridge launch; agent work itself goes through the bridge↔WSS leg.
- **5b** Reconciliation places repos at `/work/<full_name>/` reliably. Git is configured at fixed paths (`/etc/octo-canvas/gitconfig`); every git op exports `GIT_CONFIG_GLOBAL`.
- **6** ships the IDE shell. The orchestrator's `/api/sandboxes/{id}/fs` (REST) and `/ws/web/sandboxes/{id}/pty/{terminal_id}` (PTY broker) are slice 6's surface; slice 8 reuses them. The chat panel in slice 6 is a dummy that slice 8 wires up.
- **7** ships sandbox tooling via the reconciler: apt baseline, Adoptium repo, nvm/pyenv/rbenv, system Node 20 + npm + `@anthropic-ai/claude-code@2.1.118`, rustup, Go install root. **Slice 8 (Phase 0a, already shipped)** extended this with `uv` + `/opt/bridge/.venv` (uv-managed Python 3.12, isolated from pyenv).
- **5a** `/ws/web/tasks/{task_id}` + `seq`-replay from Mongo + Redis pub/sub on `task:{task_id}` are the FE wire. Slice 8 widens the producer side (bridge frames → `agent_events` rows → the chat channel) and renames `task_id → chat_id` everywhere.
- **5a** Wire-protocol JSON-Schema → `wire.d.ts` codegen pipeline. Slice 8 adds `bridge.py` as a sibling of `events.py` + `commands.py`.
- **Strict bar:** Pyright strict + TS strict + `noUncheckedIndexedAccess`. `pnpm --filter @octo-canvas/api-types gen:api-types` regenerates `wire.d.ts` covering web + bridge unions.

---

## What "done" looks like

After this slice, a developer with a connected repo can:

1. Sign in, ensure their sandbox is `warm` and a repo is cloned.
2. **(User agent ON, default)** Open `/_authed/sandbox`, open the chat panel, type "add a HELLO.md to repo-a".
3. Watch a unified transcript stream:
   - `UserAgentEnhancement{summary:"using project preferences from memory"}` (collapsible)
   - `AssistantMessage` blocks streaming as the dev agent thinks
   - `ToolCallStarted{tool:"Write", args:{...}}`, collapsed by default
   - `FileEditEvent{path:"repo-a/HELLO.md", before_sha:null, after_sha:"...", summary:"+1 -0"}` with inline diff preview
   - `ToolCallStarted{tool:"Bash", args:{cmd:"git -C /work/owner/repo-a add -A && git commit -m '...'"}}`
   - `TokenUsageEvent{input_delta:..., output_delta:...}`
   - `StatusChangeEvent("completed")`
4. Verify in Mongo: `Chat.claude_session_id` is populated, `ChatTurn(is_follow_up=false)` is `completed`, `user_agent_memory` got a `project_repo-a` row written.
5. Send a follow-up "make it a heading 1" → second `ChatTurn(is_follow_up=true)`, **same `claude_session_id`**, second commit on the same chat.
6. **Clarification round-trip with auto-answer**: prompt "what color theme do you prefer?" → dev agent calls `ask_user_clarification` → user agent reads memory → sees `prefs.md` says "dark" → emits `AgentAnsweredClarification{question:"...", proposed_answer:"dark", reason:"from prefs.md"}` → FE shows the answer with a 10s "Override?" countdown → countdown expires → `AnswerClarification{text:"dark"}` sent to bridge → dev agent unblocks.
7. **Manual clarification**: prompt "what's your favorite ASCII banner?" → user agent decides "no memory hit, ask the human" → FE shows manual reply box → user types → `AnswerClarification` sent.
8. **(User agent OFF)** Toggle off in settings → next chat: user message goes straight to bridge, full dev-agent stream (thinking + tool calls + everything) renders on the FE, no memory writes, clarifications go straight to manual reply.
9. **Multi-chat per sandbox**: open three chats concurrently, each with its own `ClaudeSDKClient`. Open a 6th → LRU eviction kicks in (verifiable via bridge log + `agent_events`).
10. **Resilience**:
    - Force-kill the orchestrator mid-turn → bridge buffers events; orchestrator restart → bridge `Hello{last_acked_seq_per_chat}` replays missed frames; `agent_events` shows continuous `seq`.
    - `pkill -f bridge.main` mid-turn → CLI subprocess dies; on next user message the chat re-spawns via `resume=claude_session_id`; transcript intact.
    - Tab close + reopen during the run → FE `Resume{after_seq}` catches up via Mongo.
11. **Auth checks**:
    - Wrong `BRIDGE_TOKEN` on bridge handshake → close `4001`.
    - Right token but `sandbox_id` mismatch → close `4003`.
    - Web client subscribes to a chat they don't own → close `4003`.
12. **Sprite-side audit**: `env | grep -i anthrop` shows only `CLAUDE_CODE_API_BASE_URL`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`. Real `sk-ant-...` absent. `cat /proc/$(pgrep -f bridge)/environ | tr '\0' '\n' | grep -i sk-ant` returns nothing.
13. `pnpm typecheck && pnpm lint && pnpm test && pnpm build` and orchestrator + bridge pytest all green.

---

## What to build

### 0. Sandbox bridge runtime — `apps/orchestrator/src/orchestrator/services/reconciliation.py` + `services/bridge_wheel.py`

**Phase 0a — shipped.** Reconciler `_BRIDGE_SETUP_REST` extended with `uv` system install + `/opt/bridge/.venv` creation (uv-managed Python 3.12, `--python-preference only-managed`, isolated from pyenv). `BRIDGE_SETUP_FINGERPRINT` bumped to include `venv-py=3.12`. `/opt/bridge` chowned to sprite user.

**Phase 0b — to build.** New `services/bridge_wheel.py` builds the bridge + workspace-deps wheels (`uv build --all-packages --out-dir <tmp>`) lazily on first use and caches them per orchestrator process keyed on a source-tree fingerprint. New reconciler step `_install_bridge_wheel(sandbox)` runs *after* `_bridge_setup_rest` and:
1. Computes combined sha of all wheels.
2. If `Sandbox.bridge_wheel_sha == combined_sha` → no-op.
3. Else: `fs_write` each wheel to `/opt/bridge/wheels/<name>.whl`, then `exec_oneshot('/opt/bridge/.venv/bin/uv pip install --find-links /opt/bridge/wheels /opt/bridge/wheels/bridge-*.whl --force-reinstall')`. Persist `Sandbox.bridge_wheel_sha`.

`Sandbox` doc gains `bridge_wheel_sha: str | None = None`.

### 1. Wire protocol — `python_packages/shared_models/src/shared_models/wire_protocol/bridge.py`

Two discriminated unions:

- `BridgeToOrchestrator` — `Hello`, `Goodbye`, `ChatStarted`, `ChatEvicted`, `AssistantMessage`, `ThinkingBlock`, `ToolCallStarted`, `ToolCallFinished`, `FileEditEvent`, `ShellExecEvent`, `TokenUsageEvent`, `StatusChangeEvent`, `AskUserClarification`, `ResultMessage`, `ErrorEvent`, `Pong`. Event-class members carry `chat_id: str` + `seq: int`; connection-class skip them.
- `OrchestratorToBridge` — `ChatState`, `UserMessage`, `AnswerClarification`, `CancelChat`, `PauseChat`, `SessionEnv` (declared, unused in v1), `Ack`, `Ping`. Inbound commands carry `frame_id: str` for idempotency.

Pydantic v2 `Field(discriminator='type')`; `model_config = ConfigDict(extra="ignore")` on every variant for forward-compat. `BridgeToOrchestratorAdapter = TypeAdapter(BridgeToOrchestrator)` and dual.

Extend `python_packages/shared_models/src/shared_models/scripts/gen_wire_schema.py` to dump both adapters.

### 2. Beanie model widening — `python_packages/db/src/db/models/`

- `chat.py` (replaces slice-5a `task.py`) — `user_id`, `title`, `status` (literal: `pending|running|awaiting_input|completed|failed|cancelled|archived`), `initial_prompt`, `claude_session_id: str | None`, `token_budget_input/output`, `last_alive_at`, `cold_since_at`, `created_at`. Index `(user_id, status, created_at)`. **No `repo_id`, no `branch`, no `pr_number`** — those are slice-9 concerns.
- `chat_turn.py` — new collection. `chat_id`, `is_follow_up: bool`, `prompt`, `enhanced_prompt: str | None`, `status`, `started_at`, `ended_at`, `token_input/output`, `error: str | None`. Index `(chat_id, started_at)`.
- `agent_event.py` — rename `task_id → chat_id`; add `claude_session_id: str | None`. Index `(chat_id, claude_session_id, seq)`.
- `seq_counter.py` — re-key `_id` to `f"{chat_id}:{claude_session_id or '_global'}"`. One-time migration script.
- `sandbox.py` — add `bridge_wheel_sha: str | None`, `bridge_version: str | None`, `bridge_connected_at: datetime | None`, `bridge_last_acked_seq_per_chat: dict[str, int] = Field(default_factory=dict)`. (`bridge_token_hash` already exists from slice 7.)
- `user.py` — add `claude_auth_mode: Literal[...] = "platform_api_key"`, `user_agent_enabled: bool = True`, `user_agent_model: str = "claude-haiku-4-5"`.
- `user_agent_memory.py` — new collection. `user_id`, `name`, `kind: Literal["index","user","feedback","project","reference"]`, `description: str`, `body: str`, `updated_at`. Unique index `(user_id, name)`.

Register in `db/mongo.py:_DOCUMENT_MODELS`. New typed accessors `mongo.chats`, `mongo.chat_turns`, `mongo.user_agent_memory`. Add `Collections.CHATS`, `CHAT_TURNS`, `USER_AGENT_MEMORY`. Drop `Collections.TASKS`.

### 3. Event store — `apps/orchestrator/src/orchestrator/services/event_store.py`

Widen `append_event(chat_id, claude_session_id, payload, *, redis)`:

1. Allocate seq atomically against `_id=f"{chat_id}:{claude_session_id or '_global'}"`.
2. Insert `AgentEvent(chat_id, claude_session_id, seq, payload, created_at)`.
3. Publish to `chat:{chat_id}`.
4. **If user agent enabled for this chat's user AND payload type is in the IMPORTANT set (#5)**: also publish to `chat:{chat_id}:ua` so the user-agent service on this instance picks it up. (The user-agent service is an in-process consumer; it filters its own subscription.)
5. Return the event.

Add `ack_bridge_chat(sandbox_id, chat_id, seq)` — writes `Sandbox.bridge_last_acked_seq_per_chat[chat_id] = seq`.

### 4. Anthropic reverse proxy — `apps/orchestrator/src/orchestrator/routes/anthropic_proxy.py`

The slice-7 invariant ("real Anthropic key never enters the sprite") rests on this route. Implementation contract is locked; do not deviate.

- Route: `@router.api_route("/api/_internal/anthropic-proxy/{sandbox_id}/{path:path}", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"], include_in_schema=False)`.
- Auth: read `Authorization: Bearer <token>`; reject if missing. `hashlib.sha256(token).hexdigest()` + `hmac.compare_digest` against `Sandbox(sandbox_id).bridge_token_hash`. 401 on any mismatch (single response — no diagnostic detail to deny probe info).
- Real-key swap: strip `Authorization` from inbound; set outbound `x-api-key: <real>` from `request.app.state.bridge_config._anthropic_api_key`. 503 on missing real key.
- Lifespan: `app.state.anthropic_proxy_client = httpx.AsyncClient(http2=True, timeout=httpx.Timeout(connect=10, read=600, write=60, pool=10))` started in `app.lifespan`, `await client.aclose()` on shutdown.
- Async streaming end-to-end (the *only* acceptable shape):
  - Inbound body: `content=request.stream()` — never `request.body()`/`request.json()`.
  - Upstream: `req = client.build_request(method=request.method, url=upstream_url, headers=swapped_headers, content=request.stream()); upstream = await client.send(req, stream=True)` — never `client.post(...)`.
  - Response: `async def relay(): try: async for chunk in upstream.aiter_raw(): yield chunk; finally: await upstream.aclose()` wrapped in `StreamingResponse(relay(), status_code=upstream.status_code, headers=filtered_outbound, background=BackgroundTask(upstream.aclose))`.
  - Inject `Cache-Control: no-cache` + `X-Accel-Buffering: no` so any nginx in front doesn't buffer SSE.
- Header filtering (both directions): drop hop-by-hop (`connection`, `keep-alive`, `proxy-authenticate`, `proxy-authorization`, `te`, `trailers`, `transfer-encoding`, `upgrade`, `host`, `content-length`) + `authorization` + `x-api-key`. Forward `anthropic-version`, `anthropic-beta`, `content-type`, etc.
- Path / query: forward `path` verbatim; preserve `request.url.query`.
- Cancellation: bridge disconnect → handler cancelled → `finally: aclose()` → upstream HTTP/2 RST → Anthropic stops billing.
- Error mapping: upstream 5xx + `httpx.RequestError` → 502; real-key missing → 503; auth failure → 401. Never echo upstream error bodies that might mention key prefixes.
- **Async-correctness audit:** nothing in the module imports `requests`, `urllib`, or `time.sleep`. CI grep should fail on those imports in this file.

### 5. Bridge WSS handler — `apps/orchestrator/src/orchestrator/ws/bridge.py`

`@router.websocket("/ws/bridge/{sandbox_id}")`:

1. Accept the WS first (FastAPI 4xxx codes only meaningful post-accept).
2. Read `Authorization: Bearer ...`; sha256 → compare against `Sandbox.bridge_token_hash`. Mismatch → close `4001`. Sandbox `destroyed` → close `4003`.
3. Spawn a `BridgeSession` task. Three concurrent loops via `asyncio.TaskGroup`:
   - `read_inbound`: validate `BridgeToOrchestrator`, persist via `event_store.append_event`, ack via `Ack{ack_seq}` periodically.
   - `pump_outbound`: read commands from a queue (filled by `BridgeOwner` Redis subscription + direct in-process appends), serialize, send.
   - `heartbeat`: 30s `Ping`, 90s rx-deadline.
4. Claim ownership: `redis.set(f"bridge_owner:{sandbox_id}", instance_id, ex=60, nx=True)`. Existing owner → close `4009`.
5. Refresh ownership every 20s; release on disconnect.

### 6. Bridge owner / cross-instance routing — `services/bridge_owner.py`

Per-instance singleton, started in lifespan. Subscribes to `bridge_in:*`; for each frame, looks up the local `BridgeSession` (deliver) or drops. Publishes outbound commands from non-owner instances via `redis.publish(f"bridge_in:{sandbox_id}", payload)`. Provides `async def send_to_bridge(sandbox_id, frame) -> None`.

### 7. Chat service + user agent — `services/chat_runner.py` + `services/user_agent/`

`chat_runner.py`:
- `create_chat(user, prompt) -> Chat`: create `Chat`, run user-agent enhancement (if enabled), create `ChatTurn(is_follow_up=False)`, send `UserMessage{chat_id, text=enhanced_text, claude_session_id=None}` to bridge.
- `add_follow_up(chat, prompt) -> ChatTurn`: same shape, with known `claude_session_id`.
- `cancel_chat(chat)`: send `CancelChat`, mark turn `cancelled`.

`services/user_agent/`:
- `service.py` — `UserAgentService` per-instance singleton. Subscribes to `chat:*:ua` (filtered events). Maintains a per-chat in-memory `anthropic.AsyncAnthropic` conversation. On `AskUserClarification`: ask Haiku "can you answer this from memory? if so, give the answer + a 1-line reason". If yes → emit `AgentAnsweredClarification{chat_id, clarification_id, proposed_answer, reason, override_deadline_at}` → schedule a 10s timer; on expiry, send `AnswerClarification` to bridge (unless overridden).
- `memory.py` — `memory_list/read/write/delete` over `mongo.user_agent_memory`. Used both by the user agent's tool-calls and by enhancement.
- `enhance.py` — `enhance_prompt(user, raw_prompt) -> EnhancedPrompt` returns `{enhanced_text, used_topics: list[str]}`. Cheap Haiku call: "given this user prompt and these memory topic descriptions, return the original prompt unchanged unless adding context from a specific topic genuinely helps." Strong default to passthrough.
- `filter.py` — `is_important(payload) -> bool` for §5 routing.

### 8. Routes — `apps/orchestrator/src/orchestrator/routes/chats.py`

- `POST /api/chats` — body `{prompt}`. Returns `ChatResponse`.
- `GET /api/chats` — list paginated.
- `GET /api/chats/{chat_id}` — single.
- `POST /api/chats/{chat_id}/messages` — follow-up.
- `POST /api/chats/{chat_id}/cancel`.
- `POST /api/chats/{chat_id}/clarifications/{clarification_id}/answer` — manual answer (also overrides a pending agent-answer).
- `PATCH /api/me/settings` — body `{user_agent_enabled?, user_agent_model?}`.

Plus dev-only `POST /api/sandboxes/{id}/rotate-bridge-token` behind `ALLOW_INTERNAL_ENDPOINTS`.

`/ws/web/chats/{chat_id}` (renamed from `/ws/web/tasks/{task_id}`).

### 9. Bridge process — `apps/bridge/src/bridge/`

```
apps/bridge/src/bridge/
├── main.py             # entrypoint; reads env; constructs WsClient + ChatMux; runs forever
├── ws_client.py        # WSS dialer; ring buffer; reconnect; Hello/Ack/Ping
├── chat_mux.py         # ClaudeSDKClient per chat; spawn/evict/route logic
├── ringbuf.py          # per-chat 1000-frame / 1MB ring
├── credentials/        # already in slice 7 — re-export
└── mcp/
    └── octo_server.py  # in-process MCP server with ask_user_clarification
```

`chat_mux.py` orchestrates per-chat `ClaudeSDKClient`s:

- On `UserMessage`: if no live client for `chat_id`, check eviction (LRU + cap); spawn a new client with `cwd=/work/`, `resume=claude_session_id` (None on first turn), `system_prompt=render_dev_agent_prompt(...)`, `allowed_tools=[...]`, `permission_mode="acceptEdits"`, `mcp_servers={"octo": create_octo_server(self)}`, `hooks=[HookMatcher("PreToolUse", "Bash", _bash_jail), HookMatcher("PreToolUse", "Write|Edit", _path_jail)]`.
- Stream `client.receive_response()`, translate each SDK message to a `BridgeToOrchestrator` frame, push to ws_client's outbound queue.
- Capture `claude_session_id` from `ResultMessage.session_id`; emit `ChatStarted` on first capture.
- Handle `CancelChat` → call `client.interrupt()` then close.

### 10. System prompt — `python_packages/agent_config/src/agent_config/dev_agent/prompt.py`

Already exists from slice 7 (`render_dev_agent_prompt`). Slice 8 widens its inputs to include the per-chat repo list (since chats run at `/work/` root, the prompt enumerates the available repos with their introspection summaries) and adjusts the rules: don't push to base branch, don't `rm -rf /`, don't reach outside `/work/`, call `ask_user_clarification` when truly blocked.

### 11. Frontend — `apps/web/`

- `src/routes/_authed/sandbox/index.tsx` — slice-6 IDE. Right-panel chat region wired to live chats list. "New chat" CTA prompts for initial message.
- `src/components/ide/ChatsPanel.tsx` — replaces the slice-6 dummy. Tabs: Active chats list. Click → opens transcript.
- `src/components/ide/ChatTranscript.tsx` — unified streaming transcript. Per-event renderers:
  - `AssistantMessage` — markdown, streaming text.
  - `ThinkingBlock` — collapsible "Thinking…" gray block.
  - `ToolCallStarted` + `ToolCallFinished` — collapsible card with args + result.
  - `FileEditEvent` — inline diff preview (`packages/diff` or a tiny custom highlighter).
  - `AskUserClarification` + `AgentAnsweredClarification` — inline answer card with 10s override countdown.
  - `UserAgentEnhancement` — collapsible "Context added by user agent" gray block.
  - `TokenUsageEvent` — small chip in the chat footer (cumulative).
- `src/components/ide/ClarificationCard.tsx` — manual answer form OR auto-answered + override countdown.
- `src/lib/chats.ts` — `createChat`, `addFollowUp`, `cancelChat`, `answerClarification`.
- `src/routes/_authed/settings.tsx` — `user_agent_enabled` toggle, `user_agent_model` select.

Light theme only ([AGENTS.md §2.8](../../AGENTS.md)).

### 12. Tests

Bridge unit (`apps/bridge/tests/`):
- `test_chat_mux.py`: spawn → message → ResultMessage → frames; eviction at cap; LRU pick; resume path.
- `test_ringbuf.py`: 1000-frame eviction, 1MB byte-size eviction, replay-after-ack.
- `test_ws_client.py`: reconnect with `Hello{last_acked_seq_per_chat}`, ack pruning, idempotent inbound `frame_id`.
- `test_mcp_clarification.py`: tool-blocks-on-future, future resolves on AnswerClarification, 5-min timeout.

Orchestrator (`apps/orchestrator/tests/`):
- `test_ws_bridge_handshake.py`: bad token → 4001; valid → ownership claimed in Redis.
- `test_ws_bridge_replay.py`: 5 frames, `Ack{3}`, disconnect, reconnect with `Hello{3}` → 4,5 replayed.
- `test_chat_create.py`: happy path creates `Chat` + `ChatTurn` + sends `UserMessage` to mocked bridge.
- `test_chat_followup.py`: second message reuses `claude_session_id`.
- `test_user_agent_enhance.py`: passthrough by default; enhances when relevant memory exists; mocked Haiku.
- `test_user_agent_clarification.py`: auto-answer with override countdown; manual override before deadline; deadline expiry sends auto-answer.
- `test_user_agent_filter.py`: `is_important` returns False for streaming deltas/thinking/tool-calls; True for clarification/result/error.
- `test_anthropic_proxy.py`: 401 single response shape; bearer-bearer swap; SSE non-buffering; cancellation propagation; static-import audit.
- `test_bridge_owner.py`: cross-instance command routing via Redis.
- `test_bridge_wheel.py`: build cache by source fingerprint; combined sha stable across rebuilds with same source.

Full-stack smoke (manual, documented):
- One real sprite, one orchestrator, one web tab. File a chat → see edits + commits. Follow-up. Toggle user agent off → re-run → all events stream raw.
- Inside the sprite: env audit per #13 above.

---

## Out of scope (explicit)

- **Git push + PR creation**: slice 9.
- **Per-repo branches / worktrees**: removed; chats run at `/work/` root.
- **Hard token-budget enforcement**: warning events only in slice 8.
- **OAuth / BYOK Claude credentials**: Protocol exists; impls don't.
- **Bridge-token rotation as ops surface**: endpoint behind `ALLOW_INTERNAL_ENDPOINTS` only.
- **24h Mongo / S3 archive**: slice 11.
- **Full LLM-driven memory curation prompts**: v1 ships dumb passthrough enhancement + simple memory tools; the *prompt engineering* for what to memorize will iterate post-slice.
- **In-browser LLM calls**: never; FE is UX-only.
- **Vector / embedding memory retrieval**: post-v1; v1 is `memory_list` + LLM picks topics by name+description.

---

## Risks

1. **User-agent context bloat over a long chat.** Even filtered to important events, a long session accumulates `ResultMessage`s and clarifications. Mitigation: each user-agent turn is its own short-lived API call (system prompt + last few important events + relevant memory excerpts), NOT a long-running streaming session. The user agent is stateless across events from its own perspective; state lives in Mongo memory. If context still grows: lower the "important" filter threshold further, or summarize via Haiku.
2. **CLI binary version drift.** Pin in `apps/bridge/CLAUDE_CLI_VERSION` checked at bridge boot; refuse to start on mismatch.
3. **Bridge-owner failover under churn.** `set NX EX 60` is atomic; loser closes `4009` and the bridge reconnects. Worst-case: a few seconds of dropped commands → Mongo replay fixes any web-side gap; bridge ring buffer fixes any bridge-side gap.
4. **MCP `ask_user_clarification` deadlock.** 5-min hard timeout. Bridge logs open-clarifications every 60s.
5. **CLI cache miss on evict-resume.** Evicted chats re-pay prompt cache on next `--resume`. Acceptable for v1; revisit if eviction frequency grows.
6. **`acceptEdits` permission mode is permissive.** Hooks are the safety net (Bash jail, path validation). Add a test per rejected pattern.
7. **Concurrent chats touching the same repo.** Allowed in v1, no worktree mitigation. Foot-gun acknowledged. If two chats step on each other, the second's commits will fail (dirty index, merge conflicts) and the dev agent's `ask_user_clarification` should surface it. Revisit if it bites.
8. **Wire schema evolution.** `extra="ignore"` per variant is the forward-compat lever. Old bridges seeing new orchestrator commands MUST gracefully ignore unknown types. Test explicitly.
9. **Bridge reconnect storms after orchestrator deploy.** Jittered backoff (1→16s ±25%) reusing slice 5a's util.
10. **`Sandbox.bridge_last_acked_seq_per_chat` doc growth.** Cleanup job: prune entries for chats `completed`/`failed`/`cancelled`/`archived` older than 7d. TODO; cleanup lands with slice 11.
11. **Wheel-build cost on every orchestrator restart.** ~5s. Cached after first build. CI doesn't run the build (it doesn't need a sprite).
12. **In-flight `UserMessage` lost if the owning instance crashes mid-forward.** Mitigation: write the `ChatTurn` row first, then send; on boot, scan for `ChatTurn(status="queued")` and re-send. Idempotency on `frame_id` prevents double-execution.
13. **User-agent memory schema drift.** v1 stores `body` as raw markdown — no migrations needed for content edits. If the kind enum ever expands, add the new literal and write a backfill noop.

---

## Acceptance — copy-paste checklist

- [ ] `pnpm typecheck` clean.
- [ ] `pnpm lint` clean.
- [ ] `pnpm --filter @octo-canvas/api-types gen:api-types` regenerates `wire.d.ts`; `pnpm typecheck` still clean.
- [ ] `uv run pytest apps/orchestrator/tests/` and `uv run pytest apps/bridge/tests/` both green. Required tests:
  - bridge handshake auth: 4001 / 4003 paths.
  - replay correctness on reconnect.
  - bridge-owner cross-instance routing.
  - chat-create + follow-up reuses session_id.
  - user-agent enhance default-passthrough + memory-driven enhancement.
  - user-agent clarification auto-answer + override countdown.
  - user-agent filter `is_important` behaviour.
  - frame_id idempotency.
  - eviction at cap + LRU pick + resume.
  - anthropic-proxy auth + key swap + SSE non-buffering + cancel + static audit.
  - bridge-wheel build cache.
- [ ] Manual smoke (real sprite + real Anthropic key): file a chat, see edits land. Follow-up. Cancel mid-run. Toggle user agent off → re-run direct. Force-restart orchestrator → bridge replays.
- [ ] Sprite-side audit: real `sk-ant-` absent from env / `/proc/<pid>/environ`.
- [ ] [docs/progress.md](../progress.md) updated.
- [ ] [docs/Contributions.md](../Contributions.md) entry added.
- [ ] [docs/agent_context.md](../agent_context.md) updated: dual-agent model in TL;DR; gotchas list user-agent filter rule + `MAX_LIVE_CHATS_PER_SANDBOX` + `/opt/bridge/.venv` isolation.
- [ ] User signs off → this brief is frozen; corrections live in `progress.md`.
