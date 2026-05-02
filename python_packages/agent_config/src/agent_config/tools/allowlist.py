"""Canonical tool allowlist for the dev agent.

Slice 8's bridge passes this list to `claude-agent-sdk` when spawning
a session so the CLI restricts itself to these tools. Slice 7 just
freezes the list so slice 8 has a stable import.

`ask_user_clarification` is the in-process MCP tool the bridge
registers per [Plan.md §14.10](../../../../../docs/Plan.md); the others
are CLI built-ins.
"""

from __future__ import annotations

from typing import Final

DEV_AGENT_TOOL_ALLOWLIST: Final[tuple[str, ...]] = (
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    "ask_user_clarification",
)
