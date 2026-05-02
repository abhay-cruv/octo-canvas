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

OrchestratorToWebAdapter: TypeAdapter[OrchestratorToWeb] = TypeAdapter(OrchestratorToWeb)
WebToOrchestratorAdapter: TypeAdapter[WebToOrchestrator] = TypeAdapter(WebToOrchestrator)

__all__ = [
    "BackpressureWarning",
    "ClientPing",
    "ClientPong",
    "DebugEvent",
    "ErrorEvent",
    "OrchestratorToWeb",
    "OrchestratorToWebAdapter",
    "Pong",
    "Resume",
    "SandboxStatusEvent",
    "ServerPing",
    "StatusChangeEvent",
    "WebToOrchestrator",
    "WebToOrchestratorAdapter",
]
