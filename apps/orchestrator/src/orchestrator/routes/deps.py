"""FastAPI dependencies that resolve request-scoped collaborators (provider,
manager) from process-singleton state held on `app.state`."""

from fastapi import Request

from ..services.reconciliation import Reconciler
from ..services.sandbox_manager import SandboxManager


def get_sandbox_manager(request: Request) -> SandboxManager:
    manager = getattr(request.app.state, "sandbox_manager", None)
    if not isinstance(manager, SandboxManager):
        raise RuntimeError("sandbox_manager not initialized on app.state")
    return manager


def get_reconciler(request: Request) -> Reconciler:
    rec = getattr(request.app.state, "reconciler", None)
    if not isinstance(rec, Reconciler):
        raise RuntimeError("reconciler not initialized on app.state")
    return rec
