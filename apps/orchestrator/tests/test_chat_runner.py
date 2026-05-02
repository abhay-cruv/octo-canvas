"""Chat service unit tests — slice 8 §7."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from beanie import PydanticObjectId
from db.models import Chat, Sandbox, User
from orchestrator.services.chat_runner import (
    ChatRunnerError,
    add_follow_up,
    cancel_chat,
    create_chat,
)
from shared_models.sandbox import SandboxStatus

pytestmark = pytest.mark.asyncio


class _FakeOwner:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self._fail = fail

    async def send(self, sandbox_id: str, frame: dict[str, Any]) -> bool:
        if self._fail:
            return False
        self.sent.append((sandbox_id, frame))
        return True


async def _seed_user(user_agent_enabled: bool = False) -> User:
    user = User(
        github_user_id=42,
        github_username="alice",
        email="alice@example.com",
        github_access_token="tok",
        user_agent_enabled=user_agent_enabled,
    )
    await user.insert()
    assert user.id is not None
    return user


async def _seed_sandbox(
    user: User,
    status: "SandboxStatus" = "warm",
) -> Sandbox:
    assert user.id is not None
    sb = Sandbox(
        user_id=user.id,
        provider_name="mock",
        status=status,
        bridge_token_hash="x",
        spawned_at=datetime.now(UTC),
    )
    await sb.insert()
    return sb


async def test_create_chat_persists_chat_and_turn_then_sends_user_message(
    client: Any,
) -> None:
    # `client` fixture is unused but loads the conftest db setup.
    _ = client
    user = await _seed_user()
    await _seed_sandbox(user)
    owner = _FakeOwner()
    chat, turn, enhanced = await create_chat(
        user,
        prompt="add HELLO.md",
        bridge_owner=owner,  # type: ignore[arg-type]
        user_agent_provider=None,  # disabled → passthrough
    )
    assert chat.id is not None
    assert chat.status == "running"
    assert chat.initial_prompt == "add HELLO.md"
    assert turn.is_follow_up is False
    assert turn.enhanced_prompt is None  # no enhancement when provider=None
    assert enhanced is None

    # Bridge frame sent.
    assert len(owner.sent) == 1
    sandbox_id, frame = owner.sent[0]
    assert frame["type"] == "bridge.user_message"
    assert frame["chat_id"] == str(chat.id)
    assert frame["text"] == "add HELLO.md"
    assert frame["claude_session_id"] is None


async def test_create_chat_no_sandbox_raises_409(client: Any) -> None:
    _ = client
    user = await _seed_user()
    owner = _FakeOwner()
    with pytest.raises(ChatRunnerError) as exc:
        await create_chat(
            user, prompt="x", bridge_owner=owner, user_agent_provider=None  # type: ignore[arg-type]
        )
    assert exc.value.code == "no_sandbox"


async def test_create_chat_unready_sandbox_raises_409(client: Any) -> None:
    _ = client
    user = await _seed_user()
    await _seed_sandbox(user, status="provisioning")
    owner = _FakeOwner()
    with pytest.raises(ChatRunnerError) as exc:
        await create_chat(
            user, prompt="x", bridge_owner=owner, user_agent_provider=None  # type: ignore[arg-type]
        )
    assert exc.value.code == "sandbox_not_ready"


async def test_create_chat_bridge_unavailable_raises(client: Any) -> None:
    _ = client
    user = await _seed_user()
    await _seed_sandbox(user)
    owner = _FakeOwner(fail=True)
    with pytest.raises(ChatRunnerError) as exc:
        await create_chat(
            user, prompt="x", bridge_owner=owner, user_agent_provider=None  # type: ignore[arg-type]
        )
    assert exc.value.code == "bridge_unavailable"


async def test_follow_up_uses_existing_session_id(client: Any) -> None:
    _ = client
    user = await _seed_user()
    await _seed_sandbox(user)
    owner = _FakeOwner()
    chat, _, _ = await create_chat(
        user, prompt="hi", bridge_owner=owner, user_agent_provider=None  # type: ignore[arg-type]
    )
    # Simulate the bridge having reported back a session id.
    chat.claude_session_id = "session-abc"
    await chat.save()

    turn, enhanced = await add_follow_up(
        user,
        chat,
        prompt="follow up",
        bridge_owner=owner,  # type: ignore[arg-type]
        user_agent_provider=None,
    )
    assert turn.is_follow_up is True
    assert enhanced is None
    # Last-sent frame carries the captured session id.
    _, frame = owner.sent[-1]
    assert frame["claude_session_id"] == "session-abc"
    assert frame["text"] == "follow up"


async def test_follow_up_on_closed_chat_raises(client: Any) -> None:
    _ = client
    user = await _seed_user()
    await _seed_sandbox(user)
    owner = _FakeOwner()
    chat, _, _ = await create_chat(
        user, prompt="hi", bridge_owner=owner, user_agent_provider=None  # type: ignore[arg-type]
    )
    chat.status = "completed"
    await chat.save()
    with pytest.raises(ChatRunnerError) as exc:
        await add_follow_up(
            user, chat, prompt="x", bridge_owner=owner, user_agent_provider=None  # type: ignore[arg-type]
        )
    assert exc.value.code == "chat_closed"


async def test_follow_up_other_user_chat_raises_not_owner(client: Any) -> None:
    _ = client
    alice = await _seed_user()
    await _seed_sandbox(alice)
    owner = _FakeOwner()
    chat, _, _ = await create_chat(
        alice, prompt="x", bridge_owner=owner, user_agent_provider=None  # type: ignore[arg-type]
    )
    # Different user.
    bob = User(
        github_user_id=99,
        github_username="bob",
        email="bob@example.com",
        github_access_token="t",
    )
    await bob.insert()
    with pytest.raises(ChatRunnerError) as exc:
        await add_follow_up(
            bob, chat, prompt="x", bridge_owner=owner, user_agent_provider=None  # type: ignore[arg-type]
        )
    assert exc.value.code == "not_owner"


async def test_cancel_chat_sends_frame_and_marks_cancelled(client: Any) -> None:
    _ = client
    user = await _seed_user()
    await _seed_sandbox(user)
    owner = _FakeOwner()
    chat, _, _ = await create_chat(
        user, prompt="x", bridge_owner=owner, user_agent_provider=None  # type: ignore[arg-type]
    )
    await cancel_chat(user, chat, bridge_owner=owner)  # type: ignore[arg-type]
    assert chat.status == "cancelled"
    # Last frame is a `bridge.cancel`.
    _, last = owner.sent[-1]
    assert last["type"] == "bridge.cancel"


async def test_cancel_chat_other_user_raises(client: Any) -> None:
    _ = client
    alice = await _seed_user()
    await _seed_sandbox(alice)
    owner = _FakeOwner()
    chat, _, _ = await create_chat(
        alice, prompt="x", bridge_owner=owner, user_agent_provider=None  # type: ignore[arg-type]
    )
    bob = User(
        github_user_id=88,
        github_username="bob",
        email="b@e.com",
        github_access_token="t",
    )
    await bob.insert()
    with pytest.raises(ChatRunnerError) as exc:
        await cancel_chat(bob, chat, bridge_owner=owner)  # type: ignore[arg-type]
    assert exc.value.code == "not_owner"


# Guarantee no state leak from these tests.
@pytest.fixture(autouse=True)
async def _cleanup(client: Any) -> Any:
    _ = client
    yield
    await Chat.delete_all()
    await Sandbox.delete_all()
    await User.delete_all()
    # Pyright placeholder — keeps PydanticObjectId import live.
    _ = PydanticObjectId
