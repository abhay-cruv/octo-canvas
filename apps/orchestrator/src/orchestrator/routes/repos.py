from typing import NoReturn

from beanie import PydanticObjectId
from db.models import Repo, User
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from github_integration import GithubReauthRequired, call_with_reauth, user_client
from githubkit import GitHub, TokenAuthStrategy
from repo_introspection import introspect_via_github
from shared_models import (
    AvailableRepo,
    AvailableReposPage,
    ConnectedRepo,
    ConnectRepoRequest,
    IntrospectionOverrides,
    RepoIntrospection,
)

from ..lib.logger import logger
from ..middleware.auth import require_user

router = APIRouter()

REAUTH_DETAIL = "github_reauth_required"

# Field names a user is allowed to override. Keep in sync with
# `IntrospectionOverrides`. `detected_at` is intentionally not overridable.
_OVERRIDE_FIELDS: tuple[str, ...] = (
    "primary_language",
    "package_manager",
    "test_command",
    "build_command",
    "dev_command",
)


def _merge(
    detected: RepoIntrospection | None, overrides: IntrospectionOverrides | None
) -> RepoIntrospection | None:
    """Merge user overrides on top of detected values. Non-None override fields
    win; None override fields fall back to the detected value.

    If detection hasn't run yet, returns None even when overrides are set —
    the wire shape exposes `introspection_overrides` separately so the UI can
    render them; consumers that need a guaranteed merged value should
    re-introspect first.
    """
    if detected is None:
        return None
    base = detected.model_dump()
    if overrides is not None:
        for field in _OVERRIDE_FIELDS:
            value = getattr(overrides, field)
            if value is not None:
                base[field] = value
    return RepoIntrospection(**base)


def _to_response(doc: Repo) -> ConnectedRepo:
    return ConnectedRepo(
        id=str(doc.id),
        github_repo_id=doc.github_repo_id,
        full_name=doc.full_name,
        default_branch=doc.default_branch,
        private=doc.private,
        clone_status=doc.clone_status,
        connected_at=doc.connected_at,
        introspection=_merge(doc.introspection_detected, doc.introspection_overrides),
        introspection_detected=doc.introspection_detected,
        introspection_overrides=doc.introspection_overrides,
    )


async def _introspect_into(doc: Repo, gh: GitHub[TokenAuthStrategy], user: User) -> None:
    """Run introspection against GitHub and persist on `doc`.

    `GithubReauthRequired` propagates so the caller can clear the token.
    Any other failure is logged and swallowed — the connection is the
    user-facing operation; a missing introspection is recoverable via
    `POST /api/repos/{id}/reintrospect`.
    """
    owner, name = doc.full_name.split("/", 1)
    try:
        result = await introspect_via_github(gh, owner, name, doc.default_branch)
    except GithubReauthRequired:
        raise
    except Exception as exc:
        logger.warning(
            "repos.introspect_failed",
            repo_id=str(doc.id),
            full_name=doc.full_name,
            user_id=str(user.id),
            error=str(exc),
        )
        return
    doc.introspection_detected = result
    await doc.save()


async def _require_token(user: User) -> str:
    if user.github_access_token is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=REAUTH_DETAIL)
    return user.github_access_token


async def _on_reauth(user: User) -> NoReturn:
    user.github_access_token = None
    await user.save()
    logger.info("repos.token_cleared", user_id=str(user.id))
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=REAUTH_DETAIL)


@router.get("/available", response_model=AvailableReposPage)
async def list_available_repos(
    user: User = Depends(require_user),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    scope_mine: bool = Query(default=True),
) -> AvailableReposPage:
    token = await _require_token(user)
    gh = user_client(token)
    connected_ids = {r.github_repo_id for r in await Repo.find(Repo.user_id == user.id).to_list()}

    query = (q or "").strip()
    if query:
        # FE sends scope_mine=true by default; user can toggle it off to search
        # all of GitHub. When on, we scope via user:/org: qualifiers since
        # /search/repositories has no native "my access" filter.
        scope = ""
        if scope_mine:
            try:
                orgs_resp = await call_with_reauth(
                    lambda: gh.rest.orgs.async_list_for_authenticated_user(per_page=100)
                )
            except GithubReauthRequired:
                await _on_reauth(user)
            org_logins = [o.login for o in orgs_resp.parsed_data]
            scope = " " + " ".join(
                [f"user:{user.github_username}", *(f"org:{o}" for o in org_logins)]
            )
        qualified = f"{query} in:name,full_name fork:true{scope}"

        try:
            resp = await call_with_reauth(
                lambda: gh.rest.search.async_repos(
                    q=qualified,
                    sort="updated",
                    order="desc",
                    page=page,
                    per_page=per_page,
                )
            )
        except GithubReauthRequired:
            await _on_reauth(user)
        parsed = resp.parsed_data
        repos = [
            AvailableRepo(
                github_repo_id=r.id,
                full_name=r.full_name,
                default_branch=r.default_branch or "main",
                private=r.private,
                description=r.description,
                is_connected=r.id in connected_ids,
            )
            for r in parsed.items
        ]
        # GitHub's search hard-caps at 1000 results.
        total = min(parsed.total_count, 1000)
        return AvailableReposPage(
            repos=repos,
            page=page,
            per_page=per_page,
            has_more=page * per_page < total,
        )

    try:
        resp = await call_with_reauth(
            lambda: gh.rest.repos.async_list_for_authenticated_user(
                visibility="all",
                affiliation="owner,collaborator,organization_member",
                sort="pushed",
                direction="desc",
                page=page,
                per_page=per_page,
            )
        )
    except GithubReauthRequired:
        await _on_reauth(user)

    raw = resp.parsed_data
    repos = [
        AvailableRepo(
            github_repo_id=r.id,
            full_name=r.full_name,
            default_branch=r.default_branch,
            private=r.private,
            description=r.description,
            is_connected=r.id in connected_ids,
        )
        for r in raw
    ]
    return AvailableReposPage(
        repos=repos,
        page=page,
        per_page=per_page,
        has_more=len(raw) == per_page,
    )


@router.get("", response_model=list[ConnectedRepo])
async def list_connected_repos(
    user: User = Depends(require_user),
) -> list[ConnectedRepo]:
    docs = await Repo.find(Repo.user_id == user.id).to_list()
    return [_to_response(d) for d in docs]


@router.post("/connect", response_model=ConnectedRepo, status_code=status.HTTP_201_CREATED)
async def connect_repo(
    body: ConnectRepoRequest, user: User = Depends(require_user)
) -> ConnectedRepo:
    token = await _require_token(user)

    if "/" not in body.full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="full_name must be 'owner/repo'",
        )
    owner, repo_name = body.full_name.split("/", 1)

    # Scope the duplicate check to *this user's* connections. A different user
    # connecting the same github_repo_id is fine. Slice 4 will further scope to
    # the chosen sandbox, allowing the same user to connect a repo to multiple
    # sandboxes.
    existing = await Repo.find_one(
        Repo.user_id == user.id,
        Repo.github_repo_id == body.github_repo_id,
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="repo already connected",
        )

    if user.id is None:
        raise RuntimeError("user.id is None")

    gh = user_client(token)
    try:
        resp = await call_with_reauth(lambda: gh.rest.repos.async_get(owner=owner, repo=repo_name))
    except GithubReauthRequired:
        await _on_reauth(user)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("repos.connect.fetch_failed", full_name=body.full_name, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="repo not accessible"
        ) from exc

    repo_data = resp.parsed_data
    if repo_data.id != body.github_repo_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="full_name and github_repo_id mismatch",
        )

    doc = Repo(
        user_id=user.id,
        github_repo_id=body.github_repo_id,
        full_name=repo_data.full_name,
        default_branch=repo_data.default_branch,
        private=repo_data.private,
    )
    await doc.create()
    logger.info(
        "repos.connected",
        repo_id=str(doc.id),
        full_name=doc.full_name,
        user_id=str(user.id),
    )

    try:
        await _introspect_into(doc, gh, user)
    except GithubReauthRequired:
        await _on_reauth(user)

    return _to_response(doc)


@router.post("/{repo_id}/reintrospect", response_model=ConnectedRepo)
async def reintrospect_repo(
    repo_id: PydanticObjectId, user: User = Depends(require_user)
) -> ConnectedRepo:
    token = await _require_token(user)
    doc = await Repo.get(repo_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="repo not found")

    gh = user_client(token)
    try:
        await _introspect_into(doc, gh, user)
    except GithubReauthRequired:
        await _on_reauth(user)
    logger.info(
        "repos.reintrospected",
        repo_id=str(doc.id),
        full_name=doc.full_name,
        user_id=str(user.id),
    )
    return _to_response(doc)


@router.patch("/{repo_id}/introspection", response_model=ConnectedRepo)
async def update_introspection_overrides(
    repo_id: PydanticObjectId,
    body: IntrospectionOverrides,
    user: User = Depends(require_user),
) -> ConnectedRepo:
    """Replace the user's overrides for this repo (full replacement, not merge).

    Send `IntrospectionOverrides()` (all-null) to clear every override.
    Send any subset of fields populated to override only those.
    """
    doc = await Repo.get(repo_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="repo not found")

    has_any = any(getattr(body, f) is not None for f in _OVERRIDE_FIELDS)
    doc.introspection_overrides = body if has_any else None
    await doc.save()
    logger.info(
        "repos.introspection_overrides_updated",
        repo_id=str(doc.id),
        full_name=doc.full_name,
        user_id=str(user.id),
        overridden_fields=[f for f in _OVERRIDE_FIELDS if getattr(body, f) is not None],
    )
    return _to_response(doc)


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_repo(
    repo_id: PydanticObjectId, user: User = Depends(require_user)
) -> Response:
    doc = await Repo.get(repo_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="repo not found")
    await doc.delete()
    logger.info("repos.disconnected", repo_id=str(repo_id), user_id=str(user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
