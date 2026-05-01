from db.models import User
from fastapi import APIRouter, Depends
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
