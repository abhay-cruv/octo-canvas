"""Dump the wire-protocol discriminated unions as JSON Schema.

Pipe the output to `json-schema-to-typescript` to produce the TS bindings
the web app imports from `@octo-canvas/api-types/generated/wire`. See
[slice5a.md §8](../../../../docs/slice/slice5a.md).

Usage:
    uv run python -m shared_models.scripts.gen_wire_schema > wire.schema.json
"""

import json
import sys
from typing import Any

from shared_models.wire_protocol import (
    BridgeToOrchestratorAdapter,
    FsWatchToWebAdapter,
    OrchestratorToBridgeAdapter,
    OrchestratorToWebAdapter,
    PtyToWebAdapter,
    WebToOrchestratorAdapter,
    WebToPtyAdapter,
)


def _hoist(adapter_schema: dict[str, Any], all_defs: dict[str, Any]) -> dict[str, Any]:
    """Pydantic emits each variant under `$defs`; pull them up to a shared
    top-level `definitions` so json-schema-to-typescript can resolve refs
    across both adapters."""
    inner_defs = adapter_schema.pop("$defs", {})
    for name, schema in inner_defs.items():
        all_defs[name] = schema
    return adapter_schema


def main() -> int:
    all_defs: dict[str, Any] = {}
    out_to_web = _hoist(OrchestratorToWebAdapter.json_schema(), all_defs)
    web_to_out = _hoist(WebToOrchestratorAdapter.json_schema(), all_defs)
    fs_watch = _hoist(FsWatchToWebAdapter.json_schema(), all_defs)
    pty_in = _hoist(WebToPtyAdapter.json_schema(), all_defs)
    pty_out = _hoist(PtyToWebAdapter.json_schema(), all_defs)
    bridge_to_orch = _hoist(BridgeToOrchestratorAdapter.json_schema(), all_defs)
    orch_to_bridge = _hoist(OrchestratorToBridgeAdapter.json_schema(), all_defs)
    all_defs["OrchestratorToWeb"] = out_to_web
    all_defs["WebToOrchestrator"] = web_to_out
    all_defs["FsWatchToWeb"] = fs_watch
    all_defs["WebToPty"] = pty_in
    all_defs["PtyToWeb"] = pty_out
    all_defs["BridgeToOrchestrator"] = bridge_to_orch
    all_defs["OrchestratorToBridge"] = orch_to_bridge

    blob = json.dumps(
        {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "OctoCanvasWireProtocol",
            "definitions": all_defs,
        }
    )
    # Rewrite Pydantic's "#/$defs/..." refs to our consolidated location.
    blob = blob.replace("#/$defs/", "#/definitions/")
    sys.stdout.write(blob + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
