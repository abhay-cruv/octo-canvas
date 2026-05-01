"""GitHub adapter — the only module in this package that talks to GitHub.

Slice 4 will introduce a sibling `filesystem_source.py` with the same two
function signatures so `orchestrate` / `commands` can stay GitHub-agnostic.
"""

import base64
import binascii

from github_integration import call_with_reauth
from githubkit import GitHub, TokenAuthStrategy
from githubkit.exception import RequestFailed


async def fetch_tree(gh: GitHub[TokenAuthStrategy], owner: str, name: str, ref: str) -> set[str]:
    """Return the set of repo-relative paths at HEAD of `ref` (recursive).

    Empty set on a missing tree (e.g. brand-new empty repo). 404s on the ref
    itself bubble up — caller decides whether that's a hard failure.
    """
    resp = await call_with_reauth(
        lambda: gh.rest.git.async_get_tree(owner, name, ref, recursive="1")
    )
    return {item.path for item in resp.parsed_data.tree if item.path is not None}


async def fetch_blob_text(
    gh: GitHub[TokenAuthStrategy],
    owner: str,
    name: str,
    path: str,
    ref: str,
) -> str | None:
    """Fetch a single file's contents as utf-8 text.

    Returns None on 404, on a non-file response (directory, symlink, submodule),
    or on decode failure. Caller treats None as "no signal".
    """
    try:
        resp = await call_with_reauth(
            lambda: gh.rest.repos.async_get_content(owner, name, path, ref=ref)
        )
    except RequestFailed as exc:
        if exc.response.status_code == 404:
            return None
        raise

    parsed = resp.parsed_data
    # Contents API returns a union: ContentFile | list[...] | symlink | submodule.
    # Only the file variant has `.content` + `.encoding`.
    content = getattr(parsed, "content", None)
    encoding = getattr(parsed, "encoding", None)
    if not isinstance(content, str) or encoding != "base64":
        return None
    try:
        raw = base64.b64decode(content)
        return raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
