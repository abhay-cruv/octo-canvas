"""TaskFanout: cross-instance fanout via real Redis pub/sub."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    import httpx
    import redis.asyncio as redis_asyncio
from beanie import PydanticObjectId
from orchestrator.services.event_store import append_event
from orchestrator.ws.task_fanout import Subscription, TaskFanout
from shared_models.wire_protocol import DebugEvent, OrchestratorToWeb

pytestmark = pytest.mark.asyncio


async def _wait_for(pred, timeout=2.0):  # type: ignore[no-untyped-def]
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("predicate timed out")


async def test_subscriber_receives_published_event(client: "httpx.AsyncClient", redis_client: "redis_asyncio.Redis") -> None:
    _ = client
    fanout = TaskFanout(redis_client)
    await fanout.start()
    try:
        task_id = PydanticObjectId()
        queue: asyncio.Queue[OrchestratorToWeb] = asyncio.Queue(maxsize=10)
        sub = Subscription(queue=queue)
        token = await fanout.subscribe(task_id, sub)
        # Give the pubsub subscribe a moment to land.
        await asyncio.sleep(0.05)

        await redis_client.publish(  # type: ignore[misc]
            f"task:{task_id}",
            DebugEvent(seq=1, message="hello").model_dump_json(),
        )

        await _wait_for(lambda: not queue.empty())
        payload = queue.get_nowait()
        assert isinstance(payload, DebugEvent)
        assert payload.message == "hello"

        await fanout.unsubscribe(task_id, token)
    finally:
        await fanout.stop()


async def test_cross_instance_fanout(client: "httpx.AsyncClient", redis_client: "redis_asyncio.Redis") -> None:
    """Two TaskFanout instances against the same Redis: instance A publishes,
    instance B's subscriber receives. This is the in-process simulation of
    'two orchestrator instances streaming the same task' per slice5a §11."""
    _ = client
    instance_a = TaskFanout(redis_client)
    instance_b = TaskFanout(redis_client)
    await instance_a.start()
    await instance_b.start()
    try:
        task_id = PydanticObjectId()
        queue_b: asyncio.Queue[OrchestratorToWeb] = asyncio.Queue(maxsize=10)
        await instance_b.subscribe(task_id, Subscription(queue=queue_b))
        await asyncio.sleep(0.05)

        await redis_client.publish(  # type: ignore[misc]
            f"task:{task_id}",
            DebugEvent(seq=42, message="from-A").model_dump_json(),
        )

        await _wait_for(lambda: not queue_b.empty())
        payload = queue_b.get_nowait()
        assert isinstance(payload, DebugEvent)
        assert payload.seq == 42
        assert payload.message == "from-A"
    finally:
        await instance_a.stop()
        await instance_b.stop()


async def test_unsubscribe_removes_channel_when_last_drops(
    client: "httpx.AsyncClient", redis_client: "redis_asyncio.Redis"
) -> None:
    _ = client
    fanout = TaskFanout(redis_client)
    await fanout.start()
    try:
        task_id = PydanticObjectId()
        queue: asyncio.Queue[OrchestratorToWeb] = asyncio.Queue(maxsize=10)
        token = await fanout.subscribe(task_id, Subscription(queue=queue))
        await fanout.unsubscribe(task_id, token)

        # The bucket should be gone — no more frames will be enqueued.
        await redis_client.publish(  # type: ignore[misc]
            f"task:{task_id}",
            DebugEvent(seq=1, message="after-unsub").model_dump_json(),
        )
        await asyncio.sleep(0.1)
        assert queue.empty()
    finally:
        await fanout.stop()


async def test_backpressure_records_dropped_seq(client: "httpx.AsyncClient", redis_client: "redis_asyncio.Redis") -> None:
    """Queue full → fanout drops + advances `last_dropped_seq` so the WS
    layer can emit BackpressureWarning to the FE."""
    _ = client
    fanout = TaskFanout(redis_client)
    await fanout.start()
    try:
        task_id = PydanticObjectId()
        # maxsize=2 so we overflow on the third publish.
        queue: asyncio.Queue[OrchestratorToWeb] = asyncio.Queue(maxsize=2)
        sub = Subscription(queue=queue)
        await fanout.subscribe(task_id, sub)
        await asyncio.sleep(0.05)

        for i in range(5):
            await redis_client.publish(  # type: ignore[misc]
                f"task:{task_id}",
                DebugEvent(seq=i + 1, message=f"m{i}").model_dump_json(),
            )

        await _wait_for(lambda: sub.dropped_count > 0, timeout=2.0)
        # At least the last seq we published should be in last_dropped_seq.
        assert sub.last_dropped_seq >= 3
    finally:
        await fanout.stop()


async def test_append_event_round_trip_via_fanout(client: "httpx.AsyncClient", redis_client: "redis_asyncio.Redis") -> None:
    """End-to-end: `append_event` publishes → fanout dispatches → subscriber
    receives. Validates the production code path without a WS handler in
    the loop."""
    from db.models import Task

    fanout = TaskFanout(redis_client)
    await fanout.start()
    try:
        task = Task(user_id=PydanticObjectId())
        await task.insert()
        assert task.id is not None

        queue: asyncio.Queue[OrchestratorToWeb] = asyncio.Queue(maxsize=10)
        await fanout.subscribe(task.id, Subscription(queue=queue))
        await asyncio.sleep(0.05)

        await append_event(task.id, DebugEvent(seq=0, message="round-trip"), redis=redis_client)

        await _wait_for(lambda: not queue.empty())
        payload = cast(DebugEvent, queue.get_nowait())
        assert payload.message == "round-trip"
        assert payload.seq == 1
    finally:
        await fanout.stop()
        _ = client  # keep mongo fixture alive
