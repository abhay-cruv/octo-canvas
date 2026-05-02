"""Construct the right `SandboxProvider` based on `Settings.sandbox_provider`.

Explicit selection — no silent fallback. With `SANDBOX_PROVIDER=sprites` an
empty `SPRITES_TOKEN` aborts startup. With `SANDBOX_PROVIDER=mock` we boot
but emit a loud warning every time.
See [slice4.md §0 #8](../../../../docs/slice/slice4.md).
"""

from sandbox_provider import (
    MockSandboxProvider,
    SandboxProvider,
    SpritesProvider,
)

from .env import settings
from .logger import logger


def build_sandbox_provider() -> SandboxProvider:
    match settings.sandbox_provider:
        case "sprites":
            sprites_token = settings.sprites_token.get_secret_value()
            if not sprites_token:
                raise RuntimeError(
                    "SANDBOX_PROVIDER=sprites but SPRITES_TOKEN is empty. "
                    "Set the token, or set SANDBOX_PROVIDER=mock for local dev."
                )
            logger.info("sandbox_provider.sprites", base_url=settings.sprites_base_url)
            return SpritesProvider(token=sprites_token, base_url=settings.sprites_base_url)
        case "mock":
            logger.warning(
                "sandbox_provider.mock_in_use",
                hint="local dev only — never set SANDBOX_PROVIDER=mock in prod",
            )
            return MockSandboxProvider()
