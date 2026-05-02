"""Per-sandbox fs/watch broker (slice 6).

One upstream `provider.fs_watch_subscribe` task per active sandbox; many
web subscribers fan out from it. Coalesces duplicate `(path, kind)`
events inside a short window to avoid storms (e.g. `pnpm install`).

Lazy start on first subscriber, dropped on last. Per-subscriber queues
have a fixed cap; on overflow we mark the subscriber stale and the WS
handler closes the connection so the FE reconnects with a clean slate.

## Cross-instance fan-out (slice 6 enhancement)

When `redis` is supplied, every event the local upstream task receives is
also published to `fswatch:{sandbox_id}` tagged with our `instance_id`. A
single Redis pub/sub subscription per orchestrator process consumes the
channel and fans out to local subscribers — skipping events tagged with
our own `instance_id` so the publisher doesn't double-fire.

This means: in single-instance dev, no Redis traffic happens (events go
upstream → local fan-out, full stop). In multi-instance prod, each
instance with subscribers opens its own upstream Sprites WSS *and* listens
on Redis for events from other instances.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from sandbox_provider import FsEvent, SandboxHandle, SandboxProvider

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from redis.asyncio.client import PubSub

_logger = structlog.get_logger("services.fs_watcher")

# Coalesce window — drop duplicate `(path, kind)` events within this many
# seconds. Caps the per-sandbox event rate per Plan.md §10.6.
_COALESCE_WINDOW_S = 0.25
# Per-subscriber outbound queue cap. On overflow the FE is told to refresh.
_SUBSCRIBER_QUEUE = 1024


def _channel_for(sandbox_id: str) -> str:
    return f"fswatch:{sandbox_id}"


@dataclass
class _Subscriber:
    queue: asyncio.Queue[FsEvent | None]
    stale: bool = False


@dataclass
class _SandboxWatcher:
    sandbox_id: str
    handle: SandboxHandle
    subscribers: list[_Subscriber] = field(default_factory=lambda: [])
    upstream_task: asyncio.Task[None] | None = None
    # `(path, kind)` -> last-emitted timestamp (monotonic seconds). Cheap
    # in-memory coalesce table; trimmed lazily.
    last_seen: dict[tuple[str, str], float] = field(default_factory=lambda: {})


class FsWatcher:
    """Process-singleton broker. Held on `app.state.fs_watcher`."""

    def __init__(
        self,
        provider: SandboxProvider,
        *,
        root_path: str = "/work",
        redis: Redis | None = None,
    ) -> None:
        self._provider = provider
        self._root_path = root_path
        self._redis = redis
        # Stable id for this process — tags every Redis publish so the
        # subscriber loop can skip our own events.
        self._instance_id = uuid.uuid4().hex[:12]
        self._watchers: dict[str, _SandboxWatcher] = {}
        self._lock = asyncio.Lock()
        # Redis pub/sub state — populated by `start()`.
        self._pubsub: PubSub | None = None
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Open the Redis pub/sub if available. Safe to call without Redis
        (no-op). The reader task uses pattern subscribe (`fswatch:*`) so
        new sandboxes don't require a re-subscribe."""
        if self._redis is None or self._pubsub is not None:
            return
        try:
            self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)  # type: ignore[no-untyped-call]
            await self._pubsub.psubscribe("fswatch:*")  # type: ignore[misc]
            self._reader_task = asyncio.create_task(self._read_redis(), name="fswatch-redis-reader")
        except Exception as exc:
            _logger.warning("fswatch.redis_start_failed", error=str(exc))
            self._pubsub = None

    async def subscribe(self, sandbox_id: str, handle: SandboxHandle) -> _Subscriber:
        """Register a new subscriber for `sandbox_id`. Lazily starts the
        upstream watcher on the first call. Returns the subscriber record;
        callers must `unsubscribe` it on disconnect."""
        async with self._lock:
            watcher = self._watchers.get(sandbox_id)
            if watcher is None:
                watcher = _SandboxWatcher(sandbox_id=sandbox_id, handle=handle)
                self._watchers[sandbox_id] = watcher
                watcher.upstream_task = asyncio.create_task(
                    self._run_upstream(watcher), name=f"fswatch-{sandbox_id}"
                )
            sub = _Subscriber(queue=asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE))
            watcher.subscribers.append(sub)
            return sub

    async def unsubscribe(self, sandbox_id: str, sub: _Subscriber) -> None:
        async with self._lock:
            watcher = self._watchers.get(sandbox_id)
            if watcher is None:
                return
            with suppress(ValueError):
                watcher.subscribers.remove(sub)
            # Signal the consumer in case it's still awaiting.
            with suppress(asyncio.QueueFull):
                sub.queue.put_nowait(None)
            if not watcher.subscribers:
                # Last subscriber gone — kill the upstream task.
                if watcher.upstream_task is not None:
                    watcher.upstream_task.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await watcher.upstream_task
                del self._watchers[sandbox_id]

    async def stop(self) -> None:
        """Shut down all watchers + the Redis reader. Called from app shutdown."""
        async with self._lock:
            tasks = [w.upstream_task for w in self._watchers.values() if w.upstream_task]
            for w in self._watchers.values():
                for sub in w.subscribers:
                    with suppress(asyncio.QueueFull):
                        sub.queue.put_nowait(None)
                if w.upstream_task is not None:
                    w.upstream_task.cancel()
            self._watchers.clear()
        for t in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await t
        if self._reader_task is not None:
            self._reader_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._reader_task
            self._reader_task = None
        if self._pubsub is not None:
            with suppress(Exception):
                await self._pubsub.aclose()  # type: ignore[misc]
            self._pubsub = None

    async def _run_upstream(self, watcher: _SandboxWatcher) -> None:
        """One subscription to `provider.fs_watch_subscribe`; fan to all
        local subscribers with coalescing AND publish to Redis so other
        instances can fan out to their subscribers.

        Retries `fs_watch_subscribe` on transient handshake failures with
        the same backoff as `exec_oneshot` (1+2+4+8+16+32s). After all
        retries exhaust we mark every local subscriber stale and exit.
        """
        backoff_s = 1.0
        attempts = 0
        while True:
            try:
                async for event in self._provider.fs_watch_subscribe(
                    watcher.handle, self._root_path, recursive=True
                ):
                    # Reset backoff once we've successfully consumed at
                    # least one event — connection is healthy now.
                    backoff_s = 1.0
                    attempts = 0
                    if not self._should_emit(watcher, event):
                        continue
                    self._fanout(watcher, event)
                    await self._publish(watcher.sandbox_id, event)
                # Iterator returned cleanly — upstream said goodbye. Try
                # to re-subscribe (Sprites may have rotated the session).
                _logger.info(
                    "fswatch.upstream_iterator_returned",
                    sandbox_id=watcher.sandbox_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                err_str = str(exc).lower()
                transient = (
                    "timed out during opening handshake" in err_str
                    or "timeout" in err_str
                    or "connection refused" in err_str
                    or "503" in err_str
                    or "502" in err_str
                    or "504" in err_str
                    or "fs_watch connect failed" in err_str
                )
                if not transient or attempts >= 5:
                    _logger.warning(
                        "fswatch.upstream_error",
                        sandbox_id=watcher.sandbox_id,
                        error=str(exc),
                        attempts=attempts,
                    )
                    for sub in watcher.subscribers:
                        sub.stale = True
                        with suppress(asyncio.QueueFull):
                            sub.queue.put_nowait(None)
                    return
                _logger.warning(
                    "fswatch.upstream_retry",
                    sandbox_id=watcher.sandbox_id,
                    attempt=attempts + 1,
                    error=str(exc)[:200],
                )

            # Sleep before re-subscribing on a transient or clean-return.
            attempts += 1
            if attempts > 5:
                for sub in watcher.subscribers:
                    sub.stale = True
                    with suppress(asyncio.QueueFull):
                        sub.queue.put_nowait(None)
                return
            await asyncio.sleep(backoff_s)
            backoff_s *= 2

    async def _read_redis(self) -> None:
        """Consume `fswatch:*` from Redis and dispatch events from OTHER
        instances to our local subscribers. Self-published events are
        skipped via the `instance_id` tag.

        We poll with `get_message` (10ms timeout) instead of `listen()`
        because redis-py's async `listen` blocks indefinitely on an empty
        connection — which makes shutdown awkward. Same pattern as
        `TaskFanout._reader_loop`.
        """
        pubsub = self._pubsub
        assert pubsub is not None
        try:
            while True:
                try:
                    msg_raw = await pubsub.get_message(  # type: ignore[misc]
                        ignore_subscribe_messages=True, timeout=0.1
                    )
                except Exception:
                    await asyncio.sleep(0.1)
                    continue
                if msg_raw is None:
                    continue
                msg: dict[str, object] = msg_raw  # pyright: ignore[reportAssignmentType, reportUnknownVariableType]
                if msg.get("type") not in ("pmessage", "message"):
                    continue
                channel_raw = msg.get("channel")
                channel = (
                    channel_raw.decode("utf-8") if isinstance(channel_raw, bytes) else channel_raw
                )
                if not isinstance(channel, str) or not channel.startswith("fswatch:"):
                    continue
                sandbox_id = channel.removeprefix("fswatch:")
                payload_raw = msg.get("data")
                payload = (
                    payload_raw.decode("utf-8", errors="replace")
                    if isinstance(payload_raw, bytes)
                    else payload_raw
                )
                if not isinstance(payload, str):
                    continue
                try:
                    parsed: dict[str, Any] = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if parsed.get("instance_id") == self._instance_id:
                    continue  # our own publish; local fan-out already happened
                event = _decode_event(parsed)
                if event is None:
                    continue
                watcher = self._watchers.get(sandbox_id)
                if watcher is None:
                    continue  # nobody local cares
                if not self._should_emit(watcher, event):
                    continue
                self._fanout(watcher, event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.warning("fswatch.redis_reader_error", error=str(exc))

    async def _publish(self, sandbox_id: str, event: FsEvent) -> None:
        if self._redis is None:
            return
        payload = {
            "instance_id": self._instance_id,
            "path": event.path,
            "kind": event.kind,
            "is_dir": event.is_dir,
            "size": event.size,
            "timestamp_ms": event.timestamp_ms,
        }
        try:
            await self._redis.publish(_channel_for(sandbox_id), json.dumps(payload))  # type: ignore[misc]
        except Exception as exc:
            _logger.warning("fswatch.publish_failed", sandbox_id=sandbox_id, error=str(exc))

    def _should_emit(self, watcher: _SandboxWatcher, event: FsEvent) -> bool:
        now = time.monotonic()
        key = (event.path, event.kind)
        last = watcher.last_seen.get(key)
        if last is not None and (now - last) < _COALESCE_WINDOW_S:
            return False
        watcher.last_seen[key] = now
        # Best-effort GC: drop entries older than 10 windows.
        if len(watcher.last_seen) > 4096:
            cutoff = now - (_COALESCE_WINDOW_S * 10)
            watcher.last_seen = {k: t for k, t in watcher.last_seen.items() if t >= cutoff}
        return True

    def _fanout(self, watcher: _SandboxWatcher, event: FsEvent) -> None:
        for sub in watcher.subscribers:
            if sub.stale:
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.stale = True
                with suppress(asyncio.QueueFull):
                    sub.queue.put_nowait(None)


def _decode_event(msg: dict[str, Any]) -> FsEvent | None:
    """Reconstruct an `FsEvent` from a wire payload (best-effort; ignores
    malformed rows)."""
    path = msg.get("path")
    kind = msg.get("kind")
    if not isinstance(path, str) or kind not in ("create", "modify", "delete", "rename"):
        return None
    is_dir = bool(msg.get("is_dir", False))
    size_raw = msg.get("size")
    size = int(size_raw) if isinstance(size_raw, (int, float)) else None
    ts_raw = msg.get("timestamp_ms")
    timestamp_ms = int(ts_raw) if isinstance(ts_raw, (int, float)) else 0
    return FsEvent(path=path, kind=kind, is_dir=is_dir, size=size, timestamp_ms=timestamp_ms)
