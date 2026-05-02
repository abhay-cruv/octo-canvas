from datetime import UTC, datetime

from shared_models.introspection import RepoIntrospection, Runtime

from agent_config.prompts import DevAgentPromptInputs, render_dev_agent_prompt


def _intro(**overrides: object) -> RepoIntrospection:
    base: dict[str, object] = {
        "primary_language": "TypeScript",
        "package_manager": "pnpm",
        "test_command": "pnpm test",
        "build_command": "pnpm build",
        "dev_command": "pnpm dev",
        "runtimes": [
            Runtime(name="node", version="20.11.0", source="package.json#engines.node"),
            Runtime(name="python", version="3.12.4", source=".python-version"),
        ],
        "system_packages": ["libpq-dev"],
        "detected_at": datetime(2026, 5, 2, tzinfo=UTC),
    }
    base.update(overrides)
    return RepoIntrospection.model_validate(base)


def test_renders_repo_identity_and_commands() -> None:
    inputs = DevAgentPromptInputs(
        repo_full_name="acme/web",
        default_branch="main",
        worktree_path="/work/acme/web",
        introspection=_intro(),
    )
    out = render_dev_agent_prompt(inputs)
    assert "acme/web" in out
    assert "/work/acme/web" in out
    assert "pnpm test" in out
    assert "pnpm dev" in out


def test_runtimes_section_lists_versions_and_does_not_instruct_install() -> None:
    inputs = DevAgentPromptInputs(
        repo_full_name="acme/web",
        default_branch="main",
        worktree_path="/work/acme/web",
        introspection=_intro(),
    )
    out = render_dev_agent_prompt(inputs)
    assert "node 20.11.0" in out
    assert "python 3.12.4" in out
    assert "already been installed" in out
    assert "nvm use" in out
    # Reconciler installs eagerly; the prompt only mentions install as a fallback.
    assert "fallback" in out


def test_no_runtimes_emits_default_message() -> None:
    inputs = DevAgentPromptInputs(
        repo_full_name="acme/web",
        default_branch="main",
        worktree_path="/work/acme/web",
        introspection=_intro(runtimes=[]),
    )
    out = render_dev_agent_prompt(inputs)
    assert "No language runtimes were detected" in out


def test_claude_md_text_appended_when_present() -> None:
    inputs = DevAgentPromptInputs(
        repo_full_name="acme/web",
        default_branch="main",
        worktree_path="/work/acme/web",
        introspection=_intro(),
        claude_md_text="Always run `pnpm lint` before commit.",
    )
    out = render_dev_agent_prompt(inputs)
    assert "## In-repo CLAUDE.md" in out
    assert "Always run `pnpm lint`" in out


def test_no_system_packages_section_when_empty() -> None:
    inputs = DevAgentPromptInputs(
        repo_full_name="acme/web",
        default_branch="main",
        worktree_path="/work/acme/web",
        introspection=_intro(system_packages=[]),
    )
    out = render_dev_agent_prompt(inputs)
    assert "## System packages" not in out


def test_output_is_stable_across_calls() -> None:
    inputs = DevAgentPromptInputs(
        repo_full_name="acme/web",
        default_branch="main",
        worktree_path="/work/acme/web",
        introspection=_intro(),
    )
    assert render_dev_agent_prompt(inputs) == render_dev_agent_prompt(inputs)
