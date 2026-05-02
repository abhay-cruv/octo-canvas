"""User-agent reply suggestion — slice 8 §calls #15 (post-simplification).

Replaces the old `clarification.py` round-trip. The user agent reads
the dev agent's finalized `assistant.message` + `result` (filtered
stream) and decides:

- **suggest** → emits `UserAgentSuggestion{suggested_reply, reason,
  override_deadline}` to FE. After deadline, orchestrator sends the
  reply as a normal `UserMessage`. User can override during the
  window via the existing `POST /api/chats/{id}/messages`.
- **defer** → no action; FE's normal reply box handles the human turn.

Strong default to `defer`. Only suggests when:
  1. The dev agent's last turn ended on a clear question, AND
  2. There's a CONCRETE memory hit that answers it.

Never invents context. Never paraphrases.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import structlog
from agent_config.llm_provider import LLMMessage, LLMProvider
from beanie import PydanticObjectId

from orchestrator.services.user_agent.memory import list_memory, read_memory

_logger = structlog.get_logger("user_agent.suggest")

ReplyDecision = Literal["suggest", "defer"]


@dataclass(frozen=True)
class ReplySuggestion:
    decision: ReplyDecision
    reply: str | None  # set iff decision == "suggest"
    reason: str  # one-line, shown to user inline


_SUGGEST_SYSTEM = """You are the BE-side user agent watching a developer chat with a coding assistant ("dev agent") in a sandbox.

The dev agent has just finished a turn. Look at its final assistant text and decide if it ended on a clear question that you can answer from the user's stored memory.

Strong default to defer. Only suggest a reply when:
1. The dev agent's text ends on a CLEAR question or request for input, AND
2. The user's memory has a concrete answer (a stored preference, a documented project convention, a recorded decision).

Never invent. Never guess. Never paraphrase the dev agent's question.

Return exactly this JSON, no prose:
{"decision": "suggest" | "defer", "reply": "<text>" | null, "reason": "<one short sentence>"}"""


async def suggest_reply(
    user_id: PydanticObjectId,
    *,
    last_assistant_text: str,
    provider: LLMProvider,
    model: str,
) -> ReplySuggestion:
    """Decide whether to suggest a reply to the dev agent's last turn."""
    topics = await list_memory(user_id)
    topic_listing = (
        "\n".join(f"- {t.name} ({t.kind}): {t.description}" for t in topics)
        or "(no memory topics)"
    )
    user_msg = (
        f"Memory topics:\n{topic_listing}\n\n"
        f"Dev agent's final message this turn:\n{last_assistant_text}"
    )
    try:
        result = await provider.complete(
            [LLMMessage(role="user", content=user_msg)],
            system=_SUGGEST_SYSTEM,
            model=model,
            max_tokens=512,
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("user_agent.suggest_failed", error=str(exc)[:200])
        return ReplySuggestion(decision="defer", reply=None, reason="user agent unavailable")
    try:
        parsed = json.loads(result.text.strip())
        decision = parsed.get("decision")
        reply = parsed.get("reply")
        reason = parsed.get("reason", "")
        if decision not in ("suggest", "defer"):
            return ReplySuggestion(decision="defer", reply=None, reason="invalid decision")
        if decision == "suggest" and not isinstance(reply, str):
            return ReplySuggestion(decision="defer", reply=None, reason="invalid reply text")
        if not isinstance(reason, str):
            reason = ""
        return ReplySuggestion(
            decision=decision,
            reply=reply if decision == "suggest" else None,
            reason=reason,
        )
    except (ValueError, TypeError):
        return ReplySuggestion(decision="defer", reply=None, reason="malformed response")


async def memory_excerpts_for(
    user_id: PydanticObjectId, names: list[str]
) -> dict[str, str]:
    """For the FE override UI: render which memory bodies informed a
    suggested reply (when we choose to surface that detail)."""
    out: dict[str, str] = {}
    for name in names:
        body = await read_memory(user_id, name)
        if body is not None:
            out[name] = body
    return out
