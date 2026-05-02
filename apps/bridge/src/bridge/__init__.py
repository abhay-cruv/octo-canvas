"""octo-canvas sprite-side bridge.

Boots inside every sprite. Slice 7 ships only the entrypoint
(`--self-check` / `--version` / idle loop) — slice 8 adds the WSS
client, session multiplexer, and `claude-agent-sdk` integration.
"""

__version__ = "0.1.0"
