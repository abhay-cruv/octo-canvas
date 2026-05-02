"""System-package detection — slice 5b introspection deepening."""

import json
from collections.abc import Awaitable, Callable

import pytest
from repo_introspection.system_packages import detect_system_packages


def _stub(blobs: dict[str, str]) -> Callable[[str], Awaitable[str | None]]:
    async def fetch(path: str) -> str | None:
        return blobs.get(path)

    return fetch


@pytest.mark.asyncio
async def test_dockerfile_apt_install_singleline() -> None:
    df = "FROM ubuntu:24.04\nRUN apt-get update && apt-get install -y libpq-dev curl\n"
    result = await detect_system_packages({"Dockerfile"}, _stub({"Dockerfile": df}))
    assert "libpq-dev" in result
    assert "curl" in result


@pytest.mark.asyncio
async def test_dockerfile_apt_install_multiline_continuation() -> None:
    df = """FROM ubuntu:24.04
RUN apt-get update && \\
    apt-get install -y \\
        libxml2-dev \\
        libxslt1-dev \\
        zlib1g-dev
"""
    result = await detect_system_packages({"Dockerfile"}, _stub({"Dockerfile": df}))
    assert set(result) >= {"libxml2-dev", "libxslt1-dev", "zlib1g-dev"}


@pytest.mark.asyncio
async def test_apt_txt() -> None:
    txt = "libpq-dev\n# comment\nffmpeg\n"
    result = await detect_system_packages({"apt.txt"}, _stub({"apt.txt": txt}))
    assert set(result) == {"libpq-dev", "ffmpeg"}


@pytest.mark.asyncio
async def test_npm_native_module_sharp() -> None:
    pkg = json.dumps({"dependencies": {"sharp": "^0.33"}})
    result = await detect_system_packages({"package.json"}, _stub({"package.json": pkg}))
    assert "libvips-dev" in result


@pytest.mark.asyncio
async def test_pip_native_psycopg2() -> None:
    req = "psycopg2==2.9.9\nfastapi>=0.110\n"
    result = await detect_system_packages(
        {"requirements.txt"}, _stub({"requirements.txt": req})
    )
    assert "libpq-dev" in result


@pytest.mark.asyncio
async def test_psycopg2_binary_no_system_dep() -> None:
    """`psycopg2-binary` ships a wheel — no system dep needed."""
    req = "psycopg2-binary==2.9.9\n"
    result = await detect_system_packages(
        {"requirements.txt"}, _stub({"requirements.txt": req})
    )
    assert "libpq-dev" not in result


@pytest.mark.asyncio
async def test_dedupe_across_sources() -> None:
    df = "RUN apt-get install -y libpq-dev"
    pkg = json.dumps({"dependencies": {"sharp": "^0.33"}})
    req = "psycopg2==2.9\n"
    result = await detect_system_packages(
        {"Dockerfile", "package.json", "requirements.txt"},
        _stub({"Dockerfile": df, "package.json": pkg, "requirements.txt": req}),
    )
    # libpq-dev appears in both Dockerfile and pip mapping — should be deduped.
    assert result.count("libpq-dev") == 1
    assert "libvips-dev" in result


@pytest.mark.asyncio
async def test_empty_repo_no_packages() -> None:
    assert await detect_system_packages(set(), _stub({})) == []


@pytest.mark.asyncio
async def test_dockerfile_skips_flags() -> None:
    df = "RUN apt-get install -y --no-install-recommends libpq-dev\n"
    result = await detect_system_packages({"Dockerfile"}, _stub({"Dockerfile": df}))
    assert result == ["libpq-dev"]


@pytest.mark.asyncio
async def test_dockerfile_strips_version_pin() -> None:
    df = "RUN apt-get install -y libpq-dev=14.10-1ubuntu1\n"
    result = await detect_system_packages({"Dockerfile"}, _stub({"Dockerfile": df}))
    assert result == ["libpq-dev"]
