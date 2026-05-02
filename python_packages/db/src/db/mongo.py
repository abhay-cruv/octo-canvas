"""Process-singleton Mongo handle.

Wraps `pymongo.AsyncMongoClient` (the new async driver that replaced motor in
pymongo 4.9+) and Beanie's document-model registration. One instance per
process; lifecycle is owned by the FastAPI `lifespan` (or the test fixture).

Usage:

    from db import mongo

    await mongo.connect(settings.mongodb_uri)
    user = await User.find_one(User.github_user_id == 42)  # Beanie still works
    raw = await mongo.users.find_one({"github_user_id": 42})  # raw collection access too
    await mongo.disconnect()

The class deliberately exposes both Beanie ORM access (via the registered
Document classes) and raw collection access (`mongo.users`, `mongo.repos`) for
hot-path queries that don't need full validation.
"""

from typing import TYPE_CHECKING
from urllib.parse import urlparse

import structlog
from beanie import init_beanie
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from db.collections import ALL as ALL_COLLECTIONS
from db.collections import Collections
from db.models import AgentEvent, Repo, Sandbox, Session, Task, User

__all__ = ["ALL_COLLECTIONS", "Collections", "Mongo", "connect", "disconnect", "mongo"]

if TYPE_CHECKING:
    from pymongo.asynchronous.collection import AsyncCollection
    from pymongo.asynchronous.database import AsyncDatabase

_logger = structlog.get_logger("db")
_DEFAULT_DB_NAME = "octo_canvas"

# Every Beanie Document must appear here or it silently fails to query.
_DOCUMENT_MODELS: list[type] = [User, Session, Repo, Sandbox, Task, AgentEvent]


def _database_name(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.path and parsed.path != "/":
        return parsed.path.lstrip("/")
    return _DEFAULT_DB_NAME


class Mongo:
    """Process singleton. Acquire/release via `connect`/`disconnect`."""

    def __init__(self) -> None:
        self._client: AsyncMongoClient[dict[str, object]] | None = None
        self._db_name: str | None = None

    @property
    def client(self) -> "AsyncMongoClient[dict[str, object]]":
        if self._client is None:
            raise RuntimeError("Mongo.connect() not called")
        return self._client

    @property
    def db(self) -> "AsyncDatabase[dict[str, object]]":
        if self._db_name is None:
            raise RuntimeError("Mongo.connect() not called")
        return self.client[self._db_name]

    @property
    def db_name(self) -> str:
        if self._db_name is None:
            raise RuntimeError("Mongo.connect() not called")
        return self._db_name

    # Typed collection accessors. Names come from db.collections.Collections —
    # the single source of truth. Add one line per new collection here.
    @property
    def users(self) -> "AsyncCollection[dict[str, object]]":
        return self.db[Collections.USERS]

    @property
    def sessions(self) -> "AsyncCollection[dict[str, object]]":
        return self.db[Collections.SESSIONS]

    @property
    def repos(self) -> "AsyncCollection[dict[str, object]]":
        return self.db[Collections.REPOS]

    @property
    def sandboxes(self) -> "AsyncCollection[dict[str, object]]":
        return self.db[Collections.SANDBOXES]

    @property
    def tasks(self) -> "AsyncCollection[dict[str, object]]":
        return self.db[Collections.TASKS]

    @property
    def agent_events(self) -> "AsyncCollection[dict[str, object]]":
        return self.db[Collections.AGENT_EVENTS]

    @property
    def seq_counters(self) -> "AsyncCollection[dict[str, object]]":
        return self.db[Collections.SEQ_COUNTERS]

    def collection(self, name: str) -> "AsyncCollection[dict[str, object]]":
        """Escape hatch for migrations / one-off scripts that need to touch a
        collection by name. Prefer the typed properties for app code."""
        return self.db[name]

    async def connect(
        self,
        uri: str,
        *,
        database: str | None = None,
        register_models: bool = True,
    ) -> None:
        """Open the client, ping, and (optionally) register Beanie models.

        `database` overrides the path-component of `uri` — useful for tests.
        Set `register_models=False` if the caller wants to call `init_beanie`
        manually with a different model list (also useful for tests that scope
        to a subset).
        """
        db_name = database or _database_name(uri)
        if self._client is not None:
            # Idempotent: re-calling with the same db is a no-op (lets the
            # FastAPI lifespan and the test fixture both call connect without
            # tripping over each other). Switching DBs requires explicit
            # disconnect() first.
            if self._db_name == db_name:
                return
            raise RuntimeError(
                f"Mongo.connect({db_name!r}) but already connected to "
                f"{self._db_name!r}; call disconnect() first"
            )
        try:
            client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(uri)
            await client.admin.command("ping")
            if register_models:
                await init_beanie(
                    database=client[db_name],
                    document_models=_DOCUMENT_MODELS,
                )
        except PyMongoError as exc:
            _logger.error("db.connect_failed", database=db_name, error=str(exc))
            raise

        self._client = client
        self._db_name = db_name
        _logger.info("db.connected", database=db_name)

    async def disconnect(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None
        self._db_name = None
        _logger.info("db.disconnected")

    async def drop_all_collections(self) -> None:
        """Drop every collection registered in `db.collections.ALL`.

        Use this in test setup so each run starts against a clean DB with
        fresh indexes — `delete_many({})` keeps stale indexes around, which is
        a real footgun when schemas change.
        """
        for name in ALL_COLLECTIONS:
            await self.db.drop_collection(name)

    async def ping(self) -> bool:
        """Return True iff Mongo is reachable. Cheap; safe in /health."""
        if self._client is None:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except PyMongoError:
            return False


# Module-level singleton. Import as `from db import mongo` (also re-exported
# from db/__init__.py).
mongo = Mongo()


# Backwards-compatible thin wrappers — keep the old `connect` / `disconnect`
# names working for callers that haven't migrated to the singleton yet.


async def connect(uri: str, *, database: str | None = None) -> None:
    await mongo.connect(uri, database=database)


async def disconnect() -> None:
    await mongo.disconnect()
