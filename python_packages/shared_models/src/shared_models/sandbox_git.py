"""Pydantic shapes for `/api/sandboxes/{id}/git/*` (slice 6).

Read-only surfaces: `git status` and `git show`. Backed by
`provider.exec_oneshot` — no new Protocol method needed.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _GitModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


# `git status --porcelain=v1` two-character status codes per file.
# index status (XY[0]):  ' ' M A D R C U ?  -- staged change kind
# worktree status (XY[1]):  ' ' M D ?       -- unstaged change kind
# `??` = untracked.  See `man git-status`.


class GitStatusFile(_GitModel):
    """One changed file. `index` and `worktree` are single-char status
    codes; the FE renders them as VS Code-style M/A/U/D badges."""

    rel_path: str
    index: str  # one-char (e.g. ' ', 'M', 'A', 'D', '?')
    worktree: str  # one-char
    # For renames git porcelain emits the OLD path too. Keep it for the FE.
    rel_path_orig: str | None = None


class GitStatusResponse(_GitModel):
    repo_path: str
    branch: str | None
    detached: bool
    ahead: int
    behind: int
    files: list[GitStatusFile]
    # Slice 6 — when git itself failed (non-zero exit), we still return 200
    # with `files=[]` so one bad repo doesn't poison the panel; populate
    # `git_error` with the trimmed stderr so the FE can surface it in a
    # tooltip rather than silently showing "no changes".
    git_error: str | None = None


class GitShowResponse(_GitModel):
    """File content at a git ref. `exists=False` means the file does NOT
    exist at `ref` (e.g. an untracked or just-added file). The FE then
    renders an empty-vs-current diff."""

    repo_path: str
    rel_path: str
    ref: str
    exists: bool
    content: str  # empty when `exists=False`
    truncated: bool  # True if larger than the FE cap


GitRef = Literal["HEAD", "INDEX"]
