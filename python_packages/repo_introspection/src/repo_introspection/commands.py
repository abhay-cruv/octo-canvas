"""Detect (test_command, build_command) given the package manager + manifests."""

import json
from collections.abc import Awaitable, Callable
from typing import TypedDict, cast

from shared_models.introspection import PackageManager


class _PkgJson(TypedDict, total=False):
    scripts: dict[str, str]


_JS_MANAGERS: frozenset[PackageManager] = frozenset({"pnpm", "yarn", "npm", "bun"})


async def _js_commands(
    pm: PackageManager, fetch_blob: Callable[[str], Awaitable[str | None]]
) -> tuple[str | None, str | None, str | None]:
    text = await fetch_blob("package.json")
    if text is None:
        return None, None, None
    try:
        parsed = cast(_PkgJson, json.loads(text))
    except (json.JSONDecodeError, ValueError):
        return None, None, None
    scripts = parsed.get("scripts", {}) if isinstance(parsed, dict) else {}
    if not isinstance(scripts, dict):
        return None, None, None
    test = f"{pm} test" if isinstance(scripts.get("test"), str) else None
    build = f"{pm} build" if isinstance(scripts.get("build"), str) else None
    if isinstance(scripts.get("dev"), str):
        dev = f"{pm} dev"
    elif isinstance(scripts.get("start"), str):
        dev = f"{pm} start"
    else:
        dev = None
    return test, build, dev


def _python_test_command(
    pm: PackageManager,
    paths: set[str],
    pyproject_text: str | None,
) -> str | None:
    if pm == "uv":
        return "uv run pytest"
    if pm == "poetry":
        return "poetry run pytest"
    if pm == "pip":
        has_pytest_signal = (
            "pytest.ini" in paths
            or any(p.startswith("tests/") for p in paths)
            or (pyproject_text is not None and "[tool.pytest" in pyproject_text)
        )
        return "pytest" if has_pytest_signal else None
    return None


async def detect_commands(
    paths: set[str],
    pm: PackageManager | None,
    fetch_blob: Callable[[str], Awaitable[str | None]],
) -> tuple[str | None, str | None, str | None]:
    """Return (test_command, build_command, dev_command) for the detected stack.

    `fetch_blob(path)` is bound to the repo+ref; we re-use it for `package.json`
    or `pyproject.toml` reads as needed.
    """
    if pm is None:
        return None, None, None

    if pm in _JS_MANAGERS:
        return await _js_commands(pm, fetch_blob)

    if pm in {"uv", "poetry", "pip"}:
        pyproject_text = await fetch_blob("pyproject.toml") if "pyproject.toml" in paths else None
        return _python_test_command(pm, paths, pyproject_text), None, None

    if pm == "cargo":
        return "cargo test", "cargo build", "cargo run"

    if pm == "go":
        return "go test ./...", "go build ./...", "go run ."

    if pm == "bundler":
        gemfile = await fetch_blob("Gemfile")
        if gemfile is not None and "rspec" in gemfile.lower():
            return "bundle exec rspec", None, None
        return None, None, None

    if pm == "maven":
        return "mvn test", "mvn package", None

    if pm == "gradle":
        return "gradle test", "gradle build", "gradle run"

    return None, None, None
