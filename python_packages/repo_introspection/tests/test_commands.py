import json
from collections.abc import Awaitable, Callable

import pytest
from repo_introspection.commands import detect_commands


def _stub_blobs(blobs: dict[str, str]) -> Callable[[str], Awaitable[str | None]]:
    async def fetch(path: str) -> str | None:
        return blobs.get(path)

    return fetch


@pytest.mark.asyncio
async def test_returns_triple_none_when_pm_is_none() -> None:
    assert await detect_commands(set(), None, _stub_blobs({})) == (None, None, None)


@pytest.mark.asyncio
async def test_pnpm_with_test_build_dev_scripts() -> None:
    pkg = json.dumps({"scripts": {"test": "vitest", "build": "tsc -b", "dev": "vite"}})
    test, build, dev = await detect_commands(
        {"pnpm-lock.yaml", "package.json"}, "pnpm", _stub_blobs({"package.json": pkg})
    )
    assert test == "pnpm test"
    assert build == "pnpm build"
    assert dev == "pnpm dev"


@pytest.mark.asyncio
async def test_pnpm_with_only_test_script() -> None:
    pkg = json.dumps({"scripts": {"test": "vitest"}})
    test, build, dev = await detect_commands(
        {"package.json"}, "pnpm", _stub_blobs({"package.json": pkg})
    )
    assert test == "pnpm test"
    assert build is None
    assert dev is None


@pytest.mark.asyncio
async def test_pnpm_dev_falls_back_to_start_script() -> None:
    pkg = json.dumps({"scripts": {"start": "node ./server.js"}})
    _, _, dev = await detect_commands(
        {"package.json"}, "pnpm", _stub_blobs({"package.json": pkg})
    )
    assert dev == "pnpm start"


@pytest.mark.asyncio
async def test_pnpm_dev_prefers_dev_over_start() -> None:
    pkg = json.dumps({"scripts": {"dev": "vite", "start": "node ./server.js"}})
    _, _, dev = await detect_commands(
        {"package.json"}, "pnpm", _stub_blobs({"package.json": pkg})
    )
    assert dev == "pnpm dev"


@pytest.mark.asyncio
async def test_pnpm_with_no_scripts_object() -> None:
    pkg = json.dumps({"name": "x"})
    assert await detect_commands(
        {"package.json"}, "pnpm", _stub_blobs({"package.json": pkg})
    ) == (None, None, None)


@pytest.mark.asyncio
async def test_pnpm_with_malformed_package_json() -> None:
    assert await detect_commands(
        {"package.json"}, "pnpm", _stub_blobs({"package.json": "{ not json"})
    ) == (None, None, None)


@pytest.mark.asyncio
async def test_pnpm_with_missing_package_json() -> None:
    assert await detect_commands({"pnpm-lock.yaml"}, "pnpm", _stub_blobs({})) == (
        None,
        None,
        None,
    )


@pytest.mark.asyncio
async def test_uv_returns_uv_run_pytest_no_dev() -> None:
    assert await detect_commands(
        {"pyproject.toml", "uv.lock"}, "uv", _stub_blobs({"pyproject.toml": "[tool.uv]\n"})
    ) == ("uv run pytest", None, None)


@pytest.mark.asyncio
async def test_poetry_returns_poetry_run_pytest_no_dev() -> None:
    assert await detect_commands({"pyproject.toml"}, "poetry", _stub_blobs({})) == (
        "poetry run pytest",
        None,
        None,
    )


@pytest.mark.asyncio
async def test_pip_with_pytest_signal_returns_pytest() -> None:
    paths = {"requirements.txt", "tests/test_x.py"}
    assert await detect_commands(paths, "pip", _stub_blobs({})) == ("pytest", None, None)


@pytest.mark.asyncio
async def test_pip_without_pytest_signal_returns_none() -> None:
    paths = {"requirements.txt", "main.py"}
    assert await detect_commands(paths, "pip", _stub_blobs({})) == (None, None, None)


@pytest.mark.asyncio
async def test_pip_with_pytest_ini_signal() -> None:
    paths = {"requirements.txt", "pytest.ini"}
    assert await detect_commands(paths, "pip", _stub_blobs({})) == ("pytest", None, None)


@pytest.mark.asyncio
async def test_pip_with_pytest_section_in_pyproject() -> None:
    paths = {"requirements.txt", "pyproject.toml"}
    text = "[tool.pytest.ini_options]\n"
    assert await detect_commands(paths, "pip", _stub_blobs({"pyproject.toml": text})) == (
        "pytest",
        None,
        None,
    )


@pytest.mark.asyncio
async def test_cargo_commands() -> None:
    assert await detect_commands({"Cargo.toml", "Cargo.lock"}, "cargo", _stub_blobs({})) == (
        "cargo test",
        "cargo build",
        "cargo run",
    )


@pytest.mark.asyncio
async def test_go_commands() -> None:
    assert await detect_commands({"go.mod", "go.sum"}, "go", _stub_blobs({})) == (
        "go test ./...",
        "go build ./...",
        "go run .",
    )


@pytest.mark.asyncio
async def test_bundler_with_rspec_in_gemfile() -> None:
    gemfile = "source 'https://rubygems.org'\ngem 'rspec'\n"
    assert await detect_commands(
        {"Gemfile", "Gemfile.lock"}, "bundler", _stub_blobs({"Gemfile": gemfile})
    ) == ("bundle exec rspec", None, None)


@pytest.mark.asyncio
async def test_bundler_without_rspec() -> None:
    assert await detect_commands(
        {"Gemfile"}, "bundler", _stub_blobs({"Gemfile": "source 'x'\n"})
    ) == (None, None, None)


@pytest.mark.asyncio
async def test_maven_commands() -> None:
    assert await detect_commands({"pom.xml"}, "maven", _stub_blobs({})) == (
        "mvn test",
        "mvn package",
        None,
    )


@pytest.mark.asyncio
async def test_gradle_commands() -> None:
    assert await detect_commands({"build.gradle"}, "gradle", _stub_blobs({})) == (
        "gradle test",
        "gradle build",
        "gradle run",
    )
