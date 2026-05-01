from typing import Protocol


class SandboxProvider(Protocol):
    """Sandbox provider interface. Methods will be added in a later slice."""

    # TODO: define create, resume, hibernate, destroy, exec methods in the sandbox slice.
    ...
