"""Wire protocol for slice-6 per-sandbox channels.

These channels are SEPARATE WebSocket endpoints from the slice-5a task WS
(`/ws/web/tasks/{task_id}`). They do NOT ride on `OrchestratorToWeb` or
`WebToOrchestrator`:

- `/ws/web/sandboxes/{sandbox_id}/fs/watch` — emits `FileEditEvent` JSON
  frames as files change inside the sandbox. No client-to-server frames in
  slice 6 (subscription is implicit on the URL).
- `/ws/web/sandboxes/{sandbox_id}/pty/{terminal_id}` — bidirectional. Bytes
  flow as raw binary frames (xterm.js stdin/stdout, no JSON wrapper).
  Control messages — `ResizePty`, `RequestClosePty`, the server's
  `PtySessionInfo` / `PtyExit` — flow as JSON frames on the same socket.

`RequestOpenPty` is reserved for a future task-WS-driven PTY open path; in
slice 6 a PTY is opened simply by dialling the per-PTY URL. We declare it
in the schema so the wire bindings are stable when the task WS picks it up.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _ChannelMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ── /fs/watch ────────────────────────────────────────────────────────────


class FileEditEvent(_ChannelMessage):
    """One filesystem change observed inside the sandbox. Emitted by the
    orchestrator's fs-watch broker after coalescing per [Plan.md §10.6]."""

    type: Literal["file.edit"] = "file.edit"
    path: str
    kind: Literal["create", "modify", "delete", "rename"]
    is_dir: bool = False
    size: int | None = None
    # ms since epoch — the orchestrator stamps its own arrival time so
    # subscribers don't need to trust Sprites' clock.
    timestamp_ms: int


class FsWatchSubscribed(_ChannelMessage):
    """Sent immediately after the channel handshake completes so the FE has
    a deterministic point to remove its 'connecting…' state."""

    type: Literal["fswatch.subscribed"] = "fswatch.subscribed"
    sandbox_id: str
    root_path: str


FsWatchToWeb = Annotated[
    FileEditEvent | FsWatchSubscribed,
    Field(discriminator="type"),
]


# ── /pty/{terminal_id} ───────────────────────────────────────────────────


class ResizePty(_ChannelMessage):
    """Web → orchestrator: tell the underlying PTY its new dimensions. The
    orchestrator forwards verbatim to Sprites' Exec channel."""

    type: Literal["pty.resize"] = "pty.resize"
    cols: int = Field(ge=1, le=10000)
    rows: int = Field(ge=1, le=10000)


class RequestOpenPty(_ChannelMessage):
    """Reserved for a future task-WS-driven PTY open. Slice 6 opens PTYs by
    dialling the per-PTY URL directly; this frame is unused on the wire
    until the task WS gains PTY-control responsibilities."""

    type: Literal["pty.open"] = "pty.open"
    sandbox_id: str
    terminal_id: str
    cwd: str | None = None
    cols: int = 80
    rows: int = 24


class RequestClosePty(_ChannelMessage):
    """Web → orchestrator: kill this PTY (the user closed the terminal tab).
    The orchestrator drops its Sprites Exec session and clears the Redis
    reattach record."""

    type: Literal["pty.close"] = "pty.close"
    terminal_id: str


WebToPty = Annotated[
    ResizePty | RequestOpenPty | RequestClosePty,
    Field(discriminator="type"),
]


class PtySessionInfo(_ChannelMessage):
    """Orchestrator → web: emitted once after the upstream Sprites Exec
    session is up. Mirrors Sprites' `session_info` plus the orchestrator's
    own correlation id so reattach can be reasoned about end-to-end."""

    type: Literal["pty.session_info"] = "pty.session_info"
    terminal_id: str
    sprites_session_id: str
    cols: int
    rows: int
    reattached: bool


class PtyExit(_ChannelMessage):
    """Orchestrator → web: the upstream shell exited. The web side typically
    leaves the tab open so the user can read final output, then closes the
    socket on user action."""

    type: Literal["pty.exit"] = "pty.exit"
    terminal_id: str
    exit_code: int


PtyToWeb = Annotated[
    PtySessionInfo | PtyExit,
    Field(discriminator="type"),
]


# Adapters — the schema-gen script consumes these; runtime handlers use them
# to validate incoming JSON frames.
FsWatchToWebAdapter: TypeAdapter[FsWatchToWeb] = TypeAdapter(FsWatchToWeb)
WebToPtyAdapter: TypeAdapter[WebToPty] = TypeAdapter(WebToPty)
PtyToWebAdapter: TypeAdapter[PtyToWeb] = TypeAdapter(PtyToWeb)
