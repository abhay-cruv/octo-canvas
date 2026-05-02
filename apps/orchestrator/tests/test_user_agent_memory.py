"""User-agent memory CRUD — slice 8 §calls #6."""

from __future__ import annotations

from typing import Any

import pytest
from beanie import PydanticObjectId
from db.models import UserAgentMemory
from orchestrator.services.user_agent.memory import (
    delete_memory,
    list_memory,
    read_memory,
    write_memory,
)

pytestmark = pytest.mark.asyncio


async def test_write_creates_then_updates_topic(client: Any) -> None:
    _ = client
    uid = PydanticObjectId()
    await write_memory(
        uid,
        name="prefs",
        kind="user",
        description="UI preferences",
        body="dark theme",
    )
    body = await read_memory(uid, "prefs")
    assert body == "dark theme"
    # Update the same topic — should upsert, not duplicate.
    await write_memory(
        uid,
        name="prefs",
        kind="user",
        description="UI preferences",
        body="dark theme; tabs not spaces",
    )
    body = await read_memory(uid, "prefs")
    assert body == "dark theme; tabs not spaces"
    # Still exactly one row for this user+name.
    rows = await UserAgentMemory.find(
        UserAgentMemory.user_id == uid, UserAgentMemory.name == "prefs"
    ).to_list()
    assert len(rows) == 1


async def test_list_excludes_index_doc(client: Any) -> None:
    _ = client
    uid = PydanticObjectId()
    # Index doc + two real topics.
    await write_memory(
        uid, name="MEMORY", kind="index", description="", body="- prefs\n- proj_x"
    )
    await write_memory(
        uid, name="prefs", kind="user", description="prefs", body="x"
    )
    await write_memory(
        uid, name="proj_x", kind="project", description="proj x notes", body="y"
    )
    entries = await list_memory(uid)
    names = sorted(e.name for e in entries)
    assert names == ["prefs", "proj_x"]
    # Each entry surfaces description for relevance scoring without
    # loading the body.
    by_name = {e.name: e for e in entries}
    assert by_name["prefs"].description == "prefs"
    assert by_name["prefs"].kind == "user"


async def test_delete_removes_topic_and_returns_true(client: Any) -> None:
    _ = client
    uid = PydanticObjectId()
    await write_memory(uid, name="x", kind="user", description="", body="b")
    assert await delete_memory(uid, "x") is True
    assert await read_memory(uid, "x") is None


async def test_delete_unknown_returns_false(client: Any) -> None:
    _ = client
    uid = PydanticObjectId()
    assert await delete_memory(uid, "nope") is False


async def test_per_user_isolation(client: Any) -> None:
    _ = client
    alice = PydanticObjectId()
    bob = PydanticObjectId()
    await write_memory(
        alice, name="prefs", kind="user", description="alice's", body="alice"
    )
    await write_memory(
        bob, name="prefs", kind="user", description="bob's", body="bob"
    )
    assert await read_memory(alice, "prefs") == "alice"
    assert await read_memory(bob, "prefs") == "bob"
    alice_entries = await list_memory(alice)
    assert len(alice_entries) == 1
    assert alice_entries[0].description == "alice's"


@pytest.fixture(autouse=True)
async def _cleanup(client: Any) -> Any:
    _ = client
    yield
    await UserAgentMemory.delete_all()
