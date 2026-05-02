"""User agent — slice 8 §calls #2-#6.

Runs on the orchestrator BE. Drives:
- prompt enhancement (memory-aware) on outgoing user messages
- clarification auto-answer on incoming dev-agent questions

The user-agent code is provider-agnostic via `agent_config.LLMProvider`.
v1 wires Anthropic + Haiku 4.5; OpenAI / Gemini ship later.
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

__all__ = [
    "AnthropicProvider",
    "MemoryEntry",
    "delete_memory",
    "is_important_for_user_agent",
    "list_memory",
    "read_memory",
    "write_memory",
]
