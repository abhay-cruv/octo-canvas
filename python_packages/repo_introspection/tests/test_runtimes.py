"""Runtime detection — slice 5b introspection deepening."""

import json
from collections.abc import Awaitable, Callable

import pytest
from repo_introspection.runtimes import detect_runtimes


def _stub(blobs: dict[str, str]) -> Callable[[str], Awaitable[str | None]]:
    async def fetch(path: str) -> str | None:
        return blobs.get(path)

    return fetch


@pytest.mark.asyncio
async def test_node_from_package_json_engines() -> None:
    pkg = json.dumps({"engines": {"node": ">=20.0.0"}})
    result = await detect_runtimes({"package.json"}, _stub({"package.json": pkg}))
    assert len(result) == 1
    assert result[0].name == "node"
    assert result[0].version == "20.0.0"
    assert result[0].source == "package.json#engines.node"


@pytest.mark.asyncio
async def test_nvmrc_when_no_engines() -> None:
    result = await detect_runtimes(
        {".nvmrc"}, _stub({".nvmrc": "v20.10.0\n"})
    )
    assert result[0].name == "node"
    assert result[0].version == "20.10.0"
    assert result[0].source == ".nvmrc"


@pytest.mark.asyncio
async def test_python_from_pyproject_requires() -> None:
    pyproject = '[project]\nrequires-python = ">=3.12"\n'
    result = await detect_runtimes(
        {"pyproject.toml"}, _stub({"pyproject.toml": pyproject})
    )
    assert result[0].name == "python"
    assert result[0].version == "3.12"


@pytest.mark.asyncio
async def test_go_mod_directive() -> None:
    gomod = "module github.com/x/y\n\ngo 1.22\n"
    result = await detect_runtimes({"go.mod"}, _stub({"go.mod": gomod}))
    assert result[0].name == "go"
    assert result[0].version == "1.22"


@pytest.mark.asyncio
async def test_multiple_runtimes_in_monorepo() -> None:
    blobs = {
        "package.json": json.dumps({"engines": {"node": "20"}}),
        "pyproject.toml": '[project]\nrequires-python = ">=3.11"\n',
        "go.mod": "module x\n\ngo 1.22\n",
    }
    result = await detect_runtimes(set(blobs), _stub(blobs))
    names = [r.name for r in result]
    assert names == ["go", "node", "python"]  # alphabetical


@pytest.mark.asyncio
async def test_empty_repo_no_signals() -> None:
    assert await detect_runtimes(set(), _stub({})) == []


@pytest.mark.asyncio
async def test_ruby_from_ruby_version() -> None:
    result = await detect_runtimes(
        {".ruby-version"}, _stub({".ruby-version": "3.2.2\n"})
    )
    assert result[0].name == "ruby"
    assert result[0].version == "3.2.2"


@pytest.mark.asyncio
async def test_runtime_without_version_still_emitted() -> None:
    """build.gradle with no parseable version still records `java` so the
    sandbox env-prep knows to install JDK in slice 6."""
    result = await detect_runtimes({"build.gradle"}, _stub({}))
    assert result[0].name == "java"
    assert result[0].version is None
