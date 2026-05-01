"""FastAPI dependencies that resolve request-scoped collaborators (provider,
manager) from process-singleton state held on `app.state`."""

from fastapi import Request

from ..services.sandbox_manager import SandboxManager


def get_sandbox_manager(request: Request) -> SandboxManager:
    manager = getattr(request.app.state, "sandbox_manager", None)
    if not isinstance(manager, SandboxManager):
        raise RuntimeError("sandbox_manager not initialized on app.state")
    return manager
