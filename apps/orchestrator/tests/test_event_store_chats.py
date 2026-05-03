"""Chat-keyed event store + replay — slice 8 §4."""

from __future__ import annotations

from typing import Any

import pytest
from beanie import PydanticObjectId
from db.models import AgentEvent
from orchestrator.services.event_store import (
    _seq_key,
    append_chat_event,
    chat_channel_for,
    chat_user_agent_channel_for,
    is_important_for_user_agent,
    replay_chat,
)
from shared_models.wire_protocol import (
    BridgeAssistantMessage,
    BridgeErrorEvent,
    ResultMessage,
    ThinkingBlock,
)

pytestmark = pytest.mark.asyncio


def test_seq_key_is_chat_scoped() -> None:
    """Single seq space per chat — claude_session_id is intentionally
    ignored. Earlier we keyed by `(chat, session)` which split early-
    turn events (pre-`chat.started`, session=None) and post-session
    events into separate seq spaces, breaking FE replay ordering."""
    chat_id = PydanticObjectId()
    assert _seq_key(chat_id, None) == _seq_key(chat_id, "session-abc")


def test_channel_helpers() -> None:
    chat_id = PydanticObjectId()
    assert chat_channel_for(chat_id) == f"chat:{chat_id}"
    assert chat_user_agent_channel_for(chat_id) == f"chat:{chat_id}:ua"


async def test_append_assigns_monotonic_seq_per_chat(client: Any) -> None:
    _ = client
    chat_id = PydanticObjectId()
    payload = ThinkingBlock(chat_id=str(chat_id), seq=0, text="hmm")
    e1 = await append_chat_event(chat_id, payload, redis=None)
    e2 = await append_chat_event(chat_id, payload, redis=None)
    e3 = await append_chat_event(chat_id, payload, redis=None)
    assert e1.seq == 1
    assert e2.seq == 2
    assert e3.seq == 3


async def test_append_uses_unified_seq_space_across_sessions(client: Any) -> None:
    """Single seq counter per chat regardless of claude_session_id.
    Old test asserted (chat, session) namespaces — but mongo's
    `chat_session_seq_unique_partial` index would still collide on
    duplicate `(chat, session, seq)` combos when the global counter
    re-allocates a low seq for a session that already has one. Single
    space per chat avoids the whole class of problems and gives the
    FE a strictly-monotonic stream per chat."""
    _ = client
    chat_id = PydanticObjectId()
    no_session = ThinkingBlock(chat_id=str(chat_id), seq=0, text="a")
    in_session = ThinkingBlock(chat_id=str(chat_id), seq=0, text="b")
    e1 = await append_chat_event(chat_id, no_session, redis=None)
    e2 = await append_chat_event(
        chat_id, in_session, claude_session_id="sess-1", redis=None
    )
    e3 = await append_chat_event(
        chat_id, in_session, claude_session_id="sess-1", redis=None
    )
    assert e1.seq == 1
    assert e2.seq == 2
    assert e3.seq == 3


async def test_append_persists_to_agent_events_collection(client: Any) -> None:
    _ = client
    chat_id = PydanticObjectId()
    payload = BridgeAssistantMessage(
        chat_id=str(chat_id), seq=0, text="hello world"
    )
    await append_chat_event(chat_id, payload, redis=None)
    rows = await AgentEvent.find(AgentEvent.chat_id == chat_id).to_list()
    assert len(rows) == 1
    assert rows[0].chat_id == chat_id
    assert rows[0].task_id is None  # slice 8 events are NOT task-keyed
    assert rows[0].payload["type"] == "assistant.message"


async def test_replay_returns_events_above_threshold_in_order(client: Any) -> None:
    _ = client
    chat_id = PydanticObjectId()
    for i, text in enumerate(["a", "b", "c", "d"]):
        await append_chat_event(
            chat_id,
            ThinkingBlock(chat_id=str(chat_id), seq=0, text=text),
            redis=None,
        )
    out = await replay_chat(chat_id, after_seq=2)
    assert len(out) == 2
    # Each replayed event has its persisted seq + payload reconstructed.
    seqs = [getattr(e, "seq", None) for e in out]
    assert seqs == [3, 4]


async def test_replay_scopes_by_session_when_provided(client: Any) -> None:
    _ = client
    chat_id = PydanticObjectId()
    # Two events in `_global`, two in `sess-A`.
    for _ in range(2):
        await append_chat_event(
            chat_id,
            ThinkingBlock(chat_id=str(chat_id), seq=0, text="g"),
            redis=None,
        )
    for _ in range(2):
        await append_chat_event(
            chat_id,
            ThinkingBlock(chat_id=str(chat_id), seq=0, text="s"),
            claude_session_id="sess-A",
            redis=None,
        )
    no_session = await replay_chat(chat_id, after_seq=0)
    assert len(no_session) == 4  # session-id None → all events for the chat
    just_session = await replay_chat(
        chat_id, after_seq=0, claude_session_id="sess-A"
    )
    assert len(just_session) == 2


def test_user_agent_filter_set_matches_documented_calls() -> None:
    # Spot-check the contract from slice 8 §calls #5.
    assert is_important_for_user_agent("assistant.message")
    assert is_important_for_user_agent("result")
    assert is_important_for_user_agent("error")
    assert not is_important_for_user_agent("assistant.delta")
    assert not is_important_for_user_agent("thinking")
    assert not is_important_for_user_agent("tool.started")


async def test_result_and_error_payloads_round_trip(client: Any) -> None:
    """The wire payloads we expect the user agent to act on must
    serialize + deserialize cleanly through the event store."""
    _ = client
    chat_id = PydanticObjectId()
    result = ResultMessage(
        chat_id=str(chat_id),
        seq=0,
        claude_session_id="sess-x",
        duration_ms=42,
        is_error=False,
    )
    err = BridgeErrorEvent(
        chat_id=str(chat_id), seq=0, kind="cli_crash", message="boom"
    )
    e1 = await append_chat_event(chat_id, result, redis=None)
    e2 = await append_chat_event(chat_id, err, redis=None)
    assert e1.payload["type"] == "result"
    assert e1.payload["claude_session_id"] == "sess-x"
    assert e2.payload["type"] == "error"
    assert e2.payload["kind"] == "cli_crash"


@pytest.fixture(autouse=True)
async def _cleanup(client: Any) -> Any:
    _ = client
    yield
    await AgentEvent.delete_all()
