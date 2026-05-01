import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from db.models import Session, User
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from shared_models import UserResponse

from ..lib.env import settings
from ..lib.logger import logger
from ..middleware.auth import SESSION_COOKIE_NAME, get_user_optional

router = APIRouter()

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"

OAUTH_STATE_COOKIE = "vibe_oauth_state"
OAUTH_SCOPE = "read:user user:email repo"
OAUTH_STATE_MAX_AGE = 10 * 60
SESSION_MAX_AGE = 7 * 24 * 60 * 60


def _cookie_kwargs(*, max_age: int) -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": settings.is_production,
        "samesite": "lax",
        "max_age": max_age,
        "path": "/",
    }


def _callback_url() -> str:
    base = settings.orchestrator_base_url.rstrip("/")
    return f"{base}/api/auth/github/callback"


def _make_oauth_client() -> AsyncOAuth2Client:
    return AsyncOAuth2Client(
        client_id=settings.github_oauth_client_id,
        client_secret=settings.github_oauth_client_secret,
        scope=OAUTH_SCOPE,
        redirect_uri=_callback_url(),
    )


async def _fetch_github_profile(access_token: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "vibe-platform",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        user_resp = await client.get(GITHUB_USER_URL, headers=headers)
        user_resp.raise_for_status()
        profile: dict[str, Any] = user_resp.json()

        if not profile.get("email"):
            emails_resp = await client.get(GITHUB_EMAILS_URL, headers=headers)
            emails_resp.raise_for_status()
            emails: list[dict[str, Any]] = emails_resp.json()
            primary = next(
                (e for e in emails if e.get("primary") and e.get("verified") and e.get("email")),
                None,
            )
            if primary is None:
                primary = next(
                    (e for e in emails if e.get("verified") and e.get("email")),
                    None,
                )
            if primary is not None:
                profile["email"] = primary["email"]

    return profile


async def _upsert_user(profile: dict[str, Any]) -> User:
    github_user_id = int(profile["id"])
    now = datetime.now(UTC)
    email = profile.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="github account has no usable email",
        )

    existing = await User.find_one(User.github_user_id == github_user_id)
    if existing is not None:
        existing.github_username = profile["login"]
        existing.github_avatar_url = profile.get("avatar_url")
        existing.email = email
        existing.display_name = profile.get("name")
        existing.last_signed_in_at = now
        existing.updated_at = now
        await existing.save()
        return existing

    user = User(
        github_user_id=github_user_id,
        github_username=profile["login"],
        github_avatar_url=profile.get("avatar_url"),
        email=email,
        display_name=profile.get("name"),
        last_signed_in_at=now,
        created_at=now,
        updated_at=now,
    )
    await user.create()
    return user


async def _create_session(user: User) -> str:
    session_id = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    if user.id is None:
        raise RuntimeError("user.id is None after persist")
    session = Session(
        session_id=session_id,
        user_id=user.id,
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(seconds=SESSION_MAX_AGE),
    )
    await session.create()
    return session_id


@router.get("/github/manage")
async def github_manage() -> RedirectResponse:
    """Send the user to the GitHub OAuth-app settings page where they can grant
    or request access for orgs that previously denied/restricted this app."""
    url = f"https://github.com/settings/connections/applications/{settings.github_oauth_client_id}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/github/login")
async def github_login() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    client = _make_oauth_client()
    try:
        url, _returned_state = client.create_authorization_url(  # pyright: ignore[reportUnknownMemberType]
            GITHUB_AUTHORIZE_URL,
            state=state,
        )
    finally:
        await client.aclose()  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]

    response = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        **_cookie_kwargs(max_age=OAUTH_STATE_MAX_AGE),
    )
    return response


@router.get("/github/callback")
async def github_callback(request: Request, code: str, state: str) -> RedirectResponse:
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not cookie_state or cookie_state != state:
        logger.warning("auth.state_mismatch")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid oauth state",
        )

    client = _make_oauth_client()
    try:
        token_raw = await client.fetch_token(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            GITHUB_TOKEN_URL,
            code=code,
            state=state,
        )
    except Exception as exc:
        logger.error("auth.token_exchange_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="token exchange failed",
        ) from exc
    finally:
        await client.aclose()  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]

    token = cast(dict[str, Any], token_raw)
    access_token = token.get("access_token")
    if not isinstance(access_token, str):
        logger.error("auth.no_access_token")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no access token returned",
        )

    try:
        profile = await _fetch_github_profile(access_token)
    except httpx.HTTPError as exc:
        logger.error("auth.profile_fetch_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="github profile fetch failed",
        ) from exc

    user = await _upsert_user(profile)
    user.github_access_token = access_token
    await user.save()

    if user.id is not None:
        await Session.find(
            Session.user_id == user.id,
            Session.expires_at < datetime.now(UTC),
        ).delete()

    session_id = await _create_session(user)
    logger.info("auth.signed_in", user_id=str(user.id))

    redirect = RedirectResponse(
        url=f"{settings.web_base_url.rstrip('/')}/dashboard",
        status_code=status.HTTP_302_FOUND,
    )
    redirect.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        **_cookie_kwargs(max_age=SESSION_MAX_AGE),
    )
    redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return redirect


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> Response:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        existing = await Session.find_one(Session.session_id == session_id)
        if existing is not None:
            await existing.delete()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/session", response_model=UserResponse)
async def session_info(user: User | None = Depends(get_user_optional)) -> UserResponse:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unauthenticated",
        )
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
