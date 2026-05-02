"""Dev-agent system prompt template.

The bridge calls `render_dev_agent_prompt(...)` once per session spawn
in slice 8. Slice 7 only ships the renderer + tests; nothing imports it
from a hot path yet.

Inputs are the bare minimum to ground the agent in the user's repo:
- Repo identity (`full_name`, `default_branch`, `worktree_path`).
- Detected `RepoIntrospection` (commands, runtimes, system packages).
- Optional in-repo `CLAUDE.md` text (rendered verbatim under a header
  so the agent treats it as user instructions for that repo).

The prompt deliberately does NOT instruct the agent to run language-
runtime installers — slice 7's reconciler installs them eagerly via
`nvm install` / `pyenv install`. The agent is told what versions are
available and how to activate them per shell.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared_models.introspection import RepoIntrospection, Runtime


@dataclass(frozen=True)
class DevAgentPromptInputs:
    repo_full_name: str
    default_branch: str
    worktree_path: str
    introspection: RepoIntrospection
    claude_md_text: str | None = None


def render_dev_agent_prompt(inputs: DevAgentPromptInputs) -> str:
    intro = inputs.introspection
    sections: list[str] = [
        _header(inputs),
        _commands_section(intro),
        _runtimes_section(intro.runtimes),
        _system_packages_section(intro.system_packages),
        _conventions_section(),
    ]
    if inputs.claude_md_text:
        sections.append(_claude_md_section(inputs.claude_md_text))
    return "\n\n".join(s for s in sections if s)


def _header(inputs: DevAgentPromptInputs) -> str:
    return (
        f"You are the dev agent for the GitHub repo `{inputs.repo_full_name}`.\n"
        f"You are working inside a sandboxed Linux box. The user's repo is checked out\n"
        f"at `{inputs.worktree_path}` on branch `{inputs.default_branch}`.\n"
        f"Run all shell commands from there unless told otherwise."
    )


def _commands_section(intro: RepoIntrospection) -> str:
    lines: list[str] = ["## Detected commands"]
    rows: list[tuple[str, str | None]] = [
        ("primary language", intro.primary_language),
        ("package manager", intro.package_manager),
        ("install / dev", intro.dev_command),
        ("test", intro.test_command),
        ("build", intro.build_command),
    ]
    for label, value in rows:
        lines.append(f"- {label}: {value or '(not detected)'}")
    return "\n".join(lines)


def _runtimes_section(runtimes: list[Runtime]) -> str:
    if not runtimes:
        return (
            "## Language runtimes\n"
            "No language runtimes were detected for this repo. The system\n"
            "defaults are available; install additional versions only if the\n"
            "task requires it."
        )
    bullets = "\n".join(
        f"- {r.name} {r.version or '(unpinned)'} — pinned via `{r.source}`"
        for r in runtimes
    )
    return (
        "## Language runtimes\n"
        "These versions have already been installed by the orchestrator before\n"
        "your session started. Activate them per-shell rather than reinstalling:\n"
        "- Node: `nvm use <version>` (managed by nvm at `/usr/local/nvm`)\n"
        "- Python: `pyenv shell <version>` (managed by pyenv at `/usr/local/pyenv`)\n"
        "- Ruby: `rbenv shell <version>` (managed by rbenv at `/usr/local/rbenv`)\n"
        "If you discover a sub-project that needs a version not listed below,\n"
        "you may run `nvm install <ver>` / `pyenv install <ver>` as a fallback.\n\n"
        f"{bullets}"
    )


def _system_packages_section(packages: list[str]) -> str:
    if not packages:
        return ""
    joined = ", ".join(sorted(packages))
    return (
        "## System packages\n"
        f"The following apt packages were installed for this repo: {joined}.\n"
        "If a build fails for a missing system library, request it via the user\n"
        "rather than installing ad-hoc — the install belongs in introspection."
    )


def _conventions_section() -> str:
    return (
        "## Working conventions\n"
        "- Prefer the repo's own scripts (test/build/dev) over ad-hoc commands.\n"
        "- Make small, reviewable diffs. Don't refactor unrelated code.\n"
        "- When uncertain about user intent, call `ask_user_clarification`\n"
        "  rather than guessing.\n"
        "- Never push or open a PR — that's a separate user-driven step."
    )


def _claude_md_section(text: str) -> str:
    return f"## In-repo CLAUDE.md\n\n{text.strip()}"
