"""Detect package manager from filenames + (for ambiguous Python) a manifest blob.

Lockfiles win when present — they're unambiguous proof of which manager runs
the project. Manifest-only fallbacks cover repos that haven't committed a
lockfile (mostly fresh `package.json`-only TS projects).
"""

from collections.abc import Awaitable, Callable

from shared_models.introspection import PackageManager

# (lockfile filename, package manager) — first match wins.
_LOCKFILES: tuple[tuple[str, PackageManager], ...] = (
    ("pnpm-lock.yaml", "pnpm"),
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
    ("yarn.lock", "yarn"),
    ("package-lock.json", "npm"),
    ("uv.lock", "uv"),
    ("poetry.lock", "poetry"),
    ("Cargo.lock", "cargo"),
    ("go.sum", "go"),
    ("Gemfile.lock", "bundler"),
)

_JS_LOCKS: frozenset[str] = frozenset(
    {"pnpm-lock.yaml", "yarn.lock", "package-lock.json", "bun.lockb", "bun.lock"}
)
_PY_LOCKS: frozenset[str] = frozenset({"uv.lock", "poetry.lock"})


def _root_files(paths: set[str]) -> set[str]:
    """Filenames that sit at the repo root — package-manager signals only count
    at the root in this slice. Nested `package.json` files (monorepo workspaces)
    don't change the root-level pm decision."""
    return {p for p in paths if "/" not in p}


async def detect_package_manager(
    paths: set[str],
    fetch_blob: Callable[[str], Awaitable[str | None]],
) -> PackageManager | None:
    """Return the project's package manager, or None.

    `fetch_blob(path)` is the curried `github_source.fetch_blob_text` bound to
    the right repo+ref; we use it once for `pyproject.toml` disambiguation.
    """
    root = _root_files(paths)

    for lockfile, pm in _LOCKFILES:
        if lockfile in root:
            return pm

    has_pkg_json = "package.json" in root
    has_pyproject = "pyproject.toml" in root
    has_requirements = "requirements.txt" in root
    has_gemfile = "Gemfile" in root

    if has_pkg_json and not (root & _JS_LOCKS):
        return "npm"

    if has_pyproject:
        text = await fetch_blob("pyproject.toml")
        if text is not None:
            if "[tool.uv" in text:
                return "uv"
            if "[tool.poetry" in text:
                return "poetry"
        if has_requirements:
            return "pip"
        return None

    if has_requirements:
        return "pip"

    if has_gemfile:
        return "bundler"

    if "pom.xml" in root:
        return "maven"

    if "build.gradle" in root or "build.gradle.kts" in root or "settings.gradle" in root:
        return "gradle"

    return None
