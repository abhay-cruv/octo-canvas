"""User-agent prompt enhancement — slice 8 §calls #4.

Default behaviour is **passthrough**. Enhancement only happens when
the LLM (Haiku) decides relevant memory context would help. v1 ships
a minimal prompt; iteration on what to inject is post-slice.

The enhancement is rendered to the FE as a collapsible "User agent
context" block on the transcript — never invisible. If the LLM
errors, we log and pass through (the user shouldn't lose their
message because the user agent was unavailable).
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from agent_config.llm_provider import LLMMessage, LLMProvider
from beanie import PydanticObjectId

from orchestrator.services.user_agent.memory import list_memory, read_memory

_logger = structlog.get_logger("user_agent.enhance")


@dataclass(frozen=True)
class EnhancedPrompt:
    enhanced_text: str
    used_topics: list[str]


_ENHANCE_SYSTEM = """You are the BE-side user agent helping a developer chat with a coding assistant ("dev agent") that runs in a sandbox.

Your job for an outgoing user prompt: decide if injecting context from the user's memory would genuinely help. If so, return the prompt with a short context block prepended. If not, return the prompt unchanged.

Strong default to passthrough. Only enhance when there's a CONCRETE memory hit (e.g., the user has a stored preference for dark themes and is asking about UI work). Never invent context. Never paraphrase the user.

Return exactly this JSON, no prose:
{"enhanced": "<enhanced or original prompt>", "used_topics": ["topic-name", ...]}"""


async def enhance_prompt(
    user_id: PydanticObjectId,
    raw_prompt: str,
    *,
    provider: LLMProvider,
    model: str,
) -> EnhancedPrompt:
    """Decide whether to enhance the user's prompt with memory context.

    Returns an `EnhancedPrompt` — `used_topics=[]` when the model
    decides passthrough. Failures fall through to passthrough."""
    topics = await list_memory(user_id)
    if not topics:
        return EnhancedPrompt(enhanced_text=raw_prompt, used_topics=[])
    topic_listing = "\n".join(f"- {t.name} ({t.kind}): {t.description}" for t in topics)
    user_msg = (
        f"Memory topics available for this user:\n{topic_listing}\n\n"
        f"User prompt:\n{raw_prompt}"
    )
    try:
        result = await provider.complete(
            [LLMMessage(role="user", content=user_msg)],
            system=_ENHANCE_SYSTEM,
            model=model,
            max_tokens=512,
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("user_agent.enhance_failed", error=str(exc)[:200])
        return EnhancedPrompt(enhanced_text=raw_prompt, used_topics=[])
    # Parse the JSON response defensively. v1 trusts Haiku to follow
    # the schema; if it doesn't, we pass through.
    import json

    try:
        parsed = json.loads(result.text.strip())
        enhanced = parsed.get("enhanced", raw_prompt)
        used_topics = parsed.get("used_topics", [])
        if not isinstance(enhanced, str):
            return EnhancedPrompt(enhanced_text=raw_prompt, used_topics=[])
        if not isinstance(used_topics, list):
            used_topics = []
    except (ValueError, TypeError):
        return EnhancedPrompt(enhanced_text=raw_prompt, used_topics=[])
    # When the model says it used topics, materialize the bodies into
    # the enhanced prompt as an explicit "Context from memory" block —
    # avoids relying on the model to copy-paste them correctly.
    if used_topics:
        bodies: list[str] = []
        for name in used_topics:
            body = await read_memory(user_id, name)
            if body:
                bodies.append(f"### {name}\n{body}")
        if bodies:
            context_block = (
                "## Context from your stored preferences\n"
                + "\n\n".join(bodies)
                + "\n\n## Your message\n"
            )
            enhanced = context_block + raw_prompt
    return EnhancedPrompt(enhanced_text=enhanced, used_topics=list(used_topics))
