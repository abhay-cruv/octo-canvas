"""Per-instance multiplex of Redis pub/sub for `task:{task_id}` channels.

A single `redis.asyncio.client.PubSub` per orchestrator process handles every
WS subscriber on this instance. Subscribers register a queue + receive
`OrchestratorToWeb` payloads parsed from the JSON published by
`event_store.append_event`.

Lifecycle:

- `start()` opens the PubSub and spawns the reader task.
- `subscribe(task_id, queue) -> token` registers a queue. If first subscriber
  for that task, calls `pubsub.subscribe(channel)`.
- `unsubscribe(task_id, token)` drops the queue. If last subscriber for that
  task, calls `pubsub.unsubscribe(channel)` so we stop receiving frames we
  have nowhere to send.
- `stop()` cancels the reader and closes the PubSub.

The reader task tolerates Redis errors by logging and re-subscribing all
known channels. We never lose canonical state because Mongo holds the truth;
a brief reader hiccup means current subscribers miss a frame, and they catch
up on the next `Resume` from the FE.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from beanie import PydanticObjectId
from shared_models.wire_protocol import OrchestratorToWeb, OrchestratorToWebAdapter

from ..services.event_store import channel_for


@dataclass
class Subscription:
    """One WS subscriber's slot inside a `TaskFanout`. Holds the inbound
    queue + a per-subscriber dropped-seq high-water mark for backpressure
    signalling. The WS handler reads `last_dropped_seq` to decide whether
    to emit a `BackpressureWarning`."""

    queue: asyncio.Queue[OrchestratorToWeb]
    last_dropped_seq: int = 0
    dropped_count: int = 0


if TYPE_CHECKING:
    from redis.asyncio.client import PubSub, Redis

_logger = structlog.get_logger("task_fanout")


class TaskFanout:
    """Per-instance Redis pub/sub multiplex. Owns one PubSub.

    Thread-safety: single asyncio loop, no locks needed beyond the
    asyncio-native `asyncio.Lock` used to serialize PubSub mutations (the
    redis-py async PubSub object is not safe for concurrent subscribe calls).
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._pubsub: PubSub | None = None
        self._reader: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        # task_id -> {token -> Subscription}
        self._subs: dict[PydanticObjectId, dict[int, Subscription]] = {}
        self._next_token = 0

    async def start(self) -> None:
        if self._pubsub is not None:
            return
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)  # type: ignore[no-untyped-call]
        self._reader = asyncio.create_task(self._reader_loop(), name="task-fanout-reader")
        _logger.info("task_fanout.started")

    async def stop(self) -> None:
        reader = self._reader
        self._reader = None
        if reader is not None:
            reader.cancel()
            with suppress(asyncio.CancelledError):
                await reader
        if self._pubsub is not None:
            with suppress(Exception):
                await self._pubsub.aclose()  # type: ignore[misc]
            self._pubsub = None
        self._subs.clear()
        _logger.info("task_fanout.stopped")

    async def subscribe(
        self,
        task_id: PydanticObjectId,
        subscription: Subscription,
    ) -> int:
        """Register a subscriber for `task_id`. Returns a token to pass back
        to `unsubscribe`."""
        if self._pubsub is None:
            raise RuntimeError("TaskFanout.start() not called")
        async with self._lock:
            self._next_token += 1
            token = self._next_token
            bucket = self._subs.setdefault(task_id, {})
            first = not bucket
            bucket[token] = subscription
            if first:
                await self._pubsub.subscribe(channel_for(task_id))  # type: ignore[misc]
        return token

    async def unsubscribe(self, task_id: PydanticObjectId, token: int) -> None:
        if self._pubsub is None:
            return
        async with self._lock:
            bucket = self._subs.get(task_id)
            if bucket is None:
                return
            bucket.pop(token, None)
            if not bucket:
                self._subs.pop(task_id, None)
                with suppress(Exception):
                    await self._pubsub.unsubscribe(channel_for(task_id))  # type: ignore[misc]

    async def _reader_loop(self) -> None:
        """Poll the PubSub connection. We use `get_message` instead of
        `listen()` because redis-py's async `listen()` blocks on an empty
        subscription set and doesn't wake reliably when channels are added
        mid-flight; polling avoids that race entirely. The 100ms tick is a
        worst-case latency floor for the live path — replay always has the
        full ordering from Mongo, so this isn't on the critical path of
        correctness."""
        assert self._pubsub is not None
        backoff = 0.5
        while True:
            try:
                # Until we have any subscribed channel, the underlying pubsub
                # connection is unset and `get_message` raises. Sleep a short
                # tick instead of busy-erroring in that window.
                if not self._subs:
                    await asyncio.sleep(0.05)
                    continue
                msg_raw = await self._pubsub.get_message(  # type: ignore[misc]
                    ignore_subscribe_messages=True, timeout=0.1
                )
                if msg_raw is None:
                    continue
                msg: dict[str, object] = msg_raw  # pyright: ignore[reportAssignmentType, reportUnknownVariableType]
                if msg.get("type") != "message":
                    continue
                channel = msg.get("channel")
                raw = msg.get("data")
                if not isinstance(channel, str) or not isinstance(raw, str):
                    continue
                if not channel.startswith("task:"):
                    continue
                try:
                    task_id = PydanticObjectId(channel.removeprefix("task:"))
                except Exception:
                    continue
                try:
                    payload = OrchestratorToWebAdapter.validate_json(raw)
                except Exception as exc:
                    _logger.warning(
                        "task_fanout.bad_payload",
                        task_id=str(task_id),
                        error=str(exc),
                    )
                    continue
                self._dispatch(task_id, payload)
                backoff = 0.5  # reset on any successful read
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _logger.warning("task_fanout.reader_error", error=str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8.0)
                # Re-subscribe everything we had on file so the next poll
                # picks up fresh frames after a transient connection error.
                async with self._lock:
                    if self._subs:
                        with suppress(Exception):
                            await self._pubsub.subscribe(  # type: ignore[misc]
                                *(channel_for(t) for t in self._subs)
                            )

    def _dispatch(self, task_id: PydanticObjectId, payload: OrchestratorToWeb) -> None:
        bucket = self._subs.get(task_id)
        if not bucket:
            return
        seq = getattr(payload, "seq", None)
        for sub in bucket.values():
            try:
                sub.queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Backpressure: drop the frame, advance the per-subscriber
                # high-water mark. The WS pump notices and emits a
                # BackpressureWarning to the FE; FE catches up on next
                # reconnect via Resume{after_seq}. Mongo is canonical.
                sub.dropped_count += 1
                if isinstance(seq, int) and seq > sub.last_dropped_seq:
                    sub.last_dropped_seq = seq
                _logger.warning("task_fanout.queue_full", task_id=str(task_id))
