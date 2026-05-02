"""Detect runtimes (Node, Python, Go, Ruby, Rust, Java) from version files.

Heuristics over the repo tree + a handful of contents fetches. Conservative —
we only emit a `Runtime` entry when we have a concrete signal. Versions are
optional (`None` when the file declares the runtime but not the version).

Multiple runtimes per repo are supported (monorepos with both backend +
frontend, build tools that pull in JVM, etc.). Order is alphabetical by
runtime name to keep the output stable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

from shared_models.introspection import Runtime, RuntimeName

FetchBlob = Callable[[str], Awaitable[str | None]]

_NODE_VERSION_RE = re.compile(r"v?\s*([0-9]+(?:\.[0-9]+){0,2})")
_PYTHON_REQUIRES_RE = re.compile(r"['\"]([^'\"]+)['\"]")
_GO_MOD_RE = re.compile(r"^go\s+([0-9]+(?:\.[0-9]+){1,2})", re.MULTILINE)
_RUBY_VERSION_RE = re.compile(r"([0-9]+(?:\.[0-9]+){1,2}(?:-?[a-z0-9]+)?)")
_RUST_TOOLCHAIN_RE = re.compile(r"^channel\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_CARGO_RUST_VERSION_RE = re.compile(r'^\s*rust-version\s*=\s*"([^"]+)"', re.MULTILINE)
_JAVA_VERSION_RE = re.compile(r"<java\.version>\s*([^<\s]+)\s*</java\.version>")


async def detect_runtimes(paths: set[str], fetch: FetchBlob) -> list[Runtime]:
    """Return all runtimes detected anywhere in the repo tree.

    `paths` is the set returned by `fetch_tree`; `fetch(path)` returns the
    file's contents as text or `None` if it's missing / undecodable. We walk
    only the top three depths (`a`, `a/b`, `a/b/c`) to keep monorepo scans
    bounded — same convention as the existing introspection detectors.
    """

    found: dict[RuntimeName, Runtime] = {}
    bounded_paths = {p for p in paths if p.count("/") <= 2}

    # Node: package.json#engines.node beats .nvmrc beats .node-version.
    node_via_pkg = await _node_from_package_json(bounded_paths, fetch)
    if node_via_pkg is not None:
        found["node"] = node_via_pkg
    else:
        nvmrc = await _read_first(["nvmrc", ".nvmrc"], bounded_paths, fetch)
        if nvmrc is not None:
            m = _NODE_VERSION_RE.search(nvmrc.strip())
            found["node"] = Runtime(name="node", version=m.group(1) if m else None, source=".nvmrc")
        else:
            ver = await _read_first([".node-version"], bounded_paths, fetch)
            if ver is not None:
                m = _NODE_VERSION_RE.search(ver.strip())
                found["node"] = Runtime(
                    name="node", version=m.group(1) if m else None, source=".node-version"
                )

    # Python: pyproject.toml#requires-python beats .python-version beats runtime.txt.
    py_via_pyproject = await _python_from_pyproject(bounded_paths, fetch)
    if py_via_pyproject is not None:
        found["python"] = py_via_pyproject
    else:
        pv = await _read_first([".python-version"], bounded_paths, fetch)
        if pv is not None:
            m = _NODE_VERSION_RE.search(pv.strip())
            found["python"] = Runtime(
                name="python", version=m.group(1) if m else None, source=".python-version"
            )
        else:
            rt = await _read_first(["runtime.txt"], bounded_paths, fetch)
            if rt is not None:
                # Heroku format: "python-3.12.1"
                m = re.search(r"python-([0-9]+(?:\.[0-9]+){0,2})", rt)
                if m:
                    found["python"] = Runtime(
                        name="python", version=m.group(1), source="runtime.txt"
                    )

    # Go: go.mod's `go 1.x[.y]` directive.
    gomod = await _read_first(["go.mod"], bounded_paths, fetch)
    if gomod is not None:
        m = _GO_MOD_RE.search(gomod)
        found["go"] = Runtime(name="go", version=m.group(1) if m else None, source="go.mod")

    # Ruby: .ruby-version beats Gemfile-declared ruby.
    rb = await _read_first([".ruby-version"], bounded_paths, fetch)
    if rb is not None:
        m = _RUBY_VERSION_RE.search(rb.strip())
        found["ruby"] = Runtime(
            name="ruby", version=m.group(1) if m else None, source=".ruby-version"
        )
    elif _has_any(bounded_paths, "Gemfile"):
        gemfile = await fetch("Gemfile")
        if gemfile is not None:
            m = re.search(r"^\s*ruby\s+['\"]([^'\"]+)['\"]", gemfile, re.MULTILINE)
            if m:
                found["ruby"] = Runtime(name="ruby", version=m.group(1), source="Gemfile#ruby")
            else:
                found["ruby"] = Runtime(name="ruby", version=None, source="Gemfile")

    # Rust: rust-toolchain[.toml] beats Cargo.toml#package.rust-version.
    toolchain = await _read_first(["rust-toolchain.toml", "rust-toolchain"], bounded_paths, fetch)
    if toolchain is not None:
        m = _RUST_TOOLCHAIN_RE.search(toolchain)
        if m:
            found["rust"] = Runtime(name="rust", version=m.group(1), source="rust-toolchain")
        else:
            stripped = toolchain.strip()
            found["rust"] = Runtime(
                name="rust",
                version=stripped if stripped and "\n" not in stripped else None,
                source="rust-toolchain",
            )
    elif "Cargo.toml" in bounded_paths:
        cargo = await fetch("Cargo.toml")
        if cargo is not None:
            m = _CARGO_RUST_VERSION_RE.search(cargo)
            found["rust"] = Runtime(
                name="rust",
                version=m.group(1) if m else None,
                source="Cargo.toml#rust-version" if m else "Cargo.toml",
            )

    # Java: pom.xml#java.version is the canonical Maven signal; build.gradle is
    # too unstructured to parse reliably, so we just emit name-only there.
    if "pom.xml" in bounded_paths:
        pom = await fetch("pom.xml")
        if pom is not None:
            m = _JAVA_VERSION_RE.search(pom)
            found["java"] = Runtime(
                name="java",
                version=m.group(1) if m else None,
                source="pom.xml#java.version" if m else "pom.xml",
            )
    elif _has_any(bounded_paths, "build.gradle", "build.gradle.kts"):
        found["java"] = Runtime(name="java", version=None, source="build.gradle")

    # Stable order — alphabetical by name.
    return [found[name] for name in sorted(found)]


async def _node_from_package_json(paths: set[str], fetch: FetchBlob) -> Runtime | None:
    if "package.json" not in paths:
        return None
    raw = await fetch("package.json")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    engines = data.get("engines") if isinstance(data, dict) else None
    if not isinstance(engines, dict):
        return None
    node = engines.get("node")
    if not isinstance(node, str):
        return None
    m = _NODE_VERSION_RE.search(node)
    return Runtime(
        name="node",
        version=m.group(1) if m else None,
        source="package.json#engines.node",
    )


async def _python_from_pyproject(paths: set[str], fetch: FetchBlob) -> Runtime | None:
    if "pyproject.toml" not in paths:
        return None
    raw = await fetch("pyproject.toml")
    if raw is None:
        return None
    # `requires-python = ">=3.12"` — a real TOML parse would be cleaner but
    # the stdlib `tomllib` requires bytes and the pattern is tight enough.
    m = re.search(r'^\s*requires-python\s*=\s*"([^"]+)"', raw, re.MULTILINE) or re.search(
        r"^\s*requires-python\s*=\s*'([^']+)'", raw, re.MULTILINE
    )
    if m is None:
        return None
    spec = m.group(1).strip()
    ver_match = _NODE_VERSION_RE.search(spec)
    return Runtime(
        name="python",
        version=ver_match.group(1) if ver_match else None,
        source="pyproject.toml#requires-python",
    )


async def _read_first(candidates: list[str], paths: set[str], fetch: FetchBlob) -> str | None:
    for c in candidates:
        if c in paths:
            text = await fetch(c)
            if text is not None:
                return text
    return None


def _has_any(paths: set[str], *names: str) -> bool:
    return any(n in paths for n in names)
