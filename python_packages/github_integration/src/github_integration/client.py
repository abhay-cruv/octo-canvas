"""Thin wrapper around githubkit for OAuth-token calls."""

from collections.abc import Awaitable, Callable

from githubkit import GitHub, TokenAuthStrategy
from githubkit.exception import RequestFailed

from .exceptions import GithubReauthRequired


def user_client(token: str) -> GitHub[TokenAuthStrategy]:
    return GitHub(TokenAuthStrategy(token))


async def call_with_reauth[T](fn: Callable[[], Awaitable[T]]) -> T:
    """Run a githubkit coroutine; convert HTTP 401 into GithubReauthRequired."""
    try:
        return await fn()
    except RequestFailed as exc:
        if exc.response.status_code == 401:
            raise GithubReauthRequired() from exc
        raise
