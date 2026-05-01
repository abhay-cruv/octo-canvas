from urllib.parse import urlparse

import structlog
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from db.models import Repo, Session, User

_logger = structlog.get_logger("db")
_client: AsyncIOMotorClient[dict[str, object]] | None = None


def _database_name(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.path and parsed.path != "/":
        return parsed.path.lstrip("/")
    return "vibe_platform"


async def connect(uri: str) -> None:
    global _client
    db_name = _database_name(uri)
    try:
        _client = AsyncIOMotorClient(uri)
        await _client.admin.command("ping")
        await init_beanie(
            database=_client[db_name],
            document_models=[User, Session, Repo],
        )
        _logger.info("db.connected", database=db_name)
    except Exception as exc:
        _logger.error("db.connect_failed", database=db_name, error=str(exc))
        raise


async def disconnect() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
        _logger.info("db.disconnected")
