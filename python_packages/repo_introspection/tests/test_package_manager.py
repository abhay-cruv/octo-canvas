from collections.abc import Awaitable, Callable

import pytest
from repo_introspection.package_manager import detect_package_manager


def _stub_blob(text: str | None) -> Callable[[str], Awaitable[str | None]]:
    async def fetch(_: str) -> str | None:
        return text

    return fetch


@pytest.mark.asyncio
async def test_pnpm_lock_wins() -> None:
    paths = {"pnpm-lock.yaml", "package.json", "src/index.ts"}
    assert await detect_package_manager(paths, _stub_blob(None)) == "pnpm"


@pytest.mark.asyncio
async def test_yarn_lock() -> None:
    paths = {"yarn.lock", "package.json"}
    assert await detect_package_manager(paths, _stub_blob(None)) == "yarn"


@pytest.mark.asyncio
async def test_npm_lock() -> None:
    paths = {"package-lock.json", "package.json"}
    assert await detect_package_manager(paths, _stub_blob(None)) == "npm"


@pytest.mark.asyncio
async def test_bun_lock() -> None:
    paths = {"bun.lockb", "package.json"}
    assert await detect_package_manager(paths, _stub_blob(None)) == "bun"


@pytest.mark.asyncio
async def test_uv_lock() -> None:
    paths = {"uv.lock", "pyproject.toml"}
    assert await detect_package_manager(paths, _stub_blob("[tool.uv]\n")) == "uv"


@pytest.mark.asyncio
async def test_poetry_lock() -> None:
    paths = {"poetry.lock", "pyproject.toml"}
    assert await detect_package_manager(paths, _stub_blob(None)) == "poetry"


@pytest.mark.asyncio
async def test_cargo_lock() -> None:
    assert await detect_package_manager({"Cargo.lock", "Cargo.toml"}, _stub_blob(None)) == "cargo"


@pytest.mark.asyncio
async def test_go_sum() -> None:
    assert await detect_package_manager({"go.sum", "go.mod"}, _stub_blob(None)) == "go"


@pytest.mark.asyncio
async def test_gemfile_lock() -> None:
    assert await detect_package_manager({"Gemfile.lock", "Gemfile"}, _stub_blob(None)) == "bundler"


@pytest.mark.asyncio
async def test_package_json_only_falls_back_to_npm() -> None:
    paths = {"package.json", "src/index.ts"}
    assert await detect_package_manager(paths, _stub_blob(None)) == "npm"


@pytest.mark.asyncio
async def test_pyproject_with_uv_section() -> None:
    paths = {"pyproject.toml", "src/main.py"}
    text = "[project]\nname='x'\n[tool.uv]\nfoo = 1\n"
    assert await detect_package_manager(paths, _stub_blob(text)) == "uv"


@pytest.mark.asyncio
async def test_pyproject_with_poetry_section() -> None:
    paths = {"pyproject.toml", "src/main.py"}
    text = "[tool.poetry]\nname = 'x'\n"
    assert await detect_package_manager(paths, _stub_blob(text)) == "poetry"


@pytest.mark.asyncio
async def test_pyproject_with_neither_then_requirements_means_pip() -> None:
    paths = {"pyproject.toml", "requirements.txt", "src/main.py"}
    text = "[project]\nname='x'\n"
    assert await detect_package_manager(paths, _stub_blob(text)) == "pip"


@pytest.mark.asyncio
async def test_pyproject_with_neither_no_requirements_returns_none() -> None:
    paths = {"pyproject.toml", "src/main.py"}
    text = "[project]\nname='x'\n"
    assert await detect_package_manager(paths, _stub_blob(text)) is None


@pytest.mark.asyncio
async def test_requirements_txt_only_means_pip() -> None:
    paths = {"requirements.txt", "src/main.py"}
    assert await detect_package_manager(paths, _stub_blob(None)) == "pip"


@pytest.mark.asyncio
async def test_pom_xml_means_maven() -> None:
    paths = {"pom.xml", "src/Main.java"}
    assert await detect_package_manager(paths, _stub_blob(None)) == "maven"


@pytest.mark.asyncio
async def test_build_gradle_means_gradle() -> None:
    paths = {"build.gradle.kts", "src/Main.kt"}
    assert await detect_package_manager(paths, _stub_blob(None)) == "gradle"


@pytest.mark.asyncio
async def test_empty_returns_none() -> None:
    assert await detect_package_manager(set(), _stub_blob(None)) is None


@pytest.mark.asyncio
async def test_nested_package_json_does_not_signal_root_pm() -> None:
    paths = {"apps/web/package.json", "src/main.py"}
    assert await detect_package_manager(paths, _stub_blob(None)) is None
