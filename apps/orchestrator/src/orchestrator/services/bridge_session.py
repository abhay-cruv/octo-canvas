"""Slice 8 (post-pivot) — orchestrator-driven bridge transport.

When `BRIDGE_TRANSPORT=service_proxy`, the bridge runs as a Sprites
Service listening on a TCP port inside the sprite. The orchestrator
dials in via `WSS /v1/sprites/{name}/proxy` (Sprites' raw TCP relay).
This module owns that side of the connection: per-sandbox connections,
a frame I/O loop matching `bridge.tcp_server`'s length-prefixed JSON
framing, and an `ensure_started` helper that does the
`upsert_service` + `start_service` dance.

The legacy `BridgeOwner` (Redis-coordinated dial-back transport) is
left intact in `bridge_owner.py`; `app.py` picks one or the other based
on the transport flag. Both expose `.send(sandbox_id, frame)` →
`bool` so the route + chat_runner layers don't need to know which is
wired up.

For v1 this fleet is single-instance (no Redis cross-instance routing).
The service-proxy model already gives Sprites the singleton process; the
only multi-instance question is "which orchestrator instance holds the
proxy WS at any moment", which is solvable later via session affinity.
"""

from __future__ import annotations

import asyncio
import json
import struct
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
import websockets
from beanie import PydanticObjectId
from db.models import Chat, Sandbox
from pydantic import ValidationError
from sandbox_provider import (
    SandboxHandle,
    SandboxProvider,
    ServiceLogLine,
    SpritesError,
)
from shared_models.wire_protocol import (
    BridgeToOrchestratorAdapter,
    Goodbye,
    Hello,
    Pong,
)
from websockets.exceptions import WebSocketException

_logger = structlog.get_logger("bridge_session")

# Service name we register with Sprites. One bridge service per sprite.
BRIDGE_SERVICE_NAME = "bridge"

# Same cap as `bridge.tcp_server._MAX_FRAME_BYTES`; symmetric framing.
_MAX_FRAME_BYTES = 16 * 1024 * 1024

# Backoff bounds for proxy-WS reconnect.
_RECONNECT_INITIAL_S = 1.0
_RECONNECT_MAX_S = 30.0


# Hooks the fleet calls on each event-class inbound frame. Mirrors what
# `ws/bridge.py:_read_inbound` does, but as a plain callable so it stays
# testable. `frame_dict` is the parsed JSON dict; the parsed Pydantic
# model is also passed for type-safe handlers.
EventHandler = Callable[
    [PydanticObjectId, dict[str, Any], Any], Awaitable[None]
]


def _handle_of(sandbox: Sandbox) -> SandboxHandle:
    """Reconstruct the provider handle from the persisted Sandbox doc.
    Mirrors the helper in `reconciliation.py` / `sandbox_bridge.py` —
    keeping a local copy so this module stays self-contained."""
    return SandboxHandle(provider=sandbox.provider_name, payload=sandbox.provider_handle)


async def _read_frame(reader: asyncio.StreamReader) -> bytes | None:
    try:
        header = await reader.readexactly(4)
    except asyncio.IncompleteReadError:
        return None
    (length,) = struct.unpack(">I", header)
    if length == 0:
        return b""
    if length > _MAX_FRAME_BYTES:
        raise ValueError(f"frame too large: {length} bytes")
    try:
        return await reader.readexactly(length)
    except asyncio.IncompleteReadError as exc:
        raise ValueError(
            f"truncated frame: expected {length} bytes, got {len(exc.partial)}"
        ) from exc


def _pack_frame(payload: bytes) -> bytes:
    if len(payload) > _MAX_FRAME_BYTES:
        raise ValueError(f"frame too large: {len(payload)} bytes")
    return struct.pack(">I", len(payload)) + payload


class BridgeSession:
    """One proxy-WS connection to a single sandbox's bridge service.

    Lifecycle:
      - `ensure_connected()` opens the WS + sends the JSON init frame
        (`{host, port}`), then starts the read loop.
      - `send(frame)` enqueues a frame for the writer.
      - On WS error the session reconnects with backoff. The writer
        queue survives across reconnects so transient drops don't lose
        frames.
      - `close()` cancels both loops and closes the WS.
    """

    def __init__(
        self,
        *,
        sandbox: Sandbox,
        provider: SandboxProvider,
        listen_port: int,
        on_event: EventHandler,
    ) -> None:
        if sandbox.id is None:
            raise ValueError("BridgeSession requires a saved Sandbox (id != None)")
        self._sandbox_id: PydanticObjectId = sandbox.id
        self._sandbox = sandbox
        self._provider = provider
        self._listen_port = listen_port
        self._on_event = on_event
        # Bytes of length-prefixed framed JSON, ready to dump on the
        # WS as binary messages. Outbound queue survives reconnects so
        # a transient WS bounce doesn't drop in-flight frames.
        self._send_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._stopped = asyncio.Event()
        self._connected_evt = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def sandbox_id(self) -> str:
        return str(self._sandbox_id)

    def is_connected(self) -> bool:
        return self._connected_evt.is_set()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(
            self._supervisor(), name=f"bridge-session-{self._sandbox_id}"
        )

    async def close(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def send(self, frame: dict[str, Any]) -> bool:
        """Best-effort enqueue. Returns True if the frame was queued —
        the supervisor delivers when the WS is up."""
        if self._stopped.is_set():
            return False
        frame.setdefault("frame_id", str(uuid.uuid4()))
        try:
            payload = json.dumps(frame, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            _logger.warning(
                "bridge_session.encode_failed",
                sandbox_id=self.sandbox_id,
                error=str(exc)[:200],
            )
            return False
        await self._send_queue.put(_pack_frame(payload))
        return True

    async def _supervisor(self) -> None:
        backoff = _RECONNECT_INITIAL_S
        while not self._stopped.is_set():
            try:
                await self._run_one_connection()
                # Clean exit (server closed) — back off briefly then retry.
                backoff = _RECONNECT_INITIAL_S
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "bridge_session.connection_error",
                    sandbox_id=self.sandbox_id,
                    error=str(exc)[:200],
                    backoff_s=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX_S)

    async def _run_one_connection(self) -> None:
        # Refresh the sandbox doc so provider_handle / provider_name are
        # current (e.g. after a destroy+recreate).
        fresh = await Sandbox.get(self._sandbox_id)
        if fresh is None:
            self._stopped.set()
            return
        self._sandbox = fresh

        info = await self._provider.proxy_dial_info(
            _handle_of(self._sandbox),
            host="localhost",
            port=self._listen_port,
        )
        _logger.info(
            "bridge_session.dialing",
            sandbox_id=self.sandbox_id,
            url=info.url,
        )
        try:
            ws = await websockets.connect(
                info.url,
                additional_headers=info.headers,
                max_size=2**24,
                # The proxy is a raw TCP relay — Sprites doesn't ping
                # at the WS layer, so disable WS-level pings; the
                # bridge-level Pong frames serve as our heartbeat.
                ping_interval=None,
            )
        except (OSError, WebSocketException) as exc:
            raise RuntimeError(f"proxy dial failed: {exc}") from exc

        # Send JSON init frame: {"host", "port"}. Sprites responds with
        # {"status":"connected", ...} and then the channel becomes raw.
        try:
            await ws.send(
                json.dumps({"host": info.init_host, "port": info.init_port})
            )
            ack_raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            if isinstance(ack_raw, bytes):
                ack_raw = ack_raw.decode("utf-8", errors="replace")
            try:
                ack = json.loads(ack_raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"proxy ack not JSON: {ack_raw[:200]}"
                ) from exc
            if ack.get("status") != "connected":
                raise RuntimeError(f"proxy ack rejected: {ack}")
        except (TimeoutError, WebSocketException, OSError) as exc:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(f"proxy init handshake failed: {exc}") from exc

        _logger.info("bridge_session.connected", sandbox_id=self.sandbox_id)
        self._connected_evt.set()

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._reader(ws))
                tg.create_task(self._writer(ws))
        except* WebSocketException:
            pass
        finally:
            self._connected_evt.clear()
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
            _logger.info("bridge_session.disconnected", sandbox_id=self.sandbox_id)

    async def _reader(self, ws: Any) -> None:
        # Reassemble a stream of length-prefixed frames from binary WS
        # messages. The Sprites proxy is a raw byte relay so a single
        # WS message may carry multiple frames OR a partial frame.
        buf = bytearray()
        async for msg in ws:
            if isinstance(msg, str):
                # Should not happen on a raw TCP relay, but be defensive.
                continue
            buf.extend(msg)
            while True:
                if len(buf) < 4:
                    break
                length = struct.unpack(">I", bytes(buf[:4]))[0]
                if length > _MAX_FRAME_BYTES:
                    _logger.warning(
                        "bridge_session.oversize_frame",
                        sandbox_id=self.sandbox_id,
                        length=length,
                    )
                    buf.clear()
                    break
                if len(buf) < 4 + length:
                    break
                payload = bytes(buf[4 : 4 + length])
                del buf[: 4 + length]
                await self._dispatch_inbound(payload)

    async def _writer(self, ws: Any) -> None:
        while True:
            framed = await self._send_queue.get()
            try:
                await ws.send(framed)
            except WebSocketException:
                # Re-queue at the head so the next connection delivers it.
                # asyncio.Queue has no put-front; we use a sentinel deque
                # via task_done semantics — easiest: push back to the tail.
                # In-flight order is "best effort"; the bridge frame_id
                # dedup catches accidental dupes.
                await self._send_queue.put(framed)
                raise

    async def _dispatch_inbound(self, payload: bytes) -> None:
        try:
            frame = BridgeToOrchestratorAdapter.validate_json(payload)
        except ValidationError as exc:
            # Log the actual raw payload too — without it we're guessing
            # which field is missing/wrong. Truncate to 600 bytes so a
            # giant frame doesn't blow out the log.
            _logger.warning(
                "bridge_session.bad_inbound_frame",
                sandbox_id=self.sandbox_id,
                error=str(exc)[:500],
                raw_payload=payload[:600].decode("utf-8", errors="replace"),
            )
            return
        # Connection-class frames: log + ignore in v1. The service-proxy
        # model doesn't need Hello/ChatState replay because we control
        # session lifecycle directly.
        if isinstance(frame, (Hello, Goodbye, Pong)):
            return
        chat_id_str = getattr(frame, "chat_id", None)
        if not isinstance(chat_id_str, str):
            return
        try:
            chat_id = PydanticObjectId(chat_id_str)
        except Exception:  # noqa: BLE001
            return
        # Hand off to the configured event handler (typically appends
        # to the event store + publishes to the per-chat fan-out).
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return
        try:
            await self._on_event(chat_id, data, frame)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "bridge_session.on_event_failed",
                sandbox_id=self.sandbox_id,
                chat_id=chat_id_str,
                error=str(exc)[:200],
            )


class BridgeSessionFleet:
    """Lookup of `sandbox_id → BridgeSession`. Mirrors `BridgeOwner.send`
    so route handlers don't care which transport is wired."""

    def __init__(
        self,
        *,
        provider: SandboxProvider,
        listen_port: int,
        on_event: EventHandler,
        bridge_env_for: Callable[[Sandbox], dict[str, str]],
    ) -> None:
        self._provider = provider
        self._listen_port = listen_port
        self._on_event = on_event
        # Closure that returns the env dict to PUT on the service. We
        # take a callable rather than a static dict because the env
        # depends on the sandbox (token, sandbox_id, etc.).
        self._bridge_env_for = bridge_env_for
        self._sessions: dict[str, BridgeSession] = {}
        # Cache the env we launched each sandbox's bridge with so
        # subsequent ensure_started calls can no-op (don't mint a new
        # token, don't rewrite Sandbox.bridge_token_hash, don't rerun
        # the launch script). Cleared by `restart()` which forces a
        # fresh token + relaunch.
        self._cached_env: dict[str, dict[str, str]] = {}
        self._lock = asyncio.Lock()
        # Test hook — also used by the live-log WS endpoint.
        self._log_taps: dict[str, list[asyncio.Queue[ServiceLogLine | None]]] = {}
        self._log_tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def instance_id(self) -> str:
        return "service-proxy"

    async def start(self) -> None:
        # Symmetry with BridgeOwner.start — fleet has nothing to bring
        # up at process start; sessions are created lazily.
        return

    async def stop(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._cached_env.clear()
            log_tasks = list(self._log_tasks.values())
            self._log_tasks.clear()
        for session in sessions:
            await session.close()
        for task in log_tasks:
            task.cancel()
        for task in log_tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def send(self, sandbox_id: str, frame: dict[str, Any]) -> bool:
        """Best-effort delivery. If no session exists yet (first message
        for this sandbox), lazily build one + wait briefly for it to
        connect to the bridge daemon. The frame goes into the session's
        outbound queue so a still-connecting session doesn't drop it."""
        session = self._sessions.get(sandbox_id)
        if session is None:
            session = await self._ensure_session(sandbox_id)
            if session is None:
                return False
        # Wait up to ~2s for the proxy WS to be open. The frame goes into
        # the queue regardless — the writer drains it once connected.
        await session.send(frame)
        for _ in range(20):
            if session.is_connected():
                return True
            await asyncio.sleep(0.1)
        return True  # queued, will deliver on next connect

    async def _ensure_session(self, sandbox_id: str) -> "BridgeSession | None":
        async with self._lock:
            session = self._sessions.get(sandbox_id)
            if session is not None:
                return session
            try:
                oid = PydanticObjectId(sandbox_id)
            except Exception:  # noqa: BLE001
                return None
            sandbox = await Sandbox.get(oid)
            if sandbox is None:
                return None
            session = BridgeSession(
                sandbox=sandbox,
                provider=self._provider,
                listen_port=self._listen_port,
                on_event=self._on_event,
            )
            self._sessions[sandbox_id] = session
            await session.start()
            return session

    async def ensure_started(self, sandbox: Sandbox) -> None:
        """Idempotent: ensure a Sprites Service named `bridge` is
        declared + running, with a `BridgeSession` dialing in via
        `/proxy` WSS, AND `Sandbox.bridge_token_hash` matches the
        token actually in the service env.

        Strategy:
          1. Read existing service env (single source of truth for the
             running bridge's BRIDGE_TOKEN). Adopt if present.
          2. If no service def yet → mint fresh env.
          3. Persist hash(BRIDGE_TOKEN) to mongo so the Anthropic
             proxy's bearer validation matches.
          4. Upsert service def + start (idempotent — Sprites no-ops
             on already-running). For sprites without Services API,
             fall back to exec_oneshot nohup launch.
          5. Re-read service env afterwards and reconcile mongo to it
             (Sprites' PUT-while-running quirks: env-on-disk may not
             match env-on-process; we trust whatever ended up running).
          6. Ensure a `BridgeSession` exists.

        This shape keeps mongo + service env in sync across:
          - first provision (no service yet → mint, persist, start)
          - orchestrator reload (cache cold → adopt running env)
          - reset (service untouched → adopt)
          - cold pause + resume (service def survives → adopt env from def)
          - explicit `restart()` (calls into here after stop+drop cache)
        """
        if sandbox.id is None:
            return
        sandbox_id = str(sandbox.id)

        # 1+2. Resolve env: cached (warm) → adopted from service def → minted.
        env = self._cached_env.get(sandbox_id)
        if env is None:
            adopted = await self._read_service_env(sandbox)
            env = adopted if adopted is not None else self._bridge_env_for(sandbox)

        # 3. Persist hash so proxy bearer validation works on the next
        #    Claude API call. Always — cheap mongo write, idempotent.
        await self._persist_token_hash(sandbox, env)
        self._cached_env[sandbox_id] = env

        # 4. Bring the service up. Idempotent — start on running is no-op.
        services_path_failed = False
        try:
            await self._provider.upsert_service(
                _handle_of(sandbox),
                name=BRIDGE_SERVICE_NAME,
                cmd="/opt/bridge/.venv/bin/python",
                args=["-m", "bridge.main"],
                env=env,
                cwd="/work",
                http_port=self._listen_port,
            )
            await self._provider.start_service(
                _handle_of(sandbox), name=BRIDGE_SERVICE_NAME
            )
            _logger.info(
                "bridge_session_fleet.service_ensured",
                sandbox_id=sandbox_id,
            )
        except SpritesError as exc:
            _logger.warning(
                "bridge_session_fleet.services_api_unavailable",
                sandbox_id=sandbox_id, error=str(exc)[:200],
                fallback="exec_launch",
            )
            services_path_failed = True

        if services_path_failed:
            # Fallback for sprites with no Services API.
            try:
                await self._exec_launch(sandbox, env, force=False)
            except SpritesError as exc:
                _logger.warning(
                    "bridge_session_fleet.exec_launch_failed",
                    sandbox_id=sandbox_id, error=str(exc)[:200],
                )
                raise

        # 5. Reconcile: re-read service env to confirm token hash on
        #    mongo matches the running service. Catches Sprites
        #    PUT-while-running quirks where the def env we just sent
        #    didn't actually replace the running process's env.
        if not services_path_failed:
            actual = await self._read_service_env(sandbox)
            if actual is not None:
                self._cached_env[sandbox_id] = actual
                await self._persist_token_hash(sandbox, actual)

        # 6. BridgeSession dials /proxy + sends queued frames.
        async with self._lock:
            session = self._sessions.get(sandbox_id)
            if session is None:
                session = BridgeSession(
                    sandbox=sandbox,
                    provider=self._provider,
                    listen_port=self._listen_port,
                    on_event=self._on_event,
                )
                self._sessions[sandbox_id] = session
                await session.start()

    async def _persist_token_hash(
        self, sandbox: Sandbox, env: dict[str, str]
    ) -> None:
        """Write `Sandbox.bridge_token_hash = sha256(env BRIDGE_TOKEN)` if
        it doesn't already match. Idempotent + cheap."""
        if sandbox.id is None:
            return
        bridge_token = env.get("BRIDGE_TOKEN") or env.get("ANTHROPIC_AUTH_TOKEN")
        if not bridge_token:
            return
        from orchestrator.services.sandbox_manager import _hash_bridge_token

        token_hash = _hash_bridge_token(bridge_token)
        if sandbox.bridge_token_hash == token_hash:
            return
        await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
            {"$set": {"bridge_token_hash": token_hash}}
        )
        sandbox.bridge_token_hash = token_hash
        _logger.info(
            "bridge_session_fleet.token_hash_synced",
            sandbox_id=str(sandbox.id),
        )

    async def _read_service_env(self, sandbox: Sandbox) -> dict[str, str] | None:
        """Read the bridge service's `env` from Sprites' service def
        (works regardless of running/stopped — it's a GET on the def).
        Returns None if the service isn't declared OR the provider isn't
        Sprites OR any HTTP error.

        Used to adopt the existing token on:
          - orchestrator restart (preserves token across uvicorn reload)
          - reset (service def survives /work wipe)
          - cold pause + resume (service def stays in the def store)
        """
        from sandbox_provider import SpritesProvider

        provider = self._provider
        if not isinstance(provider, SpritesProvider):
            return None
        sprite_name = f"octo-sbx-{sandbox.id}"
        try:
            import httpx
            client = provider._client._client  # type: ignore[reportPrivateUsage,attr-defined]
            base = provider._client.base_url  # type: ignore[reportPrivateUsage,attr-defined]
            headers = provider._client._headers()  # type: ignore[reportPrivateUsage,attr-defined]
            resp = await asyncio.to_thread(
                client.get,
                f"{base}/v1/sprites/{sprite_name}/services/{BRIDGE_SERVICE_NAME}",
                headers=headers,
                timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            env = data.get("env")
            if not isinstance(env, dict):
                return None
            return {str(k): str(v) for k, v in env.items()}
        except Exception:  # noqa: BLE001
            return None

    async def _exec_launch(
        self, sandbox: Sandbox, env: dict[str, str], *, force: bool = False
    ) -> None:
        """Ensure a bridge process is running.

        - `force=False` (default for `ensure_started`): no-op if a
          process is already alive on the PID file. Critical: every
          user-message path calls `ensure_started`, so if this killed +
          relaunched on every call, the bridge would never stay alive
          long enough to actually answer.
        - `force=True` (used by `restart`): kill the existing PID and
          start fresh.

        Same nohup + PID-file pattern as the legacy `_ensure_bridge_running`,
        no Services API dependency.
        """
        force_arg = "1" if force else "0"
        # Write the launch logic to a tempfile and exec that, so the
        # running bash process's argv contains only the path (not the
        # full script body containing "bridge.main"). This lets us
        # `pkill -f bridge\.main` without killing ourselves.
        launch_script = f"""set -euo pipefail
FORCE={force_arg}
sudo -n install -d -m 0755 -o $(id -un) -g $(id -un) /var/log/octo

# Idempotent: bridge already running and listening → no-op.
if [ "$FORCE" = "0" ] && ss -Hltn 2>/dev/null | awk '{{print $4}}' | grep -q ':9300$'; then
    echo "bridge already listening on 9300"
    exit 0
fi

# Kill any existing bridge.main process. The bash running THIS script
# is /bin/bash with argv containing the script body — we filter to
# python COMM via /proc to avoid suiciding.
for P in $(pgrep -f 'bridge\\.main' 2>/dev/null || true); do
    COMM=$(cat /proc/$P/comm 2>/dev/null || echo "")
    case "$COMM" in
        python*) kill -9 "$P" 2>/dev/null || true ;;
    esac
done
rm -f /opt/bridge/bridge.pid

# Wait briefly for port to release.
for _ in 1 2 3 4 5; do
    ss -Hltn 2>/dev/null | awk '{{print $4}}' | grep -q ':9300$' || break
    sleep 0.2
done

echo "===== bridge launching at $(date -u +%FT%TZ) =====" >> /var/log/octo/bridge.log
setsid nohup /opt/bridge/.venv/bin/python -m bridge.main \\
    >> /var/log/octo/bridge.log 2>&1 < /dev/null &
BRIDGE_PID=$!
disown
echo "$BRIDGE_PID" > /opt/bridge/bridge.pid
sleep 0.7
if kill -0 "$BRIDGE_PID" 2>/dev/null; then
    echo "bridge launched: pid=$BRIDGE_PID"
else
    echo "bridge exited within 0.7s — log follows:" >&2
    tail -n 80 /var/log/octo/bridge.log >&2 || true
    exit 1
fi
"""
        try:
            res = await self._provider.exec_oneshot(
                _handle_of(sandbox),
                ["bash", "-lc", launch_script],
                env=env,
                cwd="/",
                timeout_s=30,
            )
        except Exception as exc:  # noqa: BLE001
            # Sprites SDK rc37 TimeoutError(**kwargs) bug — catch broadly.
            raise SpritesError(
                f"bridge exec_launch ({type(exc).__name__}): {str(exc)[:200]}",
                retriable=True,
            ) from exc
        if res.exit_code != 0:
            raise SpritesError(
                f"bridge exec_launch exit {res.exit_code}: "
                f"{res.stderr.strip()[-200:]}",
                retriable=False,
            )
        _logger.info(
            "bridge_session_fleet.exec_launched",
            sandbox_id=str(sandbox.id),
            stdout=res.stdout.strip()[-200:],
        )

    async def restart(self, sandbox: Sandbox) -> None:
        """Force-restart the bridge daemon (e.g. after a wheel reinstall
        when we need the new code to actually load). Stops the running
        service so the next `ensure_started` (called by the chat path)
        rebuilds it cleanly.

        We deliberately DO NOT mint a fresh token here — `ensure_started`
        adopts the existing service env when present, so the token
        survives restarts. Pure rotation paths (security) should call
        `rotate_token()` explicitly (not yet implemented in v1).
        """
        if sandbox.id is None:
            return
        sandbox_id = str(sandbox.id)
        # Stop the running service so the next ensure_started's start
        # call brings it up fresh (picks up new wheel code).
        try:
            await self._provider.stop_service(
                _handle_of(sandbox), name=BRIDGE_SERVICE_NAME
            )
        except SpritesError as exc:
            _logger.info(
                "bridge_session_fleet.stop_warning",
                sandbox_id=sandbox_id, error=str(exc)[:200],
            )
        # Drop session + cached env so ensure_started re-adopts.
        async with self._lock:
            session = self._sessions.pop(sandbox_id, None)
            self._cached_env.pop(sandbox_id, None)
        if session is not None:
            await session.close()
        try:
            await self.ensure_started(sandbox)
        except SpritesError as exc:
            _logger.warning(
                "bridge_session_fleet.restart_failed",
                sandbox_id=sandbox_id, error=str(exc)[:200],
            )

    # ── Live log streaming for the debug WS endpoint ─────────────────

    def subscribe_logs(
        self, sandbox_id: str
    ) -> asyncio.Queue[ServiceLogLine | None]:
        """Return a queue that receives every log line for this sandbox's
        bridge service. Caller is responsible for draining + closing
        (push None to terminate). The fleet starts a single tail task
        per sandbox the first time anyone subscribes."""
        queue: asyncio.Queue[ServiceLogLine | None] = asyncio.Queue()
        self._log_taps.setdefault(sandbox_id, []).append(queue)
        if sandbox_id not in self._log_tasks:
            self._log_tasks[sandbox_id] = asyncio.create_task(
                self._tail_logs_forever(sandbox_id),
                name=f"bridge-logs-{sandbox_id}",
            )
        return queue

    def unsubscribe_logs(
        self, sandbox_id: str, queue: asyncio.Queue[ServiceLogLine | None]
    ) -> None:
        try:
            self._log_taps.get(sandbox_id, []).remove(queue)
        except ValueError:
            pass

    async def _tail_logs_forever(self, sandbox_id: str) -> None:
        """Tail `/var/log/octo/bridge.log` via repeated `tail -n` calls.

        Sprites' Services API was unusable on the user's Sprites version,
        so we don't use `service_logs`. Instead we poll the same log
        file the legacy `_ensure_bridge_running` writes to (the bridge
        is launched with stdout/stderr redirected there). Polls every
        ~1s and emits only the lines we haven't already streamed.
        """
        last_size = 0
        backoff = 1.0
        while sandbox_id in self._log_tasks:
            sandbox = await Sandbox.get(PydanticObjectId(sandbox_id))
            if sandbox is None:
                await asyncio.sleep(backoff)
                continue
            # `wc -c` then read from `last_size` to current. Cheap on
            # a kilobyte-scale log; we cap at ~64 KB per poll to stay
            # bounded if something explodes.
            shell = (
                "F=/var/log/octo/bridge.log; "
                "if [ ! -f \"$F\" ]; then echo SIZE=0; exit 0; fi; "
                f"SIZE=$(wc -c < \"$F\"); "
                f"echo SIZE=$SIZE; "
                f"if [ \"$SIZE\" -gt {last_size} ]; then "
                f"  echo '---DATA---'; "
                f"  tail -c +{last_size + 1} \"$F\" | head -c 65536; "
                f"fi"
            )
            try:
                res = await self._provider.exec_oneshot(
                    _handle_of(sandbox),
                    ["bash", "-lc", shell],
                    env={},
                    cwd="/",
                    timeout_s=10,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                _logger.info(
                    "bridge_session_fleet.tail_failed",
                    sandbox_id=sandbox_id,
                    error=str(exc)[:200],
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10.0)
                continue
            if res.exit_code != 0:
                await asyncio.sleep(backoff)
                continue
            backoff = 1.0
            stdout = res.stdout
            new_size = last_size
            data: str | None = None
            for chunk in stdout.split("---DATA---", 1):
                pass  # placeholder
            head, sep, tail = stdout.partition("---DATA---")
            for line in head.splitlines():
                if line.startswith("SIZE="):
                    try:
                        new_size = int(line.removeprefix("SIZE=").strip())
                    except ValueError:
                        pass
            if sep:
                data = tail.lstrip("\n")
            if data:
                ts = int(asyncio.get_event_loop().time() * 1000)
                for raw_line in data.splitlines():
                    if not raw_line:
                        continue
                    log_line = ServiceLogLine(
                        kind="stdout",
                        data=raw_line,
                        timestamp_ms=ts,
                        exit_code=None,
                    )
                    for q in list(self._log_taps.get(sandbox_id, [])):
                        try:
                            q.put_nowait(log_line)
                        except asyncio.QueueFull:
                            pass
            last_size = new_size
            await asyncio.sleep(1.0)
