"""Process-singleton Redis handle.

Mirrors the `db.mongo` pattern: one instance per process, lifecycle owned by
the FastAPI lifespan. Slice 4 uses Redis as a hot-cache for sandbox state and
sticky-routing keys; slice 5a/6 will add WS-replay and queue keys here.

The orchestrator NEVER reads sandbox state from Redis as primary truth —
Mongo is the source. Redis exists so slice 5a's hot path doesn't hit Mongo on
every WS frame.
"""

from typing import TYPE_CHECKING

import redis.asyncio as redis_asyncio
import structlog

if TYPE_CHECKING:
    from redis.asyncio.client import Redis

_logger = structlog.get_logger("redis")


class RedisClient:
    """Process singleton. Acquire/release via `connect`/`disconnect`."""

    def __init__(self) -> None:
        self._client: Redis | None = None

    @property
    def client(self) -> "Redis":
        if self._client is None:
            raise RuntimeError("RedisClient.connect() not called")
        return self._client

    async def connect(self, url: str) -> None:
        if self._client is not None:
            return
        client = redis_asyncio.from_url(url, decode_responses=True)
        await client.ping()  # type: ignore[misc]
        self._client = client
        _logger.info("redis.connected", url=_safe_url(url))

    async def disconnect(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None
        _logger.info("redis.disconnected")

    async def ping(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.ping()  # type: ignore[misc]
            return True
        except Exception:
            return False


def _safe_url(url: str) -> str:
    """Strip any password component before logging — `redis://:pw@host` should
    log as `redis://host`."""
    if "@" in url:
        scheme, rest = url.split("://", 1)
        _, host = rest.split("@", 1)
        return f"{scheme}://{host}"
    return url


redis_client = RedisClient()
