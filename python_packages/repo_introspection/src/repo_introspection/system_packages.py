"""Detect Ubuntu apt packages required by a repo.

Best-effort heuristics. False positives are worse than misses (a wrong
package wastes clone time at install; a missed package is added via
`IntrospectionOverrides.system_packages`). Sources, in order of trust:

1. `Dockerfile` — `apt-get install ...` lines (most reliable).
2. `apt.txt` — Heroku/Render convention; one package per line.
3. `package.json#dependencies` — known native modules with system deps
   (`sharp`, `canvas`, `node-canvas`, etc.).
4. `requirements.txt` — known wheels with system deps (`psycopg2`, `lxml`,
   `pyodbc`).

The output is deduped and sorted for deterministic checkpoint reuse.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

FetchBlob = Callable[[str], Awaitable[str | None]]

# Multi-line aware regex for `apt-get install`. Skips flags, captures package
# names. Stops at line continuation handling — we feed it the joined logical
# line. Accepts both `apt-get` and `apt`.
_APT_INSTALL_RE = re.compile(
    r"\bapt(?:-get)?\s+(?:-[a-zA-Z]+\s+)*install\s+(?:-[a-zA-Z-]+\s+)*([^&|;\n]+)"
)
_PACKAGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")

# Known native-module → apt package mappings. Conservative — expand only
# when we see real-world repos that fail without the mapping.
_NPM_NATIVE: dict[str, list[str]] = {
    "sharp": ["libvips-dev"],
    "canvas": ["libcairo2-dev", "libpango1.0-dev", "libjpeg-dev", "libgif-dev"],
    "node-canvas": ["libcairo2-dev", "libpango1.0-dev", "libjpeg-dev", "libgif-dev"],
    "puppeteer": ["chromium"],
    "playwright": ["chromium"],
    "node-gyp": ["build-essential"],
    "bcrypt": ["build-essential"],
    "sqlite3": ["libsqlite3-dev"],
}

_PIP_NATIVE: dict[str, list[str]] = {
    "psycopg2": ["libpq-dev"],
    "psycopg2-binary": [],  # binary wheel — no system deps
    "psycopg": ["libpq-dev"],
    "lxml": ["libxml2-dev", "libxslt1-dev"],
    "pyodbc": ["unixodbc-dev"],
    "pillow": ["libjpeg-dev", "zlib1g-dev"],
    "cryptography": ["libssl-dev", "libffi-dev"],
    "mysqlclient": ["default-libmysqlclient-dev"],
    "cairocffi": ["libcairo2-dev"],
}


async def detect_system_packages(paths: set[str], fetch: FetchBlob) -> list[str]:
    bounded_paths = {p for p in paths if p.count("/") <= 2}
    found: set[str] = set()

    # 1. Dockerfile(s).
    for dockerfile in sorted(p for p in bounded_paths if p.endswith("Dockerfile")):
        text = await fetch(dockerfile)
        if text is None:
            continue
        for pkg in _parse_dockerfile_apt(text):
            found.add(pkg)

    # 2. apt.txt at root or one deep.
    for apt_path in [p for p in bounded_paths if p.endswith("apt.txt")]:
        text = await fetch(apt_path)
        if text is None:
            continue
        for line in text.splitlines():
            pkg = line.strip().split("#", 1)[0].strip()
            if pkg and _PACKAGE_NAME_RE.match(pkg):
                found.add(pkg)

    # 3. package.json#dependencies → known native module mappings.
    if "package.json" in bounded_paths:
        text = await fetch("package.json")
        if text is not None:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                for section in ("dependencies", "devDependencies", "optionalDependencies"):
                    deps = data.get(section)
                    if not isinstance(deps, dict):
                        continue
                    for dep_name in deps:
                        for pkg in _NPM_NATIVE.get(dep_name, []):
                            found.add(pkg)

    # 4. requirements.txt → known wheels.
    for req_path in [p for p in bounded_paths if p == "requirements.txt"]:
        text = await fetch(req_path)
        if text is None:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # `package==1.2.3`, `package>=1.0`, `package[extras]`, plain `package`.
            m = re.match(r"^([a-zA-Z0-9_.-]+)", stripped)
            if not m:
                continue
            pkg_name = m.group(1).lower()
            for sys_pkg in _PIP_NATIVE.get(pkg_name, []):
                found.add(sys_pkg)

    return sorted(found)


def _parse_dockerfile_apt(text: str) -> list[str]:
    """Extract apt-get install package names. Joins line continuations
    (`\\\n`) before regex-matching so multi-line installs are handled."""
    joined = re.sub(r"\\\s*\n\s*", " ", text)
    out: list[str] = []
    for match in _APT_INSTALL_RE.finditer(joined):
        candidate_block = match.group(1)
        for tok in candidate_block.split():
            tok = tok.strip()
            if not tok or tok.startswith("-") or tok in {"&&", "||", ";", "\\"}:
                continue
            # Drop version pins (`pkg=1.2.3`) — apt accepts the bare name.
            tok = tok.split("=", 1)[0]
            if _PACKAGE_NAME_RE.match(tok):
                out.append(tok)
    return out
