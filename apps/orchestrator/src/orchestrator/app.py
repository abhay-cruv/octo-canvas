from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from db import mongo
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .lib.env import settings
from .lib.logger import logger
from .routes import auth, me, repos


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    await mongo.connect(settings.mongodb_uri)
    logger.info("orchestrator.startup_complete")
    try:
        yield
    finally:
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
