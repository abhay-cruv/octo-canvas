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
from shared_models.wire_protocol import OrchestratorToWeb, OrchestratorToWebAdapter

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
