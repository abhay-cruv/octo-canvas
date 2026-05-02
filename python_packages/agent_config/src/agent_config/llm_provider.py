"""Provider-agnostic LLM Protocol — slice 8 §calls #3.

The user agent on the orchestrator (BE) drives prompt enhancement +
clarification auto-answer. v1 ships the `AnthropicProvider` impl
(against `claude-haiku-4-5` by default); OpenAI + Gemini land later as
additional impls + a `User.user_agent_provider` flip — no schema
migration.

Every method is async + non-blocking. The provider must NOT spawn its
own threads / processes — it shares the orchestrator's event loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class LLMMessage:
    role: Literal["user", "assistant", "system"]
    content: str


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass(frozen=True)
class LLMCompletion:
    """Result of a non-streaming `complete()` call."""

    text: str
    usage: LLMUsage
    model: str
    stop_reason: str | None = None


class LLMProvider(Protocol):
    """Provider-agnostic LLM caller used by the user agent.

    Implementations:
    - `orchestrator.services.user_agent.providers.AnthropicProvider` (v1)
    - OpenAI / Gemini ship later as additional impls + a settings flip.

    The Protocol deliberately exposes a small surface — the user agent
    doesn't need tool calls or vision in v1. If/when those land, add
    them as separate methods, not as kwargs on `complete()` (avoids
    breaking older impls).
    """

    name: str
    """Stable provider identifier (e.g. `"anthropic"`). Matches
    `User.user_agent_provider` enum values."""

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMCompletion:
        """One-shot completion. Non-streaming — the user agent's
        decisions are short and don't benefit from streaming UX."""
        ...

    def stream(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        """Streaming completion — yields text deltas. Reserved for a
        future "user agent thinks out loud" UX; v1 callers use
        `complete()`."""
        ...
