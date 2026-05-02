"""Per-instance multiplex of Redis pub/sub for `chat:{chat_id}` channels.

Slice 8 §11 sibling of `TaskFanout`. Same shape — one `PubSub` per
orchestrator process, one queue per WS subscriber, polling reader to
sidestep redis-py async `listen()`'s wake-up bug. Payload is
`BridgeToOrchestrator` (JSON published by `event_store.append_chat_event`).
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from beanie import PydanticObjectId
from shared_models.wire_protocol import (
    BridgeToOrchestrator,
    BridgeToOrchestratorAdapter,
)

from ..services.event_store import chat_channel_for


@dataclass
class ChatSubscription:
    queue: asyncio.Queue[BridgeToOrchestrator]
    last_dropped_seq: int = 0
    dropped_count: int = 0


if TYPE_CHECKING:
    from redis.asyncio.client import PubSub, Redis

_logger = structlog.get_logger("chat_fanout")


class ChatFanout:
    """Per-orchestrator-instance multiplex over `chat:*` Redis channels."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._pubsub: PubSub | None = None
        self._reader: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._subs: dict[PydanticObjectId, dict[int, ChatSubscription]] = {}
        self._next_token = 0

    async def start(self) -> None:
        if self._pubsub is not None:
            return
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)  # type: ignore[no-untyped-call]
        self._reader = asyncio.create_task(self._reader_loop(), name="chat-fanout-reader")
        _logger.info("chat_fanout.started")

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
        _logger.info("chat_fanout.stopped")

    async def subscribe(
        self,
        chat_id: PydanticObjectId,
        subscription: ChatSubscription,
    ) -> int:
        if self._pubsub is None:
            raise RuntimeError("ChatFanout.start() not called")
        async with self._lock:
            self._next_token += 1
            token = self._next_token
            bucket = self._subs.setdefault(chat_id, {})
            first = not bucket
            bucket[token] = subscription
            if first:
                await self._pubsub.subscribe(chat_channel_for(chat_id))  # type: ignore[misc]
        return token

    async def unsubscribe(
        self, chat_id: PydanticObjectId, token: int
    ) -> None:
        if self._pubsub is None:
            return
        async with self._lock:
            bucket = self._subs.get(chat_id)
            if bucket is None:
                return
            bucket.pop(token, None)
            if not bucket:
                self._subs.pop(chat_id, None)
                with suppress(Exception):
                    await self._pubsub.unsubscribe(chat_channel_for(chat_id))  # type: ignore[misc]

    async def _reader_loop(self) -> None:
        assert self._pubsub is not None
        backoff = 0.5
        while True:
            try:
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
                if not channel.startswith("chat:") or channel.endswith(":ua"):
                    continue
                try:
                    chat_id = PydanticObjectId(channel.removeprefix("chat:"))
                except Exception:
                    continue
                try:
                    payload = BridgeToOrchestratorAdapter.validate_json(raw)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "chat_fanout.bad_payload",
                        chat_id=str(chat_id),
                        error=str(exc),
                    )
                    continue
                self._dispatch(chat_id, payload)
                backoff = 0.5
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                _logger.warning("chat_fanout.reader_error", error=str(exc))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8.0)
                async with self._lock:
                    if self._subs:
                        with suppress(Exception):
                            await self._pubsub.subscribe(  # type: ignore[misc]
                                *(chat_channel_for(c) for c in self._subs)
                            )

    def _dispatch(
        self, chat_id: PydanticObjectId, payload: BridgeToOrchestrator
    ) -> None:
        bucket = self._subs.get(chat_id)
        if not bucket:
            return
        seq = getattr(payload, "seq", None)
        for sub in bucket.values():
            try:
                sub.queue.put_nowait(payload)
            except asyncio.QueueFull:
                sub.dropped_count += 1
                if isinstance(seq, int) and seq > sub.last_dropped_seq:
                    sub.last_dropped_seq = seq
                _logger.warning("chat_fanout.queue_full", chat_id=str(chat_id))
