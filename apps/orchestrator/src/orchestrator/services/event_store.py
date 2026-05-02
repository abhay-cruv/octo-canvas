"""Persist + publish wire-protocol events on `/ws/web/tasks/{task_id}`.

Allocates a monotonic `seq` per `task_id` via Mongo's `findOneAndUpdate
{$inc: {next: 1}}` upsert (atomic across orchestrator instances), inserts
the `AgentEvent`, and publishes the JSON-serialized payload to Redis on
`task:{task_id}` for cross-instance fanout.

Mongo is canonical — replay reads here. Redis is fire-and-forget live
broadcast; subscribers that miss it catch up via `Resume{after_seq}`. See
[slice5a.md §3](../../../../../docs/slice/slice5a.md).
"""

from typing import TYPE_CHECKING, Any, cast

import structlog
from beanie import PydanticObjectId
from db import mongo
from db.models import AgentEvent
from pymongo import ReturnDocument
from shared_models.wire_protocol import (
    BridgeToOrchestrator,
    BridgeToOrchestratorAdapter,
    OrchestratorToWeb,
    OrchestratorToWebAdapter,
)

if TYPE_CHECKING:
    from redis.asyncio.client import Redis

_logger = structlog.get_logger("event_store")


def channel_for(task_id: PydanticObjectId) -> str:
    return f"task:{task_id}"


async def _allocate_seq(task_id: PydanticObjectId) -> int:
    """Atomic per-task seq allocator. Returns the seq for the new event."""
    doc = await mongo.seq_counters.find_one_and_update(
        {"_id": task_id},
        {"$inc": {"next": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    # `find_one_and_update` with upsert+AFTER never returns None.
    assert doc is not None
    next_value = doc["next"]
    assert isinstance(next_value, int)
    return next_value


async def append_event(
    task_id: PydanticObjectId,
    payload: OrchestratorToWeb,
    *,
    redis: "Redis | None",
) -> AgentEvent:
    """Allocate next seq, mutate payload's `seq`, persist, publish.

    The caller passes a payload with `seq=0` (or any placeholder); this
    function rewrites it to the freshly-allocated seq. Single source of
    seq-truth: this function. No other code path mutates `seq`.
    """

    seq = await _allocate_seq(task_id)

    # Re-validate through the adapter to (a) preserve discriminator semantics
    # and (b) get a serialized dict with the allocated seq baked in.
    raw = OrchestratorToWebAdapter.dump_python(payload, mode="json")
    raw_dict = cast("dict[str, Any]", raw)
    if "seq" in raw_dict:
        raw_dict["seq"] = seq
    rewritten = OrchestratorToWebAdapter.validate_python(raw_dict)
    json_payload = cast(
        "dict[str, Any]",
        OrchestratorToWebAdapter.dump_python(rewritten, mode="json"),
    )

    event = AgentEvent(task_id=task_id, seq=seq, payload=json_payload)
    await event.insert()

    if redis is not None:
        try:
            await redis.publish(  # type: ignore[misc]
                channel_for(task_id),
                OrchestratorToWebAdapter.dump_json(rewritten).decode(),
            )
        except Exception as exc:
            # Pub/sub is best-effort; a failed publish only means live
            # subscribers miss this frame. They catch up via Resume on
            # reconnect (Mongo has the truth).
            _logger.warning("event_store.publish_failed", task_id=str(task_id), error=str(exc))

    return event


async def replay(
    task_id: PydanticObjectId,
    *,
    after_seq: int,
) -> list[OrchestratorToWeb]:
    """Stream every event with seq > after_seq, in seq order. Slice 5a uses
    a single batch (eager `.to_list()`); for very long replays slice 6 will
    switch to async iteration."""
    cursor = AgentEvent.find(
        AgentEvent.task_id == task_id,
        AgentEvent.seq > after_seq,
    ).sort("seq")
    rows = await cursor.to_list()
    return [OrchestratorToWebAdapter.validate_python(row.payload) for row in rows]


# ── Slice 8: chat-keyed event store ──────────────────────────────────


def chat_channel_for(chat_id: PydanticObjectId) -> str:
    """FE subscription channel — receives the FULL bridge stream."""
    return f"chat:{chat_id}"


def chat_user_agent_channel_for(chat_id: PydanticObjectId) -> str:
    """User-agent subscription channel — receives only IMPORTANT events
    (slice 8 §5: AskUserClarification, ResultMessage, AssistantMessage,
    ErrorEvent — NOT thinking/deltas/tool-calls)."""
    return f"chat:{chat_id}:ua"


def _seq_key(chat_id: PydanticObjectId, claude_session_id: str | None) -> str:
    """Slice 8: per-(chat, session) seq allocator key. `_global` covers
    pre-`ChatStarted` events (no session id assigned yet) so they get a
    distinct seq space from the post-resume session's events."""
    return f"{chat_id}:{claude_session_id or '_global'}"


async def _allocate_chat_seq(
    chat_id: PydanticObjectId, claude_session_id: str | None
) -> int:
    doc = await mongo.seq_counters.find_one_and_update(
        {"_id": _seq_key(chat_id, claude_session_id)},
        {"$inc": {"next": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    assert doc is not None
    next_value = doc["next"]
    assert isinstance(next_value, int)
    return next_value


# Slice 8 §5: the user-agent filter rule. Defined as a frozen set of
# wire `type` discriminators so the routing layer can decide cheaply
# without re-importing the payload classes.
_USER_AGENT_IMPORTANT_TYPES: frozenset[str] = frozenset(
    {
        "ask_user_clarification",
        "result",
        "assistant.message",  # final block, NOT `assistant.delta`
        "error",
    }
)


def is_important_for_user_agent(payload_type: str) -> bool:
    """Filter rule for which bridge frames flow to the BE user agent.

    The user agent only sees the events it can sensibly act on:
    clarifications (it might auto-answer), final assistant blocks +
    result messages (turn conclusions it should remember), errors. It
    does NOT see streaming deltas, thinking blocks, tool calls, or
    file edits — those would burn its context for no decision benefit.
    """
    return payload_type in _USER_AGENT_IMPORTANT_TYPES


async def append_chat_event(
    chat_id: PydanticObjectId,
    payload: BridgeToOrchestrator,
    *,
    claude_session_id: str | None = None,
    redis: "Redis | None",
    user_agent_enabled: bool = False,
) -> AgentEvent:
    """Slice 8: persist a bridge frame + fan it out.

    1. Allocate seq atomically against `_id="{chat_id}:{session_id or '_global'}"`.
    2. Insert `AgentEvent(chat_id, claude_session_id, seq, payload)`.
    3. Publish to `chat:{chat_id}` (full stream → FE subscribers).
    4. If user-agent is enabled AND payload is important: also publish
       to `chat:{chat_id}:ua` so the in-process user-agent service
       picks it up.
    """
    seq = await _allocate_chat_seq(chat_id, claude_session_id)

    # Mutate seq (the bridge sends seq=0 placeholder; orchestrator is
    # the seq authority for replay purposes).
    raw = BridgeToOrchestratorAdapter.dump_python(payload, mode="json")
    raw_dict = cast("dict[str, Any]", raw)
    if "seq" in raw_dict:
        raw_dict["seq"] = seq
    rewritten = BridgeToOrchestratorAdapter.validate_python(raw_dict)
    json_payload = cast(
        "dict[str, Any]",
        BridgeToOrchestratorAdapter.dump_python(rewritten, mode="json"),
    )

    event = AgentEvent(
        chat_id=chat_id,
        claude_session_id=claude_session_id,
        seq=seq,
        payload=json_payload,
    )
    await event.insert()

    if redis is not None:
        serialized = BridgeToOrchestratorAdapter.dump_json(rewritten).decode()
        try:
            await redis.publish(chat_channel_for(chat_id), serialized)  # type: ignore[misc]
        except Exception as exc:
            _logger.warning(
                "event_store.chat_publish_failed",
                chat_id=str(chat_id),
                error=str(exc),
            )
        if user_agent_enabled and is_important_for_user_agent(
            json_payload.get("type", "")
        ):
            try:
                await redis.publish(  # type: ignore[misc]
                    chat_user_agent_channel_for(chat_id), serialized
                )
            except Exception as exc:
                _logger.warning(
                    "event_store.user_agent_publish_failed",
                    chat_id=str(chat_id),
                    error=str(exc),
                )

    return event


async def ack_bridge_chat(
    sandbox_id: PydanticObjectId, chat_id: PydanticObjectId, seq: int
) -> None:
    """Bridge ring-buffer ack: `Sandbox.bridge_last_acked_seq_per_chat[chat_id] = seq`.

    The bridge uses this on reconnect (`Hello{last_acked_seq_per_chat}`) to
    decide which frames to replay. We only update if the new seq is
    higher (avoid clobbering on out-of-order acks)."""
    await mongo.sandboxes.update_one(
        {
            "_id": sandbox_id,
            f"bridge_last_acked_seq_per_chat.{chat_id}": {"$lt": seq},
        },
        {"$set": {f"bridge_last_acked_seq_per_chat.{chat_id}": seq}},
    )
    # Separate update for the case where the key doesn't exist yet
    # (the conditional above doesn't match a missing field).
    await mongo.sandboxes.update_one(
        {
            "_id": sandbox_id,
            f"bridge_last_acked_seq_per_chat.{chat_id}": {"$exists": False},
        },
        {"$set": {f"bridge_last_acked_seq_per_chat.{chat_id}": seq}},
    )


async def replay_chat(
    chat_id: PydanticObjectId,
    *,
    after_seq: int,
    claude_session_id: str | None = None,
) -> list[BridgeToOrchestrator]:
    """Slice 8: replay bridge frames for a chat. When `claude_session_id`
    is provided, scope to that session's seq space (matches the
    seq_counter keying); otherwise return everything for the chat."""
    if claude_session_id is None:
        cursor = AgentEvent.find(
            AgentEvent.chat_id == chat_id,
            AgentEvent.seq > after_seq,
        ).sort("seq")
    else:
        cursor = AgentEvent.find(
            AgentEvent.chat_id == chat_id,
            AgentEvent.claude_session_id == claude_session_id,
            AgentEvent.seq > after_seq,
        ).sort("seq")
    rows = await cursor.to_list()
    return [BridgeToOrchestratorAdapter.validate_python(row.payload) for row in rows]
