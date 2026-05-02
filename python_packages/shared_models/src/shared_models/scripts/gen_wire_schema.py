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
    OrchestratorToWebAdapter,
    WebToOrchestratorAdapter,
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
    all_defs["OrchestratorToWeb"] = out_to_web
    all_defs["WebToOrchestrator"] = web_to_out

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
