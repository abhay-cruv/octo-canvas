"""Chat routes — slice 8 §8.

`POST /api/chats` (create), `GET /api/chats` (list), `GET /api/chats/{id}`
(detail), `POST /api/chats/{id}/messages` (follow-up),
`POST /api/chats/{id}/cancel`,
`POST /api/chats/{id}/clarifications/{cid}/answer` (manual clarification
answer — also overrides a pending agent-answer).

User-agent settings flow through `PATCH /api/me/settings`
(reserved — wires up in slice 8 §11; for now, the User model is
mutable directly via tests).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from beanie import PydanticObjectId
from db.models import Chat, ChatTurn, User
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..middleware.auth import require_user
from ..services.bridge_owner import BridgeOwner
from ..services.chat_runner import (
    ChatRunnerError,
    add_follow_up,
    cancel_chat,
    create_chat,
)
from ..services.user_agent.providers import AnthropicProvider

router = APIRouter()


class CreateChatBody(BaseModel):
    prompt: Annotated[str, Field(min_length=1, max_length=20000)]
    title: str | None = None


class FollowUpBody(BaseModel):
    prompt: Annotated[str, Field(min_length=1, max_length=20000)]


class ChatResponse(BaseModel):
    id: str
    title: str
    status: str
    initial_prompt: str
    claude_session_id: str | None
    tokens_input: int
    tokens_output: int
    last_alive_at: datetime | None
    created_at: datetime


class ChatTurnResponse(BaseModel):
    id: str
    chat_id: str
    is_follow_up: bool
    prompt: str
    enhanced_prompt: str | None
    status: str
    started_at: datetime
    ended_at: datetime | None


class CreateChatResponse(BaseModel):
    chat: ChatResponse
    turn: ChatTurnResponse
    enhanced: bool
    used_topics: list[str] = Field(default_factory=list)


def _chat_to_response(chat: Chat) -> ChatResponse:
    assert chat.id is not None
    return ChatResponse(
        id=str(chat.id),
        title=chat.title,
        status=chat.status,
        initial_prompt=chat.initial_prompt,
        claude_session_id=chat.claude_session_id,
        tokens_input=chat.tokens_input,
        tokens_output=chat.tokens_output,
        last_alive_at=chat.last_alive_at,
        created_at=chat.created_at,
    )


def _turn_to_response(turn: ChatTurn) -> ChatTurnResponse:
    assert turn.id is not None
    return ChatTurnResponse(
        id=str(turn.id),
        chat_id=str(turn.chat_id),
        is_follow_up=turn.is_follow_up,
        prompt=turn.prompt,
        enhanced_prompt=turn.enhanced_prompt,
        status=turn.status,
        started_at=turn.started_at,
        ended_at=turn.ended_at,
    )


def _bridge_owner(request: Request) -> BridgeOwner:
    owner = getattr(request.app.state, "bridge_owner", None)
    if owner is None:
        raise HTTPException(503, detail="bridge owner not initialized")
    return owner


def _user_agent_provider(request: Request, user: User) -> AnthropicProvider | None:
    """Build (or return cached) user-agent LLMProvider for the user.
    v1 only supports `anthropic`; other providers raise. When the
    user has user-agent disabled, returns None — callers skip
    enhancement entirely.

    The real Anthropic key is held in `bridge_config._anthropic_api_key`
    on app.state — we reuse it here for the user-agent's direct
    anthropic.com calls (NOT through the proxy — the user agent is
    on the orchestrator and can hold the key)."""
    if not user.user_agent_enabled:
        return None
    if user.user_agent_provider != "anthropic":
        # OpenAI / Gemini land later; for now disable enhancement
        # rather than failing the request.
        return None
    bridge_config = getattr(request.app.state, "bridge_config", None)
    api_key = (
        getattr(bridge_config, "_anthropic_api_key", None)
        if bridge_config is not None
        else None
    )
    if not api_key:
        return None
    return AnthropicProvider(api_key=api_key)


def _raise_chat_error(exc: ChatRunnerError) -> None:
    code_to_status = {
        "no_sandbox": status.HTTP_409_CONFLICT,
        "sandbox_not_ready": status.HTTP_409_CONFLICT,
        "bridge_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
        "not_owner": status.HTTP_403_FORBIDDEN,
        "chat_closed": status.HTTP_409_CONFLICT,
        "invalid_user": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "invalid_state": status.HTTP_500_INTERNAL_SERVER_ERROR,
    }
    raise HTTPException(
        code_to_status.get(exc.code, 400), detail={"code": exc.code, "message": str(exc)}
    )


@router.post("", response_model=CreateChatResponse, status_code=201)
async def post_chat(
    body: CreateChatBody,
    request: Request,
    user: User = Depends(require_user),
) -> CreateChatResponse:
    owner = _bridge_owner(request)
    provider = _user_agent_provider(request, user)
    try:
        chat, turn, enhanced = await create_chat(
            user,
            prompt=body.prompt,
            title=body.title,
            bridge_owner=owner,
            user_agent_provider=provider,
        )
    except ChatRunnerError as exc:
        _raise_chat_error(exc)
        raise  # unreachable; satisfies type checker
    return CreateChatResponse(
        chat=_chat_to_response(chat),
        turn=_turn_to_response(turn),
        enhanced=enhanced is not None and bool(enhanced.used_topics),
        used_topics=enhanced.used_topics if enhanced else [],
    )


@router.get("", response_model=list[ChatResponse])
async def list_chats(
    user: User = Depends(require_user),
    limit: int = 50,
) -> list[ChatResponse]:
    cursor = (
        Chat.find(Chat.user_id == user.id)
        .sort(-Chat.created_at)  # type: ignore[arg-type]
        .limit(limit)
    )
    rows = await cursor.to_list()
    return [_chat_to_response(c) for c in rows]


async def _load_chat_for_user(chat_id: str, user: User) -> Chat:
    try:
        cid = PydanticObjectId(chat_id)
    except Exception:
        raise HTTPException(404, detail="chat not found")
    chat = await Chat.get(cid)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(404, detail="chat not found")
    return chat


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(chat_id: str, user: User = Depends(require_user)) -> ChatResponse:
    chat = await _load_chat_for_user(chat_id, user)
    return _chat_to_response(chat)


class FollowUpResponse(BaseModel):
    turn: ChatTurnResponse
    enhanced: bool
    used_topics: list[str] = Field(default_factory=list)


@router.post("/{chat_id}/messages", response_model=FollowUpResponse, status_code=201)
async def post_message(
    chat_id: str,
    body: FollowUpBody,
    request: Request,
    user: User = Depends(require_user),
) -> FollowUpResponse:
    chat = await _load_chat_for_user(chat_id, user)
    owner = _bridge_owner(request)
    provider = _user_agent_provider(request, user)
    user_agent_loop = getattr(request.app.state, "user_agent_loop", None)
    try:
        turn, enhanced = await add_follow_up(
            user,
            chat,
            prompt=body.prompt,
            bridge_owner=owner,
            user_agent_provider=provider,
            user_agent_loop=user_agent_loop,
        )
    except ChatRunnerError as exc:
        _raise_chat_error(exc)
        raise
    return FollowUpResponse(
        turn=_turn_to_response(turn),
        enhanced=enhanced is not None and bool(enhanced.used_topics),
        used_topics=enhanced.used_topics if enhanced else [],
    )


@router.post("/{chat_id}/cancel", status_code=204)
async def post_cancel(
    chat_id: str,
    request: Request,
    user: User = Depends(require_user),
) -> None:
    chat = await _load_chat_for_user(chat_id, user)
    owner = _bridge_owner(request)
    try:
        await cancel_chat(user, chat, bridge_owner=owner)
    except ChatRunnerError as exc:
        _raise_chat_error(exc)
        raise


# Clarifications are not a separate channel: when the dev agent ends
# a turn with a question, the user (or the orchestrator-side user
# agent on their behalf) just sends another message via
# `POST /api/chats/{id}/messages`. No special clarification route.
