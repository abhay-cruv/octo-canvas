"""Repo introspection result — wire-shaped, embedded on `Repo` documents."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

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


class RepoIntrospection(BaseModel):
    primary_language: str | None
    package_manager: PackageManager | None
    test_command: str | None
    build_command: str | None
    dev_command: str | None
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
