from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from db import connect, disconnect
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .lib.env import settings
from .lib.logger import logger
from .routes import auth, me


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    await connect(settings.mongodb_uri)
    logger.info("orchestrator.startup_complete")
    try:
        yield
    finally:
        await disconnect()
        logger.info("orchestrator.shutdown_complete")


app = FastAPI(title="vibe-platform orchestrator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_base_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(me.router, prefix="/api", tags=["me"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
