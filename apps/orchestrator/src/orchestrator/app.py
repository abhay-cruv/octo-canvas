from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from db import mongo
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sandbox_provider import SpritesProvider

from .lib.env import settings
from .lib.logger import logger
from .lib.provider_factory import build_sandbox_provider
from .lib.redis_client import redis_client
from .routes import auth, me, repos, sandbox
from .services.sandbox_manager import SandboxManager


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    await mongo.connect(settings.mongodb_uri)

    # Redis is optional in slice 4 — failures are logged but don't kill the
    # orchestrator; the manager's redis_write helpers tolerate `None`.
    redis_handle = None
    try:
        await redis_client.connect(settings.redis_url)
        redis_handle = redis_client.client
    except Exception as exc:
        logger.warning("redis.connect_failed", url=settings.redis_url, error=str(exc))

    provider = build_sandbox_provider()
    manager = SandboxManager(provider=provider, redis=redis_handle)
    app.state.sandbox_manager = manager
    app.state.sandbox_provider = provider

    logger.info("orchestrator.startup_complete")

    try:
        yield
    finally:
        if isinstance(provider, SpritesProvider):
            try:
                await provider.aclose()
            except Exception as exc:
                logger.warning("provider.close_failed", error=str(exc))

        await redis_client.disconnect()
        await mongo.disconnect()
        logger.info("orchestrator.shutdown_complete")


app = FastAPI(title="vibe-platform orchestrator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_base_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(me.router, prefix="/api", tags=["me"])
app.include_router(repos.router, prefix="/api/repos", tags=["repos"])
app.include_router(sandbox.router, prefix="/api/sandboxes", tags=["sandboxes"])


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness + Mongo reachability. 503 if Mongo is down so load balancers
    drop us out of rotation instead of accepting requests we can't serve."""
    mongo_ok = await mongo.ping()
    if not mongo_ok:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "mongo": False},
        )
    return JSONResponse(content={"status": "ok", "mongo": True})
