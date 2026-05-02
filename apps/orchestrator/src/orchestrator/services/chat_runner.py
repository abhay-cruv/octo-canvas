"""Chat lifecycle service — slice 8 §7.

`create_chat`, `add_follow_up`, `cancel_chat`. Bridges the HTTP route
layer (slice 8 §8) to the bridge↔WSS leg via `BridgeOwner.send`.

v1: chats run at `cwd=/work/`; no per-chat branch / worktree (slice 9
owns branching). Concurrency cap = `MAX_LIVE_CHATS_PER_SANDBOX` is
enforced bridge-side, not here — the orchestrator just queues
`UserMessage` frames and lets the bridge decide eviction.
"""

from __future__ import annotations

import structlog
from agent_config.llm_provider import LLMProvider
from beanie import PydanticObjectId
from db.models import Chat, ChatTurn, Sandbox, User
from shared_models.wire_protocol import (
    CancelChat,
    OrchestratorToBridgeAdapter,
    UserMessage,
)

from orchestrator.services.bridge_owner import BridgeOwner
from orchestrator.services.user_agent.enhance import (
    EnhancedPrompt,
    enhance_prompt,
)

_logger = structlog.get_logger("chat_runner")


class ChatRunnerError(Exception):
    """Raised on user-visible failures (no live sandbox, etc.). Routes
    catch and translate to the appropriate HTTP status."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def _user_sandbox(user: User) -> Sandbox:
    if user.id is None:
        raise ChatRunnerError("invalid_user", "user id missing")
    sandbox = await Sandbox.find_one(
        Sandbox.user_id == user.id,
        {"status": {"$ne": "destroyed"}},
    )
    if sandbox is None:
        raise ChatRunnerError(
            "no_sandbox", "no live sandbox — provision one first"
        )
    if sandbox.status not in ("warm", "running"):
        raise ChatRunnerError(
            "sandbox_not_ready", f"sandbox is {sandbox.status}"
        )
    return sandbox


async def _send_user_message_to_bridge(
    *,
    bridge_owner: BridgeOwner,
    sandbox: Sandbox,
    chat: Chat,
    text: str,
) -> None:
    """Serialize and send a `UserMessage` to the bridge."""
    if sandbox.id is None or chat.id is None:
        raise ChatRunnerError("invalid_state", "missing sandbox or chat id")
    msg = UserMessage(
        chat_id=str(chat.id),
        frame_id="",  # populated by BridgeOwner.send
        text=text,
        claude_session_id=chat.claude_session_id,
    )
    raw = OrchestratorToBridgeAdapter.dump_python(msg, mode="json")
    if not isinstance(raw, dict):
        raise ChatRunnerError("invalid_state", "frame serialization failed")
    delivered = await bridge_owner.send(str(sandbox.id), raw)
    if not delivered:
        raise ChatRunnerError(
            "bridge_unavailable",
            "bridge isn't connected — try again once it reconnects",
        )


async def create_chat(
    user: User,
    *,
    prompt: str,
    title: str | None = None,
    bridge_owner: BridgeOwner,
    user_agent_provider: LLMProvider | None,
) -> tuple[Chat, ChatTurn, EnhancedPrompt | None]:
    """Create a chat, run optional user-agent enhancement, send the
    first `UserMessage` to the bridge."""
    if user.id is None:
        raise ChatRunnerError("invalid_user", "user id missing")
    sandbox = await _user_sandbox(user)

    enhanced: EnhancedPrompt | None = None
    text_to_send = prompt
    if user.user_agent_enabled and user_agent_provider is not None:
        enhanced = await enhance_prompt(
            user.id,
            prompt,
            provider=user_agent_provider,
            model=user.user_agent_model,
        )
        text_to_send = enhanced.enhanced_text

    chat = Chat(
        user_id=user.id,
        title=title or _default_title(prompt),
        status="running",
        initial_prompt=prompt,
    )
    await chat.insert()
    assert chat.id is not None

    turn = ChatTurn(
        chat_id=chat.id,
        is_follow_up=False,
        prompt=prompt,
        enhanced_prompt=enhanced.enhanced_text if enhanced else None,
        status="running",
    )
    await turn.insert()

    await _send_user_message_to_bridge(
        bridge_owner=bridge_owner,
        sandbox=sandbox,
        chat=chat,
        text=text_to_send,
    )

    return chat, turn, enhanced


async def add_follow_up(
    user: User,
    chat: Chat,
    *,
    prompt: str,
    bridge_owner: BridgeOwner,
    user_agent_provider: LLMProvider | None,
) -> tuple[ChatTurn, EnhancedPrompt | None]:
    if user.id is None or chat.user_id != user.id:
        raise ChatRunnerError("not_owner", "not your chat")
    if chat.status in ("completed", "failed", "cancelled", "archived"):
        raise ChatRunnerError(
            "chat_closed", f"chat is {chat.status} — start a new one"
        )
    sandbox = await _user_sandbox(user)

    enhanced: EnhancedPrompt | None = None
    text_to_send = prompt
    if user.user_agent_enabled and user_agent_provider is not None:
        enhanced = await enhance_prompt(
            user.id,
            prompt,
            provider=user_agent_provider,
            model=user.user_agent_model,
        )
        text_to_send = enhanced.enhanced_text

    turn = ChatTurn(
        chat_id=chat.id if chat.id is not None else PydanticObjectId(),
        is_follow_up=True,
        prompt=prompt,
        enhanced_prompt=enhanced.enhanced_text if enhanced else None,
        status="running",
    )
    await turn.insert()

    chat.status = "running"
    await chat.save()

    await _send_user_message_to_bridge(
        bridge_owner=bridge_owner,
        sandbox=sandbox,
        chat=chat,
        text=text_to_send,
    )
    return turn, enhanced


async def cancel_chat(
    user: User,
    chat: Chat,
    *,
    bridge_owner: BridgeOwner,
) -> None:
    if chat.user_id != user.id:
        raise ChatRunnerError("not_owner", "not your chat")
    sandbox = await _user_sandbox(user)
    if chat.id is None or sandbox.id is None:
        return
    msg = CancelChat(chat_id=str(chat.id), frame_id="")
    raw = OrchestratorToBridgeAdapter.dump_python(msg, mode="json")
    if isinstance(raw, dict):
        await bridge_owner.send(str(sandbox.id), raw)
    chat.status = "cancelled"
    await chat.save()


def _default_title(prompt: str) -> str:
    """First line, truncated to 80 chars. The user-agent could rename
    this later via `Chat.save()` — out of scope for v1."""
    first = prompt.strip().split("\n", 1)[0].strip()
    if len(first) <= 80:
        return first or "New chat"
    return first[:77] + "..."
