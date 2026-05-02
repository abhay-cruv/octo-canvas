"""Repo introspection result — wire-shaped, embedded on `Repo` documents."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PackageManager = Literal[
    "pnpm",
    "npm",
    "yarn",
    "uv",
    "poetry",
    "pip",
    "cargo",
    "go",
    "bundler",
    "bun",
    "maven",
    "gradle",
    "other",
]

# Slice 5b: runtimes detected per repo. Multiple supported (monorepo).
RuntimeName = Literal["node", "python", "go", "ruby", "rust", "java"]


class Runtime(BaseModel):
    name: RuntimeName
    version: str | None = None  # None when no version file present
    source: str  # "package.json#engines.node", ".nvmrc", "go.mod", etc.


class RepoIntrospection(BaseModel):
    primary_language: str | None
    package_manager: PackageManager | None
    test_command: str | None
    build_command: str | None
    dev_command: str | None
    # Slice 5b additions — `default_factory=list` so existing Mongo rows that
    # don't yet have these fields read back as empty lists.
    runtimes: list[Runtime] = Field(default_factory=list)
    system_packages: list[str] = Field(default_factory=list)
    detected_at: datetime


class IntrospectionOverrides(BaseModel):
    """Sparse user overrides for `RepoIntrospection`.

    A `None` field means "no override — fall back to the detected value".
    A non-`None` field means "use this instead of whatever was detected".

    To remove an override, the client sends `null` (which the server stores as
    "field not overridden"). v1 has no way to *force-clear* a non-null detected
    value to null — if you need to silence a detected value, set the override
    to a placeholder string. Surface a real "clear" toggle in v1.1 if it bites.
    """

    primary_language: str | None = None
    package_manager: PackageManager | None = None
    test_command: str | None = None
    build_command: str | None = None
    dev_command: str | None = None
    # Slice 5b: list-typed overrides — empty list `[]` means "user wants no
    # detected entries"; `None` means "no override, use detected".
    runtimes: list[Runtime] | None = None
    system_packages: list[str] | None = None
