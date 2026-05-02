"""User agent — slice 8 §calls #2-#6.

Runs on the orchestrator BE. Drives:
- prompt enhancement (memory-aware) on outgoing user messages
- "suggest a reply" on the dev agent's finalized assistant messages
  (when the dev agent ends a turn with a question, the user agent
  may auto-answer with a 10s override countdown — surfaced to FE as
  `UserAgentSuggestion`)

The user-agent code is provider-agnostic via `agent_config.LLMProvider`.
v1 wires Anthropic + Haiku 4.5; OpenAI / Gemini ship later as
additional impls + a settings flip.

**No custom MCP tool / clarification protocol.** Clarifications are
just natural assistant text + the next user message — same flow as
any chat turn. The user agent reads the filtered stream
(`assistant.message` + `result`) and decides.
"""

from orchestrator.services.user_agent.filter import is_important_for_user_agent
from orchestrator.services.user_agent.memory import (
    MemoryEntry,
    delete_memory,
    list_memory,
    read_memory,
    write_memory,
)
from orchestrator.services.user_agent.providers.anthropic import AnthropicProvider
from orchestrator.services.user_agent.suggest import (
    ReplySuggestion,
    suggest_reply,
)

__all__ = [
    "AnthropicProvider",
    "MemoryEntry",
    "ReplySuggestion",
    "delete_memory",
    "is_important_for_user_agent",
    "list_memory",
    "read_memory",
    "suggest_reply",
    "write_memory",
]
