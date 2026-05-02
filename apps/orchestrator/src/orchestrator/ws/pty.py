"""PTY WebSocket broker (slice 6).

Dials the upstream sandbox exec channel via `provider.pty_dial_info` and
pumps bytes both ways. Per-terminal session-id is cached in Redis so a
browser refresh can re-attach to the same upstream session and Sprites
replays scrollback.

URL: `/ws/web/sandboxes/{sandbox_id}/pty/{terminal_id}`
Auth: session cookie (same as REST).

Wire shape:
- Server → web: raw binary frames (xterm.js stdin payload), plus JSON
  `PtySessionInfo` and `PtyExit` control frames.
- Web → server: raw binary frames (stdin), plus JSON `ResizePty` and
  `RequestClosePty` control frames.

Close codes:
- 4001 — auth missing/expired
- 4003 — user does not own this sandbox
- 4004 — sandbox not found / not provisioned
- 4502 — upstream dial failed
- 1000 — clean close
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
import websockets
from beanie import PydanticObjectId
from db.models import Sandbox, Session, User
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sandbox_provider import PtyDialInfo, SandboxHandle, SandboxProvider, SpritesError
from shared_models.wire_protocol import (
    PtyExit,
    PtySessionInfo,
    RequestClosePty,
    ResizePty,
    WebToPtyAdapter,
)

from ..middleware.auth import SESSION_COOKIE_NAME

if TYPE_CHECKING:
    from redis.asyncio import Redis

_logger = structlog.get_logger("ws.pty")

router = APIRouter()


_PTY_REDIS_TTL_S = 24 * 60 * 60  # 24h — matches Sprites' own scrollback retention


def _redis_key(sandbox_id: str, terminal_id: str) -> str:
    return f"pty:{sandbox_id}:{terminal_id}"


async def _resolve_user(websocket: WebSocket) -> User | None:
    session_id = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    session = await Session.find_one(Session.session_id == session_id)
    if session is None:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        return None
    return await User.get(session.user_id)


async def _load_owned(sandbox_id: PydanticObjectId, user: User) -> Sandbox | None:
    doc = await Sandbox.get(sandbox_id)
    if doc is None or doc.user_id != user.id:
        return None
    if not doc.provider_handle:
        return None
    return doc


def _provider(websocket: WebSocket) -> SandboxProvider:
    p = getattr(websocket.app.state, "sandbox_provider", None)
    if p is None:
        raise RuntimeError("sandbox_provider not initialized on app.state")
    return p  # type: ignore[no-any-return]


def _redis(websocket: WebSocket) -> Redis | None:
    return getattr(websocket.app.state, "redis_handle", None)


@router.websocket("/ws/web/sandboxes/{sandbox_id}/pty/{terminal_id}")
async def pty_stream(websocket: WebSocket, sandbox_id: str, terminal_id: str) -> None:
    # Per the WS protocol, application-level close codes (4xxx) only have
    # meaning AFTER accept(). Mirror slice 5a — accept first, then validate.
    await websocket.accept()

    user = await _resolve_user(websocket)
    if user is None:
        await websocket.close(code=4001, reason="unauthenticated")
        return
    try:
        oid = PydanticObjectId(sandbox_id)
    except (ValueError, TypeError):
        await websocket.close(code=4003, reason="forbidden")
        return
    doc = await _load_owned(oid, user)
    if doc is None:
        await websocket.close(code=4003, reason="forbidden")
        return

    handle = SandboxHandle(provider=doc.provider_name, payload=dict(doc.provider_handle or {}))
    redis = _redis(websocket)
    attach_session_id: str | None = None
    if redis is not None:
        cached = await redis.get(_redis_key(sandbox_id, terminal_id))
        if isinstance(cached, str) and cached:
            attach_session_id = cached
        elif isinstance(cached, bytes):
            attach_session_id = cached.decode("utf-8")

    provider = _provider(websocket)
    try:
        dial = await provider.pty_dial_info(handle, attach_session_id=attach_session_id)
    except SpritesError as exc:
        _logger.warning("pty.dial_info_failed", error=str(exc))
        await websocket.close(code=4502, reason="upstream_dial_failed")
        return

    # Connect to the upstream Sprites Exec WSS with retry-on-transient.
    # Two flake modes from observation:
    # 1. Handshake timeout — sprite is still spinning up after `warm`.
    #     Mitigation: retry with 1+2+4+8+16+32s backoff (mirrors
    #     `exec_oneshot`'s pattern).
    # 2. HTTP 404 on `/exec/{session_id}` — the cached `attach_session_id`
    #     points at a session Sprites already reaped (TTL/idle/restart).
    #     Mitigation: drop the attach hint, clear the Redis entry, dial
    #     a fresh session.
    upstream, attach_session_id, dial = await _connect_with_retry(
        websocket=websocket,
        provider=provider,
        handle=handle,
        sandbox_id=sandbox_id,
        terminal_id=terminal_id,
        attach_session_id=attach_session_id,
        redis=redis,
        initial_dial=dial,
    )
    if upstream is None:
        return

    # `attach_session_id` may have been cleared by `_connect_with_retry` on
    # a 404 fallback — recompute reattached from the post-retry value.
    reattached = attach_session_id is not None

    async def _pump_upstream_to_client() -> None:
        """Forward bytes verbatim; intercept JSON control frames so we can
        cache session_id and surface PtySessionInfo / PtyExit on our wire."""
        try:
            async for raw in upstream:
                if isinstance(raw, bytes):
                    await websocket.send_bytes(raw)
                    continue
                # Text frame — Sprites control message.
                try:
                    msg: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg_type = msg.get("type")
                if msg_type == "session_info":
                    sid = msg.get("session_id")
                    if isinstance(sid, str) and sid and redis is not None:
                        await redis.set(
                            _redis_key(sandbox_id, terminal_id),
                            sid,
                            ex=_PTY_REDIS_TTL_S,
                        )
                    await websocket.send_text(
                        PtySessionInfo(
                            terminal_id=terminal_id,
                            sprites_session_id=str(sid or ""),
                            cols=int(msg.get("cols", 80) or 80),
                            rows=int(msg.get("rows", 24) or 24),
                            reattached=reattached,
                        ).model_dump_json()
                    )
                elif msg_type == "exit":
                    exit_code = int(msg.get("exit_code", 0) or 0)
                    await websocket.send_text(
                        PtyExit(terminal_id=terminal_id, exit_code=exit_code).model_dump_json()
                    )
                    if redis is not None:
                        await redis.delete(_redis_key(sandbox_id, terminal_id))
                # Other control types (port_opened, port_closed) are ignored
                # in slice 6.
        except websockets.exceptions.ConnectionClosed:
            return

    # Latest known dimensions — the keepalive task re-emits this resize
    # frame every 25s so neither the upstream Sprites WSS nor the FE-facing
    # WSS go idle long enough for an intermediate proxy / Sprites' own
    # idle reaper to drop the connection. xterm/Sprites treat a no-op
    # resize as benign — no visible output.
    last_dims: dict[str, int] = {"cols": 80, "rows": 24}

    async def _pump_client_to_upstream_v2() -> None:
        # Same body as `_pump_client_to_upstream` but also tracks the
        # latest dimensions so the keepalive task can mirror them.
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                data_b = message.get("bytes")
                if isinstance(data_b, (bytes, bytearray)):
                    await upstream.send(bytes(data_b))
                    continue
                data_t = message.get("text")
                if isinstance(data_t, str):
                    parsed = _parse_client_control(data_t)
                    if parsed is None:
                        continue
                    if parsed.type == "pty.resize":
                        last_dims["cols"] = parsed.cols
                        last_dims["rows"] = parsed.rows
                        await upstream.send(
                            json.dumps(
                                {"type": "resize", "cols": parsed.cols, "rows": parsed.rows}
                            )
                        )
                    elif parsed.type == "pty.close":
                        # User explicitly closed the terminal tab. Drop
                        # the Redis reattach cache so the next open
                        # creates a FRESH Sprites session (with the
                        # current `pty_dial_info` cmd shape — important
                        # when we change the wrapper script, e.g. the
                        # `cd /work` cwd fix). Without this, every
                        # reopen reattaches to the old session forever.
                        if redis is not None:
                            try:
                                await redis.delete(_redis_key(sandbox_id, terminal_id))
                            except Exception:
                                pass
                        return
        except WebSocketDisconnect:
            return

    async def _keepalive() -> None:
        """Keep BOTH ends of the PTY pipe warm.

        - Upstream (orchestrator → Sprites): re-send the current dims as a
          resize every 15s. Some Sprites runtimes only count stdin/stdout
          traffic toward the idle timer, so a resize alone may not be
          enough — we therefore also send a single NUL stdin byte, which
          bash readline silently swallows (no visible output).
        - Downstream (orchestrator → FE): browser tabs and intermediate
          proxies sometimes drop idle WS connections regardless of WS
          ping/pong. A tiny binary frame containing a single NUL byte
          counts as activity from xterm's POV (xterm.write skips embedded
          NULs cleanly) and keeps the connection warm end-to-end.

        Errors on either side terminate the keepalive task; the broker's
        `asyncio.wait` notices and tears the whole session down so the
        FE's auto-reconnect can take over.
        """
        try:
            while True:
                await asyncio.sleep(15)
                try:
                    # Upstream resize ping (control frame).
                    await upstream.send(
                        json.dumps(
                            {
                                "type": "resize",
                                "cols": last_dims["cols"],
                                "rows": last_dims["rows"],
                            }
                        )
                    )
                    # Upstream stdin no-op — readline drops NUL silently.
                    # The Sprites Exec WSS treats this as activity, which
                    # resets the inactivity reaper.
                    await upstream.send(b"\x00")
                except (websockets.exceptions.ConnectionClosed, RuntimeError):
                    return
                try:
                    # Downstream — keep the FE-side WS warm via a 1-byte
                    # NUL. xterm.write silently skips NULs.
                    await websocket.send_bytes(b"\x00")
                except (WebSocketDisconnect, RuntimeError):
                    return
                except Exception:
                    # FE side hung up; let the wait()-FIRST_COMPLETED
                    # in the caller notice via the down_task instead.
                    return
        except asyncio.CancelledError:
            raise

    up_task = asyncio.create_task(_pump_upstream_to_client(), name=f"pty-up-{terminal_id}")
    down_task = asyncio.create_task(_pump_client_to_upstream_v2(), name=f"pty-down-{terminal_id}")
    keepalive_task = asyncio.create_task(_keepalive(), name=f"pty-ka-{terminal_id}")
    try:
        _done, pending = await asyncio.wait(
            {up_task, down_task, keepalive_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
            with suppress(asyncio.CancelledError):
                await t
    finally:
        with suppress(Exception):
            await upstream.close()
        with suppress(Exception):
            await websocket.close()


def _parse_client_control(text: str) -> ResizePty | RequestClosePty | None:
    try:
        return WebToPtyAdapter.validate_json(text)  # type: ignore[return-value]
    except ValidationError:
        return None


_CONNECT_BACKOFFS_S: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)


async def _connect_with_retry(
    *,
    websocket: WebSocket,
    provider: SandboxProvider,
    handle: SandboxHandle,
    sandbox_id: str,
    terminal_id: str,
    attach_session_id: str | None,
    redis: Redis | None,
    initial_dial: PtyDialInfo,
):  # type: ignore[no-untyped-def]
    """Open the upstream Sprites Exec WSS, retrying on transient failures.

    Returns `(upstream, attach_session_id, dial)`. On terminal failure the
    web socket is closed with 4502 and `upstream` is `None`.

    Two flake modes handled:
    - Handshake timeout (sprite warming) → backoff and retry.
    - HTTP 404 on attach (Sprites reaped the cached session) → drop the
      `attach_session_id`, clear the stale Redis entry, redial fresh.
    """
    dial = initial_dial
    last_err: BaseException | None = None
    for attempt, delay in enumerate(_CONNECT_BACKOFFS_S):
        try:
            ws = await websockets.connect(
                dial.url, additional_headers=dial.headers, max_size=2**24
            )
            return ws, attach_session_id, dial
        except (OSError, websockets.exceptions.WebSocketException) as exc:
            last_err = exc
            err_str = str(exc).lower()

            # 404 on attach → cached session is gone. Clear it and retry
            # immediately with a fresh session URL.
            if (
                attach_session_id is not None
                and ("http 404" in err_str or "rejected websocket connection: http 404" in err_str)
            ):
                _logger.info(
                    "pty.attach_session_stale_falling_back",
                    sandbox_id=sandbox_id,
                    terminal_id=terminal_id,
                    stale_session_id=attach_session_id,
                )
                if redis is not None:
                    try:
                        await redis.delete(_redis_key(sandbox_id, terminal_id))
                    except Exception:
                        pass
                attach_session_id = None
                try:
                    dial = await provider.pty_dial_info(handle, attach_session_id=None)
                except SpritesError as inner:
                    last_err = inner
                    break
                continue  # don't sleep — try the fresh URL right away

            transient = (
                "timed out during opening handshake" in err_str
                or "timeout" in err_str
                or "connection refused" in err_str
                or "503" in err_str
                or "502" in err_str
                or "504" in err_str
            )
            if not transient or attempt == len(_CONNECT_BACKOFFS_S) - 1:
                break
            _logger.warning(
                "pty.upstream_connect_retry",
                attempt=attempt + 1,
                error=str(exc)[:200],
            )
            await asyncio.sleep(delay)

    _logger.warning(
        "pty.upstream_connect_failed",
        error=str(last_err) if last_err else "unknown",
    )
    try:
        await websocket.close(code=4502, reason="upstream_dial_failed")
    except Exception:
        pass
    return None, attach_session_id, dial
