"""SpritesProvider — `sprites-py` SDK behind the SandboxProvider Protocol.

The SDK is synchronous; we wrap calls in `asyncio.to_thread` so the rest of
the orchestrator stays event-loop-friendly. The SDK is the only Sprites
import in the codebase — any swap to a different backend stays inside this
module.

Sprite naming: `octo-sbx-{sandbox_id}` where `sandbox_id` is the Mongo
ObjectId. Reset (slice 4) destroys+recreates with the same name; slice 5b
will switch Reset to `restore_checkpoint("clean")` and stop rotating the
Sprite on every reset.

The SDK installed is rc37 (latest on PyPI as of 2026-05-01). The rc43 docs
in [docs/sprites/v0.0.1-rc43/python.md](../../../../docs/sprites/v0.0.1-rc43/python.md)
(Python examples) and
[docs/sprites/v0.0.1-rc43/http.md](../../../../docs/sprites/v0.0.1-rc43/http.md)
(raw HTTP) describe the same surface for everything slice 4 touches —
`create_sprite`, `get_sprite`, `delete_sprite`, the `cold|warm|running`
status enum, and the per-sprite URL.
"""

import asyncio

import structlog
from sprites import (
    AuthenticationError as SDKAuthenticationError,
)
from sprites import (
    NotFoundError,
    Sprite,
    SpriteError,
    SpritesClient,
)

from sandbox_provider.interface import (
    ProviderName,
    ProviderStatus,
    SandboxHandle,
    SandboxState,
    SpritesError,
)

_logger = structlog.get_logger("sandbox_provider.sprites")

# Sprites' status enum maps 1:1 onto our ProviderStatus.
_STATUS_MAP: dict[str, ProviderStatus] = {
    "cold": "cold",
    "warm": "warm",
    "running": "running",
}


class SpritesProvider:
    """Wraps `sprites-py.SpritesClient`. The SDK is sync; we offload to a
    thread so the orchestrator's async loop isn't blocked on Sprites HTTP."""

    name: ProviderName = "sprites"

    def __init__(self, *, token: str, base_url: str = "https://api.sprites.dev") -> None:
        if not token:
            raise ValueError("SpritesProvider requires a non-empty token")
        self._client = SpritesClient(token=token, base_url=base_url)

    async def aclose(self) -> None:
        await asyncio.to_thread(self._client.close)

    async def create(self, *, sandbox_id: str, labels: list[str]) -> SandboxHandle:
        sprite_name = _name_for(sandbox_id)
        # `create_sprite` returns a Sprite with only `name` populated. Chain
        # with `get_sprite` so the handle carries the SDK-assigned UUID id.
        # `labels` is reserved for the rc43 SDK; rc37's create_sprite signature
        # doesn't accept it. Carrying the param keeps callers unchanged.
        _ = labels

        def _create_then_fetch() -> Sprite:
            self._client.create_sprite(sprite_name)
            return self._client.get_sprite(sprite_name)

        try:
            sprite = await asyncio.to_thread(_create_then_fetch)
        except SDKAuthenticationError as exc:
            raise SpritesError(_sanitize(exc), retriable=False) from exc
        except SpriteError as exc:
            raise SpritesError(_sanitize(exc), retriable=_is_retriable(exc)) from exc

        _logger.info(
            "sprites.created",
            sandbox_id=sandbox_id,
            sprite_name=sprite.name,
            sprite_id=sprite.id,
            url=sprite.url,
        )
        return _to_handle(sprite)

    async def status(self, handle: SandboxHandle) -> SandboxState:
        sprite_name = _require_name(handle)
        try:
            sprite = await asyncio.to_thread(self._client.get_sprite, sprite_name)
        except NotFoundError as exc:
            raise SpritesError(f"sprite {sprite_name!r} not found", retriable=False) from exc
        except SpriteError as exc:
            raise SpritesError(_sanitize(exc), retriable=_is_retriable(exc)) from exc
        return _to_state(sprite)

    async def destroy(self, handle: SandboxHandle) -> None:
        sprite_name = _require_name(handle)
        try:
            await asyncio.to_thread(self._client.delete_sprite, sprite_name)
        except NotFoundError:
            # Idempotent — already gone.
            _logger.info("sprites.destroy_already_gone", sprite_name=sprite_name)
            return
        except SpriteError as exc:
            raise SpritesError(_sanitize(exc), retriable=_is_retriable(exc)) from exc

    async def wake(self, handle: SandboxHandle) -> SandboxState:
        """Force a `cold` sprite to `warm`/`running` by issuing a no-op exec.
        Sprites auto-wakes on any access; this is just an explicit nudge so
        the user's "Start" / "Resume" button has predictable feedback."""
        sprite_name = _require_name(handle)

        def _ping() -> Sprite:
            sprite = self._client.sprite(sprite_name)
            cmd = sprite.command("true")
            try:
                cmd.run()
            except SpriteError:
                # Swallow — the request landed; the sprite is now warming
                # regardless of whether `true` returned an exit code.
                pass
            return self._client.get_sprite(sprite_name)

        try:
            sprite = await asyncio.to_thread(_ping)
        except NotFoundError as exc:
            raise SpritesError(f"sprite {sprite_name!r} not found", retriable=False) from exc
        except SpriteError as exc:
            raise SpritesError(_sanitize(exc), retriable=_is_retriable(exc)) from exc
        return _to_state(sprite)

    async def pause(self, handle: SandboxHandle) -> SandboxState:
        """Force the sprite to release compute by killing all active exec
        sessions; Sprites' own idle timer then transitions the sprite to
        `cold`. Returns whatever status Sprites currently reports — the
        sprite may still be `warm` for a few seconds before going cold.

        rc37 SDK does not expose `kill_session`; we POST the kill endpoint
        directly via the SDK's `_client` (same auth, same base_url) per the
        rc43 docs (POST /v1/sprites/{name}/exec/{session_id}/kill).
        Per-session kill failures are logged but do not abort the pause —
        a session that 404s during the race window is already gone.
        """
        sprite_name = _require_name(handle)

        def _kill_then_status() -> Sprite:
            sprite = self._client.sprite(sprite_name)
            try:
                sessions = sprite.list_sessions()
            except NotFoundError:
                # Sprite is gone; let status() raise the right error below.
                sessions = []
            killed = 0
            for session in sessions:
                session_id = getattr(session, "id", None)
                if not isinstance(session_id, str) or not session_id:
                    continue
                try:
                    resp = self._client._client.post(  # type: ignore[reportPrivateUsage]
                        f"{self._client.base_url}/v1/sprites/{sprite_name}/exec/{session_id}/kill",
                        headers=self._client._headers(),  # type: ignore[reportPrivateUsage]
                        timeout=10.0,
                    )
                    if resp.status_code >= 400 and resp.status_code != 404:
                        _logger.warning(
                            "sprites.pause.kill_failed",
                            sprite=sprite_name,
                            session=session_id,
                            status=resp.status_code,
                        )
                    else:
                        killed += 1
                except Exception as exc:
                    _logger.warning(
                        "sprites.pause.kill_error",
                        sprite=sprite_name,
                        session=session_id,
                        error=str(exc),
                    )
            _logger.info("sprites.pause", sprite=sprite_name, sessions_killed=killed)
            return self._client.get_sprite(sprite_name)

        try:
            sprite = await asyncio.to_thread(_kill_then_status)
        except NotFoundError as exc:
            raise SpritesError(f"sprite {sprite_name!r} not found", retriable=False) from exc
        except SpriteError as exc:
            raise SpritesError(_sanitize(exc), retriable=_is_retriable(exc)) from exc
        return _to_state(sprite)


def _name_for(sandbox_id: str) -> str:
    return f"octo-sbx-{sandbox_id}"


def _require_name(handle: SandboxHandle) -> str:
    if handle.provider != "sprites":
        raise SpritesError(
            f"SpritesProvider received a handle for {handle.provider!r}",
            retriable=False,
        )
    name = handle.payload.get("name")
    if not isinstance(name, str) or not name:
        raise SpritesError("sprites handle missing 'name'", retriable=False)
    return name


def _to_handle(sprite: Sprite) -> SandboxHandle:
    payload: dict[str, str] = {"name": sprite.name}
    if sprite.id:
        payload["id"] = sprite.id
    return SandboxHandle(provider="sprites", payload=payload)


def _to_state(sprite: Sprite) -> SandboxState:
    raw = sprite.status or "cold"
    mapped = _STATUS_MAP.get(raw)
    if mapped is None:
        # Sprites might add intermediate states (e.g. 'starting'). Map to
        # 'warm' as a safe approximation.
        _logger.warning("sprites.unknown_status", status=raw, name=sprite.name)
        mapped = "warm"
    return SandboxState(status=mapped, public_url=sprite.url)


def _sanitize(exc: BaseException) -> str:
    """Strip any token-shaped substring before persisting/logging an error."""
    text = str(exc)
    if "Bearer " in text:
        text = text.split("Bearer ")[0] + "Bearer <redacted>"
    return text[:500]


def _is_retriable(exc: SpriteError) -> bool:
    """5xx-shaped errors get retried by the orchestrator's caller; 4xx don't.
    The SDK doesn't expose status codes uniformly across error types; we
    look at the message as a fallback."""
    text = str(exc).lower()
    return any(s in text for s in ("500", "502", "503", "504", "timeout", "connection"))
