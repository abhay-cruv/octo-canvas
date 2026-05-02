"""Cross-instance bridge ownership + command routing — slice 8 §6.

Each `/ws/bridge/{sandbox_id}` connection is owned by the orchestrator
instance Fly's load balancer happened to route it to. That instance
writes `bridge_owner:{sandbox_id} = {instance_id}` in Redis (TTL 60s,
refreshed every 20s). Other instances forward outbound commands
(UserMessage, AnswerClarification, Cancel, Pause) via Redis pub/sub on
`bridge_in:{sandbox_id}` — the owning instance subscribes and delivers
to its local `BridgeSession`.

Mongo is canonical for chat state; this module just routes commands
across instances during a chat's life.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from redis.asyncio.client import PubSub, Redis

_logger = structlog.get_logger("bridge_owner")


def _instance_id() -> str:
    """Stable per-process id. Fly sets `FLY_ALLOC_ID`; locally we make
    one up. Used to disambiguate ownership records across replicas."""
    return os.environ.get("FLY_ALLOC_ID") or f"local-{secrets.token_hex(4)}"


_OWNER_KEY = "bridge_owner:{sandbox_id}"
_INBOUND_CHANNEL = "bridge_in:{sandbox_id}"
_OWNERSHIP_TTL_S = 60
_OWNERSHIP_REFRESH_S = 20


def owner_key(sandbox_id: str) -> str:
    return _OWNER_KEY.format(sandbox_id=sandbox_id)


def inbound_channel(sandbox_id: str) -> str:
    return _INBOUND_CHANNEL.format(sandbox_id=sandbox_id)


# Type for the local-delivery callback.
LocalDeliver = Callable[[str, dict[str, object]], Awaitable[None]]
"""Receives (sandbox_id, frame_dict). Returns when the frame is queued
on the owning `BridgeSession`'s outbound queue."""


class BridgeOwner:
    """Per-orchestrator-instance singleton.

    Keeps track of locally-owned bridges + subscribes to the global
    `bridge_in:*` pattern so commands aimed at locally-owned bridges
    arrive even when a route handler ran on a different replica.
    """

    def __init__(self, redis: "Redis | None") -> None:
        self._redis = redis
        self._instance_id = _instance_id()
        self._local_delivers: dict[str, LocalDeliver] = {}
        self._refresh_tasks: dict[str, asyncio.Task[None]] = {}
        self._subscribe_task: asyncio.Task[None] | None = None
        self._pubsub: PubSub | None = None
        self._stopped = False

    @property
    def instance_id(self) -> str:
        return self._instance_id

    async def start(self) -> None:
        """Spin up the global `bridge_in:*` subscriber."""
        if self._redis is None:
            return
        self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await self._pubsub.psubscribe(inbound_channel("*"))  # type: ignore[misc]
        self._subscribe_task = asyncio.create_task(self._reader())

    async def stop(self) -> None:
        self._stopped = True
        for t in list(self._refresh_tasks.values()):
            t.cancel()
        for t in list(self._refresh_tasks.values()):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._refresh_tasks.clear()
        if self._subscribe_task is not None:
            self._subscribe_task.cancel()
            try:
                await self._subscribe_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._pubsub is not None:
            try:
                await self._pubsub.aclose()  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001
                _logger.warning("bridge_owner.pubsub_close_failed", error=str(exc))

    async def claim(self, sandbox_id: str, deliver: LocalDeliver) -> bool:
        """Claim ownership of `sandbox_id`. Returns True on success.
        Returns False if another instance currently owns it (caller
        should close the WSS with 4009 — bridge will reconnect)."""
        if self._redis is None:
            # No Redis → single-instance mode; ownership is implicit.
            self._local_delivers[sandbox_id] = deliver
            return True
        ok = await self._redis.set(  # type: ignore[misc]
            owner_key(sandbox_id),
            self._instance_id,
            ex=_OWNERSHIP_TTL_S,
            nx=True,
        )
        if not ok:
            # Steal-back: if we already own this (e.g. duplicate connect
            # from the same bridge), allow the new connection to take
            # over. Otherwise reject.
            current = await self._redis.get(owner_key(sandbox_id))  # type: ignore[misc]
            if current != self._instance_id:
                return False
        self._local_delivers[sandbox_id] = deliver
        self._refresh_tasks[sandbox_id] = asyncio.create_task(
            self._refresh(sandbox_id)
        )
        return True

    async def release(self, sandbox_id: str) -> None:
        """Drop ownership on disconnect."""
        self._local_delivers.pop(sandbox_id, None)
        task = self._refresh_tasks.pop(sandbox_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._redis is None:
            return
        try:
            # Only delete if we still own it (avoid clobbering a
            # subsequent owner).
            current = await self._redis.get(owner_key(sandbox_id))  # type: ignore[misc]
            if current == self._instance_id:
                await self._redis.delete(owner_key(sandbox_id))  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "bridge_owner.release_failed",
                sandbox_id=sandbox_id,
                error=str(exc),
            )

    async def send(self, sandbox_id: str, frame: dict[str, object]) -> bool:
        """Forward an outbound command frame to whoever owns the bridge.

        - If we own it: deliver locally.
        - Else: publish on `bridge_in:{sandbox_id}`; the owning instance
          receives via its pattern subscription and delivers.

        Returns True if delivered (locally) or queued (Redis).
        """
        # Each frame gets a `frame_id` for idempotency on replay (slice
        # 8 §10). Caller can pre-set it; we generate one if missing.
        frame.setdefault("frame_id", str(uuid.uuid4()))
        local = self._local_delivers.get(sandbox_id)
        if local is not None:
            await local(sandbox_id, frame)
            return True
        if self._redis is None:
            _logger.warning(
                "bridge_owner.unowned_no_redis", sandbox_id=sandbox_id
            )
            return False
        try:
            await self._redis.publish(  # type: ignore[misc]
                inbound_channel(sandbox_id), json.dumps(frame)
            )
            return True
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "bridge_owner.publish_failed",
                sandbox_id=sandbox_id,
                error=str(exc),
            )
            return False

    async def _refresh(self, sandbox_id: str) -> None:
        """Renew the ownership TTL every 20s."""
        if self._redis is None:
            return
        try:
            while not self._stopped:
                await asyncio.sleep(_OWNERSHIP_REFRESH_S)
                try:
                    await self._redis.expire(  # type: ignore[misc]
                        owner_key(sandbox_id), _OWNERSHIP_TTL_S
                    )
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "bridge_owner.refresh_failed",
                        sandbox_id=sandbox_id,
                        error=str(exc),
                    )
        except asyncio.CancelledError:
            pass

    async def _reader(self) -> None:
        """Reads `bridge_in:*` pattern messages and delivers locally."""
        if self._pubsub is None:
            return
        try:
            while not self._stopped:
                msg = await self._pubsub.get_message(  # type: ignore[misc]
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg is None:
                    continue
                channel = msg["channel"]
                # Strip prefix to extract sandbox_id.
                if not isinstance(channel, str):
                    channel = channel.decode("utf-8")
                if not channel.startswith("bridge_in:"):
                    continue
                sandbox_id = channel.removeprefix("bridge_in:")
                local = self._local_delivers.get(sandbox_id)
                if local is None:
                    # Not ours — another instance owns it.
                    continue
                data = msg["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                try:
                    frame = json.loads(data)
                except (ValueError, TypeError) as exc:
                    _logger.warning(
                        "bridge_owner.bad_frame_json",
                        sandbox_id=sandbox_id,
                        error=str(exc),
                    )
                    continue
                try:
                    await local(sandbox_id, frame)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "bridge_owner.local_deliver_failed",
                        sandbox_id=sandbox_id,
                        error=str(exc),
                    )
        except asyncio.CancelledError:
            pass
