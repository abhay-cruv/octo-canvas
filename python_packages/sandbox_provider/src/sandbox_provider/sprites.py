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
import time
from collections.abc import Mapping
from typing import Any

import httpx
import structlog
from sprites import (
    AuthenticationError as SDKAuthenticationError,
)
from sprites import (
    ExecError,
    NotFoundError,
    Sprite,
    SpriteError,
    SpritesClient,
)
from sprites.exec import run as _sprites_run

from sandbox_provider.interface import (
    CheckpointId,
    ExecResult,
    FsEntry,
    ProviderName,
    ProviderStatus,
    SandboxHandle,
    SandboxState,
    SpritesError,
)

_logger = structlog.get_logger("sandbox_provider.sprites")

# Sprites' status enum maps 1:1 onto our ProviderStatus.
# Map every Sprites lifecycle string we know about — keys lowercased
# at lookup time. Anything an idle/paused/stopped sprite reports
# resolves to `cold`; transient warming/starting strings resolve to
# `warm`. Unknown strings fall through to the warning path below.
_STATUS_MAP: dict[str, ProviderStatus] = {
    "cold": "cold",
    "stopped": "cold",
    "idle": "cold",
    "paused": "cold",
    "hibernated": "cold",
    "warm": "warm",
    "starting": "warm",
    "warming": "warm",
    "ready": "warm",
    "running": "running",
    "active": "running",
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

    # ── Slice 5b additions ────────────────────────────────────────────────

    async def exec_oneshot(
        self,
        handle: SandboxHandle,
        argv: list[str],
        *,
        env: Mapping[str, str],
        cwd: str,
        timeout_s: int = 300,
    ) -> ExecResult:
        sprite_name = _require_name(handle)

        def _run() -> ExecResult:
            sprite = self._client.sprite(sprite_name)
            start = time.monotonic()
            # `sprites.run(...)` is the subprocess-style helper. It sets
            # `_capture_stdout = _capture_stderr = True` so we get the
            # actual command output back. The lower-level `cmd.run()`
            # we used previously does NOT capture by default — that's
            # why every failure showed up as "exit status 1" with empty
            # stderr. Set `check=False` so non-zero exits don't raise;
            # we read the exit code off `CompletedProcess`.
            try:
                proc = _sprites_run(
                    sprite,
                    *argv,
                    capture_output=True,
                    check=False,
                    timeout=float(timeout_s),
                    env=dict(env),
                    cwd=cwd,
                )
            except ExecError as exc:
                # `check=False` should prevent ExecError from rising,
                # but the SDK still raises on transport-level failures
                # that present as ExecError variants. Capture whatever
                # output the SDK already buffered on the exception.
                duration = time.monotonic() - start
                return ExecResult(
                    exit_code=exc.exit_code(),
                    stdout=_to_text(getattr(exc, "stdout", b"")),
                    stderr=_to_text(getattr(exc, "stderr", b"")),
                    duration_s=duration,
                )
            except SpriteError as exc:
                raise SpritesError(_sanitize(exc), retriable=_is_retriable(exc)) from exc
            duration = time.monotonic() - start
            return ExecResult(
                exit_code=int(proc.returncode),
                stdout=_to_text(proc.stdout),
                stderr=_to_text(proc.stderr),
                duration_s=duration,
            )

        # Retry up to 6 times on websocket-handshake timeouts. Sprites'
        # Exec endpoint isn't always Exec-ready the instant the sprite
        # status flips to `warm` — the WS handshake can time out for
        # tens of seconds, especially on the first exec after wake or
        # right after a /work wipe. Backoff: 1+2+4+8+16+32 = 63s of
        # total backoff, plenty for Sprites' runtime to come up.
        backoff_s = 1.0
        last: ExecResult | None = None
        for attempt in range(6):
            try:
                last = await asyncio.to_thread(_run)
            except NotFoundError as exc:
                raise SpritesError(f"sprite {sprite_name!r} not found", retriable=False) from exc
            err_blob = (last.stderr + last.stdout).lower()
            if last.exit_code != 0 and (
                "timed out during opening handshake" in err_blob
                or "websocket error: timeouterror" in err_blob
            ):
                _logger.warning(
                    "sprites.exec.retry",
                    sprite=sprite_name,
                    attempt=attempt + 1,
                    stderr_tail=last.stderr[-200:],
                )
                await asyncio.sleep(backoff_s)
                backoff_s *= 2
                continue
            return last
        # Exhausted retries — return the last result so the caller can
        # surface the actual stderr (the websocket-handshake message)
        # to the user instead of swallowing it as a generic failure.
        assert last is not None
        return last

    async def fs_list(self, handle: SandboxHandle, path: str) -> list[FsEntry]:
        """List directory contents via raw HTTP — rc37 SDK doesn't expose
        `list_files` as a Python method, so we hit `/v1/sprites/{name}/fs/list`
        through the SDK's authenticated client (same pattern as `pause`)."""
        sprite_name = _require_name(handle)

        def _list() -> list[FsEntry]:
            try:
                resp = self._client._client.get(  # type: ignore[reportPrivateUsage]
                    f"{self._client.base_url}/v1/sprites/{sprite_name}/fs/list",
                    params={"path": path, "workingDir": "/"},
                    headers=self._client._headers(),  # type: ignore[reportPrivateUsage]
                    timeout=15.0,
                )
            except httpx.RequestError as exc:
                # ReadTimeout, ConnectError, etc. — wrap as retriable
                # so the reconciler logs a clean SpritesError instead
                # of an uncaught httpx exception that aborts the pass.
                raise SpritesError(f"fs_list transport error: {exc}", retriable=True) from exc
            if resp.status_code == 404:
                raise SpritesError(f"path {path!r} not found", retriable=False)
            if resp.status_code >= 400:
                raise SpritesError(
                    f"fs_list failed: {resp.status_code}", retriable=resp.status_code >= 500
                )
            data: dict[str, Any] = resp.json()
            entries_raw = data.get("entries") or []
            out: list[FsEntry] = []
            for raw in entries_raw:
                if not isinstance(raw, dict):
                    continue
                name = raw.get("name")
                kind_raw = raw.get("type") or raw.get("kind")
                size_raw = raw.get("size", 0)
                if not isinstance(name, str):
                    continue
                kind: str = "dir" if kind_raw == "dir" or kind_raw == "directory" else "file"
                size = int(size_raw) if isinstance(size_raw, (int, float)) else 0
                out.append(FsEntry(name=name, kind=kind, size=size))  # type: ignore[arg-type]
            return out

        return await asyncio.to_thread(_list)

    async def fs_delete(self, handle: SandboxHandle, path: str, *, recursive: bool = False) -> None:
        sprite_name = _require_name(handle)

        def _delete() -> None:
            try:
                resp = self._client._client.delete(  # type: ignore[reportPrivateUsage]
                    f"{self._client.base_url}/v1/sprites/{sprite_name}/fs/delete",
                    params={
                        "path": path,
                        "workingDir": "/",
                        "recursive": str(recursive).lower(),
                    },
                    headers=self._client._headers(),  # type: ignore[reportPrivateUsage]
                    timeout=30.0,
                )
            except httpx.RequestError as exc:
                raise SpritesError(f"fs_delete transport error: {exc}", retriable=True) from exc
            if resp.status_code == 404:
                return  # idempotent
            if resp.status_code >= 400:
                raise SpritesError(
                    f"fs_delete failed: {resp.status_code}", retriable=resp.status_code >= 500
                )

        await asyncio.to_thread(_delete)

    async def snapshot(self, handle: SandboxHandle, *, comment: str) -> CheckpointId:
        """Take a checkpoint via the SDK. `create_checkpoint` returns a
        streaming `CheckpointStream` of `StreamMessage(type, data, error)`
        records — the id may live in `record.data.id`, `record.data["id"]`,
        or only on the final "complete" message depending on SDK version.
        Rather than parse, we drain the stream then call
        `list_checkpoints` and pick the newest entry whose comment matches
        ours. That's robust against any stream-shape change."""
        sprite_name = _require_name(handle)

        def _snap() -> str:
            sprite = self._client.sprite(sprite_name)
            stream = sprite.create_checkpoint(comment)  # type: ignore[no-untyped-call]
            stream_id: str | None = None
            for record in stream:
                # Best-effort: capture id if any message carries one. We
                # fall back to list_checkpoints regardless.
                data = getattr(record, "data", None)
                if isinstance(data, dict):
                    candidate = data.get("id") or data.get("checkpoint_id")
                    if isinstance(candidate, str) and candidate:
                        stream_id = candidate
                elif data is not None:
                    candidate = getattr(data, "id", None)
                    if isinstance(candidate, str) and candidate:
                        stream_id = candidate
            if stream_id:
                return stream_id
            # Fall back: list checkpoints, pick the newest matching our
            # comment. Sprites returns checkpoints with `comment` field
            # set to whatever we passed in.
            checkpoints = sprite.list_checkpoints()
            matching = [c for c in checkpoints if getattr(c, "comment", "") == comment]
            if matching:
                # SDK returns oldest-first by default; sort by create_time.
                matching.sort(key=lambda c: getattr(c, "create_time", None) or 0, reverse=True)
                cid = getattr(matching[0], "id", None)
                if isinstance(cid, str) and cid:
                    return cid
            # Last resort — newest checkpoint period.
            if checkpoints:
                cid = getattr(checkpoints[-1], "id", None)
                if isinstance(cid, str) and cid:
                    return cid
            raise SpritesError("create_checkpoint returned no id", retriable=True)

        # Retry up to 3 times on transient Sprites errors (503s, network
        # blips, etc.) — checkpoints are best-effort during slice 5b
        # but slice 6+ may use `clean_checkpoint_id` for fast resets,
        # and a missing field there will silently disable that path.
        # Backoff: 2s, 4s.
        backoff_s = 2.0
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                ckpt = await asyncio.to_thread(_snap)
                if attempt > 0:
                    _logger.info(
                        "sprites.snapshot.retry_succeeded",
                        sprite=sprite_name,
                        attempt=attempt + 1,
                    )
                return CheckpointId(ckpt)
            except NotFoundError as exc:
                # Definitive — sprite is gone. No point retrying.
                raise SpritesError(f"sprite {sprite_name!r} not found", retriable=False) from exc
            except SpriteError as exc:
                last_err = exc
                msg = _sanitize(exc).lower()
                # Only retry on shapes we know are transient. 503,
                # 502, gateway timeouts, network errors all qualify;
                # 4xx auth/validation errors don't.
                transient = any(
                    s in msg
                    for s in ("503", "502", "504", "timeout", "connection", "service unavailable")
                )
                if not transient or attempt == 2:
                    raise SpritesError(_sanitize(exc), retriable=_is_retriable(exc)) from exc
                _logger.warning(
                    "sprites.snapshot.retry",
                    sprite=sprite_name,
                    attempt=attempt + 1,
                    error=msg[:200],
                )
                await asyncio.sleep(backoff_s)
                backoff_s *= 2
        # Unreachable — the loop either returns or raises — but make
        # the type checker happy.
        raise SpritesError(f"snapshot exhausted retries: {last_err}", retriable=True)

    async def restore(self, handle: SandboxHandle, checkpoint_id: CheckpointId) -> SandboxState:
        sprite_name = _require_name(handle)

        def _restore() -> Sprite:
            sprite = self._client.sprite(sprite_name)
            stream = sprite.restore_checkpoint(str(checkpoint_id))  # type: ignore[no-untyped-call]
            for _ in stream:  # drain progress
                pass
            return self._client.get_sprite(sprite_name)

        try:
            sprite = await asyncio.to_thread(_restore)
        except NotFoundError as exc:
            raise SpritesError(
                f"checkpoint {checkpoint_id!r} not found on sprite {sprite_name!r}",
                retriable=False,
            ) from exc
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


def _to_text(buf: object) -> str:
    """Coerce SDK byte-or-str output to text. The Exec result fields are
    bytes; the older string-shaped path is kept for forward-compat with
    SDK versions that swap to `str`."""
    if isinstance(buf, bytes):
        try:
            return buf.decode("utf-8", errors="replace")
        except Exception:
            return repr(buf)
    if isinstance(buf, str):
        return buf
    return str(buf or "")


def _to_state(sprite: Sprite) -> SandboxState:
    raw = (sprite.status or "cold").lower()
    mapped = _STATUS_MAP.get(raw)
    if mapped is None:
        # Sprites might add a state we haven't taught the map. Default
        # to `cold` (safer than `warm` — the previous default kept
        # actually-cold sprites stuck reading as warm in the dashboard
        # whenever Sprites rebranded a status string). Log the raw
        # value loudly so we can extend the map.
        _logger.warning(
            "sprites.unknown_status",
            status=sprite.status,
            name=sprite.name,
            mapped_to="cold",
        )
        mapped = "cold"
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
