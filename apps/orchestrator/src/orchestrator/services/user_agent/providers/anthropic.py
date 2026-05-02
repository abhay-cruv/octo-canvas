"""Anthropic implementation of the `LLMProvider` Protocol — slice 8.

Used by the orchestrator-side user agent to drive prompt enhancement +
clarification auto-answer. Holds the real `ANTHROPIC_API_KEY` directly
(it's ON the orchestrator — the key never leaves this process). Bridge
talks to Anthropic via the reverse proxy; user agent talks directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from agent_config.llm_provider import (
    LLMCompletion,
    LLMMessage,
    LLMProvider,
    LLMUsage,
)
from anthropic import AsyncAnthropic


class AnthropicProvider(LLMProvider):
    name: str = "anthropic"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("AnthropicProvider requires a non-empty api_key")
        self._client = AsyncAnthropic(api_key=api_key)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMCompletion:
        # Anthropic's Messages API: `system` is a top-level kwarg
        # (not a role on the messages array).
        anth_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        kwargs: dict[str, object] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": anth_messages,
        }
        if system is not None:
            kwargs["system"] = system
        response = await self._client.messages.create(**kwargs)  # type: ignore[arg-type]
        # Concatenate text blocks. Anthropic may also return tool_use /
        # thinking blocks; v1 user-agent prompts don't request those.
        text_parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        text = "".join(text_parts)
        usage = LLMUsage(
            input_tokens=getattr(response.usage, "input_tokens", 0),
            output_tokens=getattr(response.usage, "output_tokens", 0),
            cache_creation_tokens=getattr(
                response.usage, "cache_creation_input_tokens", 0
            )
            or 0,
            cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0)
            or 0,
        )
        return LLMCompletion(
            text=text,
            usage=usage,
            model=response.model,
            stop_reason=response.stop_reason,
        )

    def stream(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        return self._stream(
            messages,
            system=system,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def _stream(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        anth_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        kwargs: dict[str, object] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": anth_messages,
        }
        if system is not None:
            kwargs["system"] = system
        async with self._client.messages.stream(**kwargs) as stream:  # type: ignore[arg-type]
            async for delta in stream.text_stream:
                yield delta
