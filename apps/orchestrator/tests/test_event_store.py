"""Unit tests for event_store: atomic seq allocation, persistence, replay."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from beanie import PydanticObjectId

if TYPE_CHECKING:
    import httpx
    import redis.asyncio as redis_asyncio
from db.models import AgentEvent, Task
from orchestrator.services.event_store import append_event, replay
from shared_models.wire_protocol import (
    DebugEvent,
    OrchestratorToWebAdapter,
    StatusChangeEvent,
)

pytestmark = pytest.mark.asyncio


async def _make_task() -> PydanticObjectId:
    task = Task(user_id=PydanticObjectId())
    await task.insert()
    assert task.id is not None
    return task.id


async def test_append_assigns_monotonic_seq(client: "httpx.AsyncClient") -> None:
    _ = client  # fixture wires Mongo
    task_id = await _make_task()

    e1 = await append_event(task_id, DebugEvent(seq=0, message="a"), redis=None)
    e2 = await append_event(task_id, DebugEvent(seq=0, message="b"), redis=None)
    e3 = await append_event(task_id, DebugEvent(seq=0, message="c"), redis=None)

    assert (e1.seq, e2.seq, e3.seq) == (1, 2, 3)
    # Persisted payload's seq matches the doc seq.
    assert e1.payload["seq"] == 1
    assert e3.payload["seq"] == 3


async def test_replay_returns_events_after_cursor_in_order(client: "httpx.AsyncClient") -> None:
    _ = client
    task_id = await _make_task()
    for i in range(5):
        await append_event(task_id, DebugEvent(seq=0, message=f"m{i}"), redis=None)

    streamed = await replay(task_id, after_seq=2)
    assert [getattr(e, "seq", None) for e in streamed] == [3, 4, 5]
    assert all(isinstance(e, DebugEvent) for e in streamed)


async def test_replay_validates_through_discriminator(client: "httpx.AsyncClient") -> None:
    _ = client
    task_id = await _make_task()
    await append_event(
        task_id,
        StatusChangeEvent(seq=0, new_status="running"),
        redis=None,
    )
    streamed = await replay(task_id, after_seq=0)
    assert len(streamed) == 1
    assert isinstance(streamed[0], StatusChangeEvent)
    assert streamed[0].new_status == "running"


async def test_concurrent_appends_have_no_seq_collisions(client: "httpx.AsyncClient") -> None:
    _ = client
    task_id = await _make_task()

    async def insert(i: int) -> int:
        ev = await append_event(task_id, DebugEvent(seq=0, message=f"m{i}"), redis=None)
        return ev.seq

    seqs = await asyncio.gather(*(insert(i) for i in range(50)))
    assert sorted(seqs) == list(range(1, 51))

    # Mongo has exactly 50 events with unique seqs.
    rows = await AgentEvent.find(AgentEvent.task_id == task_id).to_list()
    assert len(rows) == 50
    assert sorted(r.seq for r in rows) == list(range(1, 51))


async def test_publish_is_best_effort_without_redis(client: "httpx.AsyncClient") -> None:
    """`redis=None` is a valid slice 5a config (single instance, no fanout).
    Persistence still happens; only the live broadcast is skipped."""
    _ = client
    task_id = await _make_task()
    ev = await append_event(task_id, DebugEvent(seq=0, message="x"), redis=None)
    assert ev.seq == 1
    rows = await AgentEvent.find(AgentEvent.task_id == task_id).to_list()
    assert len(rows) == 1


async def test_published_payload_round_trips_through_adapter(client: "httpx.AsyncClient", redis_client: "redis_asyncio.Redis") -> None:
    """append_event with a real Redis publishes a JSON frame that round-trips
    through `OrchestratorToWebAdapter.validate_json`."""
    _ = client
    task_id = await _make_task()
    pubsub = redis_client.pubsub()  # pyright: ignore[reportUnknownMemberType]
    await pubsub.subscribe(f"task:{task_id}")  # pyright: ignore[reportUnknownMemberType]
    # drain the subscribe ack
    await asyncio.sleep(0.05)

    await append_event(task_id, DebugEvent(seq=0, message="hi"), redis=redis_client)

    async def next_message() -> dict[str, object]:
        for _ in range(50):
            msg = await pubsub.get_message(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                ignore_subscribe_messages=True, timeout=0.1
            )
            if msg and msg.get("type") == "message":  # pyright: ignore[reportUnknownMemberType]
                return msg  # pyright: ignore[reportUnknownVariableType, reportReturnType]
        raise AssertionError("no published message arrived")

    msg = await next_message()
    raw = msg["data"]
    assert isinstance(raw, (str, bytes))
    payload = OrchestratorToWebAdapter.validate_json(raw)
    assert isinstance(payload, DebugEvent)
    assert payload.message == "hi"
    assert payload.seq == 1
    await pubsub.aclose()
