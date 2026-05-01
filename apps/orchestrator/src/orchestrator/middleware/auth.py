from datetime import UTC, datetime

from db.models import Session, User
from fastapi import HTTPException, Request, status

SESSION_COOKIE_NAME = "vibe_session"


async def _resolve_user(request: Request) -> User | None:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None

    session = await Session.find_one(Session.session_id == session_id)
    if session is None:
        return None

    now = datetime.now(UTC)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        return None

    session.last_used_at = now
    await session.save()

    user = await User.get(session.user_id)
    if user is None:
        return None

    return user


async def require_user(request: Request) -> User:
    user = await _resolve_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unauthenticated",
        )
    return user


async def get_user_optional(request: Request) -> User | None:
    return await _resolve_user(request)
