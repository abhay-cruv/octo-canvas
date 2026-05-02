"""User-agent clarification handling — slice 8 §calls #15.

When the dev agent asks `ask_user_clarification`, the bridge sends
`AskUserClarification` over WSS. With the user agent enabled, the
orchestrator first asks Haiku "can you answer this from memory?"
- if yes (`auto_answer`): emit `AgentAnsweredClarification` to FE with
  a 10s override countdown; on expiry without override, send
  `AnswerClarification{source:"user_agent"}` to the bridge.
- if no (`defer`): forward to FE for manual reply.

v1 keeps the decision policy simple — the LLM either commits to an
answer or defers. The override window lets the user take control if
the auto-answer is wrong.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import structlog
from agent_config.llm_provider import LLMMessage, LLMProvider
from beanie import PydanticObjectId

from orchestrator.services.user_agent.memory import list_memory, read_memory

_logger = structlog.get_logger("user_agent.clarification")

ClarificationDecision = Literal["auto_answer", "defer"]


@dataclass(frozen=True)
class ClarificationResolution:
    decision: ClarificationDecision
    answer: str | None  # set iff decision=="auto_answer"
    reason: str  # one-line explanation, shown to the user inline


_DECIDE_SYSTEM = """You are the BE-side user agent helping a developer chat with a coding assistant.

The dev agent has just asked the user a clarification question. Your job: decide if you can answer it from the user's stored memory, OR if you need to defer to the human.

Strong default to defer. Only answer when there's a CONCRETE memory hit — e.g., the user has a stored preference, the question is procedural and the answer is in memory, or you're confident enough that an incorrect auto-answer wouldn't break their work.

Never invent an answer. Never guess.

Return exactly this JSON, no prose:
{"decision": "auto_answer" | "defer", "answer": "<text>" | null, "reason": "<one short sentence>"}"""


async def resolve_clarification(
    user_id: PydanticObjectId,
    *,
    question: str,
    context: str | None,
    provider: LLMProvider,
    model: str,
) -> ClarificationResolution:
    """Ask the user agent whether to auto-answer or defer."""
    topics = await list_memory(user_id)
    topic_listing = (
        "\n".join(f"- {t.name} ({t.kind}): {t.description}" for t in topics)
        or "(no memory topics)"
    )
    user_msg = (
        f"Memory topics:\n{topic_listing}\n\n"
        f"Dev-agent question:\n{question}\n\n"
        f"Context provided by dev agent: {context or '(none)'}"
    )
    try:
        result = await provider.complete(
            [LLMMessage(role="user", content=user_msg)],
            system=_DECIDE_SYSTEM,
            model=model,
            max_tokens=512,
        )
    except Exception as exc:  # noqa: BLE001
        _logger.warning("user_agent.decide_failed", error=str(exc)[:200])
        return ClarificationResolution(
            decision="defer", answer=None, reason="user agent unavailable"
        )
    try:
        parsed = json.loads(result.text.strip())
        decision = parsed.get("decision")
        answer = parsed.get("answer")
        reason = parsed.get("reason", "")
        if decision not in ("auto_answer", "defer"):
            return ClarificationResolution(
                decision="defer", answer=None, reason="invalid decision"
            )
        if decision == "auto_answer" and not isinstance(answer, str):
            return ClarificationResolution(
                decision="defer", answer=None, reason="invalid auto answer"
            )
        if not isinstance(reason, str):
            reason = ""
        # Materialize relevant memory bodies into the decision when
        # auto-answering — gives the user something concrete to
        # override with if needed. (We don't enforce that the model
        # actually used them; the answer text is authoritative.)
        return ClarificationResolution(
            decision=decision,
            answer=answer if decision == "auto_answer" else None,
            reason=reason,
        )
    except (ValueError, TypeError):
        return ClarificationResolution(
            decision="defer", answer=None, reason="malformed response"
        )


async def memory_excerpts_for(
    user_id: PydanticObjectId, names: list[str]
) -> dict[str, str]:
    """Helper used by the clarification UI to render which memory bodies
    informed an auto-answer."""
    out: dict[str, str] = {}
    for name in names:
        body = await read_memory(user_id, name)
        if body is not None:
            out[name] = body
    return out
