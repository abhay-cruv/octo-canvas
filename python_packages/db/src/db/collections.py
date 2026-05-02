"""Single source of truth for Mongo collection names.

Every Beanie `Document.Settings.name` reads from this module, every typed
collection accessor in `db/mongo.py` reads from this module, and every test
or migration that needs to enumerate collections reads from this module. No
hand-typed `"users"` / `"repos"` strings anywhere else in the codebase.

This module deliberately imports nothing from `db.models` — keeps the
constants importable from inside the model files themselves without a cycle.
The Beanie Document → name binding (the `BEANIE_MODELS` list) lives in
`db/mongo.py` since that's the only file that needs both.

Adding a new collection: add a constant below, then in `db/mongo.py` import
the Document class and append it to `_BEANIE_MODELS` + add a typed accessor.
"""

from typing import Final


class Collections:
    """Canonical collection names. Use these instead of string literals."""

    USERS: Final = "users"
    SESSIONS: Final = "sessions"
    REPOS: Final = "repos"

    # Slice 4+ collections — declared here so the names are reserved and
    # refactor-safe even before the model classes exist.
    SANDBOXES: Final = "sandboxes"
    TASKS: Final = "tasks"
    AGENT_RUNS: Final = "agent_runs"
    AGENT_EVENTS: Final = "agent_events"
    # Slice 5a: per-task atomic seq allocator. Raw collection (no Beanie) —
    # `findOneAndUpdate {$inc: {next: 1}}` upsert is the only access pattern.
    SEQ_COUNTERS: Final = "seq_counters"


# Names of every collection currently materialized in Mongo. Iterate this in
# tests/migrations that need to touch *all* collections (e.g. drop-on-setup).
ALL: Final[tuple[str, ...]] = (
    Collections.USERS,
    Collections.SESSIONS,
    Collections.REPOS,
    Collections.SANDBOXES,
    Collections.TASKS,
    Collections.AGENT_EVENTS,
    Collections.SEQ_COUNTERS,
)
