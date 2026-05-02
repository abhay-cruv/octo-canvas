"""Wire protocol for `/ws/web/tasks/{task_id}` (slice 5a).

The two `TypeAdapter`s exported here are the canonical serializer/parser for
both directions of the channel. WS handlers MUST go through them rather than
calling `model_dump_json` on a specific variant — keeps the discriminator
field correct and makes new variants automatically wire-compatible.
"""

from pydantic import TypeAdapter

from shared_models.wire_protocol.commands import (
    ClientPing,
    ClientPong,
    Resume,
    WebToOrchestrator,
)
from shared_models.wire_protocol.events import (
    BackpressureWarning,
    DebugEvent,
    ErrorEvent,
    OrchestratorToWeb,
    Pong,
    SandboxStatusEvent,
    ServerPing,
    StatusChangeEvent,
)
from shared_models.wire_protocol.sandbox_channels import (
    FileEditEvent,
    FsWatchSubscribed,
    FsWatchToWeb,
    FsWatchToWebAdapter,
    PtyExit,
    PtySessionInfo,
    PtyToWeb,
    PtyToWebAdapter,
    RequestClosePty,
    RequestOpenPty,
    ResizePty,
    WebToPty,
    WebToPtyAdapter,
)

OrchestratorToWebAdapter: TypeAdapter[OrchestratorToWeb] = TypeAdapter(OrchestratorToWeb)
WebToOrchestratorAdapter: TypeAdapter[WebToOrchestrator] = TypeAdapter(WebToOrchestrator)

__all__ = [
    "BackpressureWarning",
    "ClientPing",
    "ClientPong",
    "DebugEvent",
    "ErrorEvent",
    "FileEditEvent",
    "FsWatchSubscribed",
    "FsWatchToWeb",
    "FsWatchToWebAdapter",
    "OrchestratorToWeb",
    "OrchestratorToWebAdapter",
    "Pong",
    "PtyExit",
    "PtySessionInfo",
    "PtyToWeb",
    "PtyToWebAdapter",
    "RequestClosePty",
    "RequestOpenPty",
    "ResizePty",
    "Resume",
    "SandboxStatusEvent",
    "ServerPing",
    "StatusChangeEvent",
    "WebToOrchestrator",
    "WebToOrchestratorAdapter",
    "WebToPty",
    "WebToPtyAdapter",
]
