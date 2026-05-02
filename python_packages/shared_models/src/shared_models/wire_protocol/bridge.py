"""Bridge ↔ orchestrator wire protocol — slice 8.

Two discriminated unions covering the `/ws/bridge/{sandbox_id}` channel:

- `BridgeToOrchestrator` — frames the bridge sends home (assistant text,
  thinking, tool calls, file edits, clarifications, status, errors,
  pong).
- `OrchestratorToBridge` — commands the orchestrator sends down (user
  messages, clarification answers, cancel/pause, env updates, ack/ping).

`extra="ignore"` per variant: forward-compat lever (slice 5a §risks #1).
Old bridges seeing new orchestrator commands MUST gracefully ignore
unknown types instead of crashing — and vice versa.

Event-class members carry `chat_id: str` + `seq: int`. Connection-class
(Hello/Goodbye/Pong/Ping) skip them. Inbound commands carry
`frame_id: str` for idempotency on replay.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _BridgeFrame(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ── Bridge → Orchestrator (events) ───────────────────────────────────


class Hello(_BridgeFrame):
    """First frame after WSS handshake. Carries the bridge's view of
    `last_acked_seq_per_chat` so the orchestrator can decide whether to
    request replay."""

    type: Literal["bridge.hello"] = "bridge.hello"
    bridge_version: str
    last_acked_seq_per_chat: dict[str, int] = Field(default_factory=dict)


class Goodbye(_BridgeFrame):
    """Sent by the bridge before a clean shutdown (sprite hibernate /
    process exit). Orchestrator can release Redis ownership immediately."""

    type: Literal["bridge.goodbye"] = "bridge.goodbye"
    reason: str


class BridgePong(_BridgeFrame):
    type: Literal["bridge.pong"] = "bridge.pong"


class ChatStarted(_BridgeFrame):
    """Emitted when a chat's underlying CLI session reports its
    `claude_session_id` for the first time (via `ResultMessage.session_id`).
    The orchestrator persists this onto `Chat.claude_session_id` so
    follow-ups can `--resume` without losing prompt cache."""

    type: Literal["chat.started"] = "chat.started"
    chat_id: str
    seq: int
    claude_session_id: str


class ChatEvicted(_BridgeFrame):
    """Bridge evicted this chat's CLI session (LRU cap reached). The
    next user message will cold-start via `--resume`."""

    type: Literal["chat.evicted"] = "chat.evicted"
    chat_id: str
    seq: int
    reason: Literal["lru_cap", "idle_grace", "archived", "explicit_cancel"]


class StatusChange(_BridgeFrame):
    type: Literal["chat.status"] = "chat.status"
    chat_id: str
    seq: int
    new_status: Literal[
        "pending", "running", "awaiting_input", "completed", "failed", "cancelled"
    ]


class AssistantMessageDelta(_BridgeFrame):
    """A streaming text fragment from the dev agent. Multiple of these
    interleave with `ThinkingBlock` and `ToolCallStarted` until the
    `ResultMessage` closes the turn."""

    type: Literal["assistant.delta"] = "assistant.delta"
    chat_id: str
    seq: int
    text: str


class BridgeAssistantMessage(_BridgeFrame):
    """Final non-streaming assistant block emitted at turn close. The
    full text of one assistant message — used by the user agent (it
    only sees `important` events, of which this is one)."""

    type: Literal["assistant.message"] = "assistant.message"
    chat_id: str
    seq: int
    text: str


class ThinkingBlock(_BridgeFrame):
    """Extended-thinking block. Filtered out from the user-agent stream
    (too noisy for Haiku) but rendered on the FE."""

    type: Literal["thinking"] = "thinking"
    chat_id: str
    seq: int
    text: str


class ToolCallStarted(_BridgeFrame):
    type: Literal["tool.started"] = "tool.started"
    chat_id: str
    seq: int
    tool_use_id: str
    tool_name: str
    args: dict[str, Any]


class ToolCallFinished(_BridgeFrame):
    type: Literal["tool.finished"] = "tool.finished"
    chat_id: str
    seq: int
    tool_use_id: str
    is_error: bool = False
    # Truncated to ~10 KB before sending. Full result is in the
    # transcript persisted by the SDK; FE renders this preview.
    result_preview: str


class BridgeFileEditEvent(_BridgeFrame):
    """Emitted after `Write` or `Edit` tool calls succeed. `before_sha`
    is null for newly created files."""

    type: Literal["file.edit"] = "file.edit"
    chat_id: str
    seq: int
    path: str
    before_sha: str | None
    after_sha: str
    summary: str  # e.g. "+12 -3"


class ShellExecEvent(_BridgeFrame):
    """Emitted after `Bash` tool calls finish — useful for the FE to
    show `git commit` / test runs / etc. as first-class events instead
    of generic tool calls."""

    type: Literal["shell.exec"] = "shell.exec"
    chat_id: str
    seq: int
    cmd: str
    exit_code: int
    stdout_tail: str  # last ~2 KB
    stderr_tail: str


class TokenUsageEvent(_BridgeFrame):
    """Per-`ResultMessage.usage` deltas. Per-chat budget enforcement
    lives in slice 8b — slice 8 emits warning events at 80%."""

    type: Literal["token.usage"] = "token.usage"
    chat_id: str
    seq: int
    input_delta: int
    output_delta: int
    cache_creation_delta: int = 0
    cache_read_delta: int = 0


class UserAgentSuggestion(_BridgeFrame):
    """The user agent (BE) decided to auto-answer the dev agent's most
    recent question. Informational frame for the FE — it shows the
    suggested reply with a countdown to `override_deadline_at`. If the
    user doesn't override, the orchestrator sends the suggested reply
    as a normal `UserMessage` to the bridge after the deadline.

    No round-trip needed at the bridge level — clarifications are just
    natural assistant text + next user message."""

    type: Literal["user_agent.suggestion"] = "user_agent.suggestion"
    chat_id: str
    seq: int
    suggestion_id: str
    suggested_reply: str
    reason: str
    override_deadline_at: str  # ISO-8601 UTC


class ResultMessage(_BridgeFrame):
    """End-of-turn marker from the SDK. Carries the session id (used
    for `--resume`) and the cumulative usage. The user agent treats
    this as the "important conclusion" event for filter purposes."""

    type: Literal["result"] = "result"
    chat_id: str
    seq: int
    claude_session_id: str
    duration_ms: int
    is_error: bool
    error: str | None = None


class BridgeErrorEvent(_BridgeFrame):
    """Bridge-side errors. `kind` lets the orchestrator route on
    well-known causes (`clarification_timeout`, `worktree_dirty_externally`,
    `cli_crash`, `cli_pin_mismatch`, ...)."""

    type: Literal["error"] = "error"
    chat_id: str
    seq: int
    kind: str
    message: str


BridgeToOrchestrator = Annotated[
    Hello
    | Goodbye
    | BridgePong
    | ChatStarted
    | ChatEvicted
    | StatusChange
    | AssistantMessageDelta
    | BridgeAssistantMessage
    | ThinkingBlock
    | ToolCallStarted
    | ToolCallFinished
    | BridgeFileEditEvent
    | ShellExecEvent
    | TokenUsageEvent
    | UserAgentSuggestion
    | ResultMessage
    | BridgeErrorEvent,
    Field(discriminator="type"),
]


# ── Orchestrator → Bridge (commands) ─────────────────────────────────


class BridgePing(_BridgeFrame):
    type: Literal["bridge.ping"] = "bridge.ping"


class Ack(_BridgeFrame):
    """Periodic acknowledgement of `(chat_id, ack_seq)`. The bridge
    drops persisted frames from its ring buffer up to `ack_seq` for the
    given chat."""

    type: Literal["bridge.ack"] = "bridge.ack"
    chat_id: str
    ack_seq: int


class ChatState(_BridgeFrame):
    """Reconciliation message the orchestrator sends in response to
    `Hello` — declares the canonical state for each chat the bridge
    reported. Used to converge after a reconnect.

    `last_seen_seq` tells the bridge "this is the highest seq I have
    persisted for this chat; resend anything beyond." A bridge with
    fewer frames than this can recover via Mongo replay (no-op locally)."""

    type: Literal["bridge.chat_state"] = "bridge.chat_state"
    chat_id: str
    last_seen_seq: int
    claude_session_id: str | None = None


class UserMessage(_BridgeFrame):
    """User-sent (or user-agent-enhanced) prompt for a chat. First
    message: `claude_session_id=None` and the bridge spawns a fresh
    `ClaudeSDKClient`. Follow-ups: the bridge feeds text to the live
    client OR `--resume`s if cold."""

    type: Literal["bridge.user_message"] = "bridge.user_message"
    chat_id: str
    frame_id: str
    text: str
    claude_session_id: str | None = None


class CancelChat(_BridgeFrame):
    """Hard interrupt: bridge calls `client.interrupt()` then closes."""

    type: Literal["bridge.cancel"] = "bridge.cancel"
    chat_id: str
    frame_id: str


class PauseChat(_BridgeFrame):
    """Soft pause: bridge stops feeding turns until `UserMessage` or
    `CancelChat` arrives. Slice 8 doesn't surface this in the UI but
    the wire variant is reserved."""

    type: Literal["bridge.pause"] = "bridge.pause"
    chat_id: str
    frame_id: str


class SessionEnv(_BridgeFrame):
    """Reserved for v1+ user-scoped credentials (OAuth / BYOK). v1
    bridges receive this and ignore the contents — `extra="ignore"`
    keeps them forward-compatible. Declared in the union so the
    schema is stable."""

    type: Literal["bridge.session_env"] = "bridge.session_env"
    chat_id: str
    frame_id: str
    env: dict[str, str] = Field(default_factory=dict)


OrchestratorToBridge = Annotated[
    BridgePing | Ack | ChatState | UserMessage | CancelChat | PauseChat | SessionEnv,
    Field(discriminator="type"),
]


BridgeToOrchestratorAdapter: TypeAdapter[BridgeToOrchestrator] = TypeAdapter(
    BridgeToOrchestrator
)
OrchestratorToBridgeAdapter: TypeAdapter[OrchestratorToBridge] = TypeAdapter(
    OrchestratorToBridge
)
