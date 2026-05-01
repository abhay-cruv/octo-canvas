"""Detect language/package-manager/test/build for a connected repo via GitHub APIs.

Single public entry point: `introspect_via_github`. Internals are split per
responsibility (language, package_manager, commands, github adapter) so slice 4
can swap the GitHub adapter for a filesystem one without touching the rest.
"""

from shared_models.introspection import PackageManager, RepoIntrospection

from repo_introspection.orchestrate import introspect_via_github

__all__ = ["PackageManager", "RepoIntrospection", "introspect_via_github"]
