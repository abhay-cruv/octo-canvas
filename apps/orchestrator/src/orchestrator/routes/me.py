from typing import Literal

from db.models import User
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from shared_models import UserResponse

from ..middleware.auth import require_user

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(require_user)) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        github_user_id=user.github_user_id,
        github_username=user.github_username,
        github_avatar_url=user.github_avatar_url,
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
        last_signed_in_at=user.last_signed_in_at,
        needs_github_reauth=user.github_access_token is None,
    )


class UserSettingsResponse(BaseModel):
    """Slice 8: user-agent settings surfaced separately from the
    profile because they're agent-runtime config, not identity."""

    user_agent_enabled: bool
    user_agent_provider: Literal["anthropic", "openai", "google"]
    user_agent_model: str
    chat_permission_mode: Literal["all_granted", "ask"]


class UpdateUserSettingsBody(BaseModel):
    user_agent_enabled: bool | None = None
    user_agent_provider: Literal["anthropic", "openai", "google"] | None = None
    user_agent_model: str | None = None
    chat_permission_mode: Literal["all_granted", "ask"] | None = None


@router.get("/me/settings", response_model=UserSettingsResponse)
async def get_settings(user: User = Depends(require_user)) -> UserSettingsResponse:
    return UserSettingsResponse(
        user_agent_enabled=user.user_agent_enabled,
        user_agent_provider=user.user_agent_provider,
        user_agent_model=user.user_agent_model,
        chat_permission_mode=user.chat_permission_mode,
    )


@router.patch("/me/settings", response_model=UserSettingsResponse)
async def patch_settings(
    body: UpdateUserSettingsBody, user: User = Depends(require_user)
) -> UserSettingsResponse:
    """Partial update — only fields the body sets are touched. The
    user agent's provider Protocol means flipping `user_agent_provider`
    swaps to a different `LLMProvider` impl on the next chat without
    a schema migration (slice 8 §calls #3).

    `chat_permission_mode` flips take effect on the NEXT chat the user
    creates (the SDK's permission_mode is locked at spawn time). Live
    chats keep the mode they were created with."""
    if body.user_agent_enabled is not None:
        user.user_agent_enabled = body.user_agent_enabled
    if body.user_agent_provider is not None:
        user.user_agent_provider = body.user_agent_provider
    if body.user_agent_model is not None:
        # Defensive: cap at a reasonable length, reject empty.
        model = body.user_agent_model.strip()
        if model:
            user.user_agent_model = model[:200]
    if body.chat_permission_mode is not None:
        user.chat_permission_mode = body.chat_permission_mode
    await user.save()
    return UserSettingsResponse(
        user_agent_enabled=user.user_agent_enabled,
        user_agent_provider=user.user_agent_provider,
        user_agent_model=user.user_agent_model,
        chat_permission_mode=user.chat_permission_mode,
    )
