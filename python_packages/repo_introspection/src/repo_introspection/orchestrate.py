"""Single entry point: turn (gh, owner, name, ref) into a RepoIntrospection."""

from datetime import UTC, datetime
from functools import partial

from githubkit import GitHub, TokenAuthStrategy
from shared_models.introspection import RepoIntrospection

from repo_introspection.commands import detect_commands
from repo_introspection.github_source import fetch_blob_text, fetch_tree
from repo_introspection.language import detect_primary_language
from repo_introspection.package_manager import detect_package_manager


async def introspect_via_github(
    gh: GitHub[TokenAuthStrategy], owner: str, name: str, ref: str
) -> RepoIntrospection:
    paths = await fetch_tree(gh, owner, name, ref)
    fetch = partial(fetch_blob_text, gh, owner, name, ref=ref)

    language = detect_primary_language(paths)
    pm = await detect_package_manager(paths, fetch)
    test_cmd, build_cmd, dev_cmd = await detect_commands(paths, pm, fetch)

    return RepoIntrospection(
        primary_language=language,
        package_manager=pm,
        test_command=test_cmd,
        build_command=build_cmd,
        dev_command=dev_cmd,
        detected_at=datetime.now(UTC),
    )
