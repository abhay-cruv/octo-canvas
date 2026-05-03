"""Live bridge-service debug WebSocket — slice 8 (post-pivot).

`/ws/web/sandboxes/{sandbox_id}/bridge/debug` lets a connected user
tail the bridge service's stdout/stderr in real time AND see a
snapshot of the auth wiring (which env vars the proxy expects, whether
the Anthropic auth token is plumbed, the latest service status).

Why this exists: the bridge runs as a Sprites Service and prints
everything to its log. We don't want every user to need `ssh` access
to see why their chat is stuck on Claude auth (or why the bridge
crashed at boot). This route surfaces the same stream you'd see from
`POST /v1/sprites/{name}/services/bridge/logs` plus an initial
`status` frame summarising what the orchestrator believes is wired.

Auth: session cookie (same shape as `ws/chats.py`). Ownership: the
sandbox must belong to the connected user.

Frame shape (server → client, JSON-per-text-message):
  {"type": "status", ...}                  — sent on connect
  {"type": "log", "kind": "stdout", "data": "..."}
  {"type": "log", "kind": "stderr", "data": "..."}
  {"type": "log", "kind": "exit", "exit_code": 0}
  {"type": "log", "kind": "started"}
  {"type": "error", "message": "..."}      — terminal
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any, cast

import structlog
from beanie import PydanticObjectId
from db.models import Sandbox, Session, User
from fastapi import APIRouter, WebSocket
from sandbox_provider import SandboxHandle, ServiceLogLine, SpritesError
from starlette.websockets import WebSocketDisconnect

from ..lib.env import settings
from ..middleware.auth import SESSION_COOKIE_NAME
from ..services.bridge_session import BRIDGE_SERVICE_NAME, BridgeSessionFleet

router = APIRouter()
_logger = structlog.get_logger("ws.bridge_debug")


async def _resolve_user_for_ws(websocket: WebSocket) -> User | None:
    session_id = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    session = await Session.find_one(Session.session_id == session_id)
    if session is None:
        return None
    return await User.get(session.user_id)


def _handle_of(sandbox: Sandbox) -> SandboxHandle:
    return SandboxHandle(provider=sandbox.provider_name, payload=sandbox.provider_handle)


@router.websocket("/ws/web/sandboxes/{sandbox_id}/bridge/debug")
async def bridge_debug(websocket: WebSocket, sandbox_id: str) -> None:
    await websocket.accept()

    user = await _resolve_user_for_ws(websocket)
    if user is None:
        await websocket.close(code=4001, reason="unauthenticated")
        return
    try:
        oid = PydanticObjectId(sandbox_id)
    except Exception:  # noqa: BLE001
        await websocket.close(code=4004, reason="sandbox_not_found")
        return
    sandbox = await Sandbox.get(oid)
    if sandbox is None or sandbox.user_id != user.id:
        await websocket.close(code=4004, reason="sandbox_not_found")
        return

    provider = getattr(websocket.app.state, "sandbox_provider", None)
    bridge_owner = getattr(websocket.app.state, "bridge_owner", None)
    transport = settings.bridge_transport

    # Always send an initial status frame — even in dial_back mode, so
    # the user can see why log streaming isn't available.
    status_frame = await _build_status_frame(
        sandbox=sandbox,
        bridge_owner=bridge_owner,
        provider=provider,
        transport=transport,
    )
    try:
        await websocket.send_text(json.dumps(status_frame))
    except (WebSocketDisconnect, RuntimeError):
        return

    # Run a diagnostic battery — answers the questions a human would
    # actually have when "the bridge isn't working":
    #   - Is the wheel installed? Right version?
    #   - Can we manually invoke `bridge.main`? Does it crash on auth?
    #   - Are the toolchain managers reachable?
    #   - In service_proxy mode: does Sprites' Services API work AT ALL
    #     on this sprite? What about the proxy endpoint?
    if provider is not None:
        await _run_diagnostics(
            websocket=websocket,
            sandbox=sandbox,
            provider=provider,
        )

    # Open the interactive exec channel. Client may send:
    #   {"type": "exec", "id": "<corr-id>", "argv": ["bash", "-lc", "..."],
    #    "timeout_s": 30}
    # We reply with `{"type": "exec_result", "id": "...", ...}`. Tail the
    # bridge service log stream in parallel when service_proxy is active.
    log_queue: asyncio.Queue[ServiceLogLine | None] | None = None
    if transport == "service_proxy" and isinstance(bridge_owner, BridgeSessionFleet):
        log_queue = bridge_owner.subscribe_logs(sandbox_id)

    interactive_task = asyncio.create_task(
        _interactive_loop(websocket, sandbox, provider),
        name=f"bridge-debug-rx-{sandbox_id}",
    )
    pump_task: asyncio.Task[None] | None = None
    if log_queue is not None:
        pump_task = asyncio.create_task(
            _pump_logs(websocket, log_queue),
            name=f"bridge-debug-logs-{sandbox_id}",
        )

    try:
        tasks = {interactive_task}
        if pump_task is not None:
            tasks.add(pump_task)
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in pending:
            with suppress(asyncio.CancelledError, Exception):
                await task
    finally:
        if log_queue is not None and isinstance(bridge_owner, BridgeSessionFleet):
            bridge_owner.unsubscribe_logs(sandbox_id, log_queue)
            with suppress(Exception):
                log_queue.put_nowait(None)


async def _pump_logs(
    websocket: WebSocket, queue: asyncio.Queue[ServiceLogLine | None]
) -> None:
    while True:
        line = await queue.get()
        if line is None:
            return
        body: dict[str, Any] = {
            "type": "log",
            "kind": line.kind,
            "data": line.data,
            "timestamp_ms": line.timestamp_ms,
        }
        if line.exit_code is not None:
            body["exit_code"] = line.exit_code
        try:
            await websocket.send_text(json.dumps(body))
        except (WebSocketDisconnect, RuntimeError):
            return


async def _interactive_loop(
    websocket: WebSocket, sandbox: Sandbox, provider: object
) -> None:
    """Read JSON messages from the client and run them via
    `provider.exec_oneshot`. Lets a logged-in user poke the sprite
    interactively from the browser dev console without needing
    Sprites' web shell or a service-API roundtrip.

    Accepted shape:
      {"type": "exec", "id": "<corr-id>", "argv": [...], "timeout_s": 30,
       "cwd": "/", "env": {...}}
    We reply:
      {"type": "exec_result", "id": "...", "exit_code": 0,
       "stdout": "...", "stderr": "..."}

    Any single response is capped at ~64 KB stdout/stderr — anything
    larger gets truncated with a tail marker.
    """
    from sandbox_provider import SandboxProvider

    provider_typed = cast("SandboxProvider", provider)
    handle = _handle_of(sandbox)

    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return
        except Exception:  # noqa: BLE001
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await _send_json(
                websocket, {"type": "error", "message": "invalid json"}
            )
            continue
        if not isinstance(msg, dict):
            continue
        kind = msg.get("type")
        if kind != "exec":
            await _send_json(
                websocket,
                {
                    "type": "error",
                    "message": f"unknown message type: {kind!r} (expected 'exec')",
                },
            )
            continue
        argv = msg.get("argv")
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            await _send_json(
                websocket,
                {"type": "error", "message": "exec.argv must be a list[str]"},
            )
            continue
        cid = str(msg.get("id") or "")
        cwd_raw = msg.get("cwd")
        cwd: str = cwd_raw if isinstance(cwd_raw, str) else "/"
        env_raw = msg.get("env")
        env: dict[str, str] = (
            {str(k): str(v) for k, v in env_raw.items()}
            if isinstance(env_raw, dict)
            else {}
        )
        timeout_s = int(msg.get("timeout_s") or 30)
        timeout_s = max(1, min(timeout_s, 120))

        try:
            res = await provider_typed.exec_oneshot(
                handle,
                argv,
                env=env,
                cwd=cwd,
                timeout_s=timeout_s,
            )
            await _send_json(
                websocket,
                {
                    "type": "exec_result",
                    "id": cid,
                    "exit_code": res.exit_code,
                    "stdout": _trunc(res.stdout),
                    "stderr": _trunc(res.stderr),
                    "duration_s": getattr(res, "duration_s", None),
                },
            )
        except Exception as exc:  # noqa: BLE001
            await _send_json(
                websocket,
                {
                    "type": "exec_result",
                    "id": cid,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"{type(exc).__name__}: {str(exc)[:500]}",
                },
            )


def _trunc(s: str, *, limit: int = 64_000) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n…[truncated {len(s) - limit} bytes]"


async def _send_json(websocket: WebSocket, body: dict[str, Any]) -> None:
    with suppress(WebSocketDisconnect, RuntimeError):
        await websocket.send_text(json.dumps(body))


async def _run_diagnostics(
    *,
    websocket: WebSocket,
    sandbox: Sandbox,
    provider: object,
) -> None:
    """Run a battery of read-only checks and stream each result. Fires
    on connect so the user immediately sees what's broken without
    typing commands."""
    from sandbox_provider import SandboxProvider, SpritesError

    provider_typed = cast("SandboxProvider", provider)
    handle = _handle_of(sandbox)

    # (label, argv) — keep the list short and fast. Any individual probe
    # capped at 10s so a hung sprite doesn't stall the whole battery.
    probes: list[tuple[str, list[str]]] = [
        ("uname", ["bash", "-lc", "uname -a; cat /etc/os-release | head -5"]),
        (
            "bridge_wheel_installed",
            [
                "bash",
                "-lc",
                "ls -la /opt/bridge/wheels/ 2>&1 | head -10; "
                "echo '---'; "
                "ls -la /opt/bridge/.venv/lib/python*/site-packages/bridge/main.py 2>&1; "
                "echo '---'; "
                "/opt/bridge/.venv/bin/python -m bridge --version 2>&1 || echo 'bridge --version FAILED'",
            ],
        ),
        (
            "bridge_main_dry_run",
            [
                "bash",
                "-lc",
                "BRIDGE_TRANSPORT=service_proxy "
                "BRIDGE_LISTEN_PORT=9300 "
                "SANDBOX_ID=diagprobe "
                "BRIDGE_TOKEN=diagprobe "
                "ANTHROPIC_AUTH_TOKEN=diagprobe "
                "ANTHROPIC_BASE_URL=http://localhost:1 "
                "/opt/bridge/.venv/bin/python -m bridge --self-check 2>&1 || true",
            ],
        ),
        (
            "claude_cli_version",
            ["bash", "-lc", "claude --version 2>&1 | head -3"],
        ),
        (
            "toolchain_present",
            [
                "bash",
                "-lc",
                "command -v uv && command -v node && "
                "[ -d /usr/local/nvm ] && echo nvm_ok && "
                "[ -d /usr/local/pyenv ] && echo pyenv_ok && "
                "[ -d /usr/local/rbenv ] && echo rbenv_ok && "
                "[ -x /usr/local/cargo/bin/rustup ] && echo rustup_ok && "
                "[ -x /opt/bridge/.venv/bin/python ] && echo bridge_venv_ok",
            ],
        ),
        (
            "running_processes",
            [
                "bash",
                "-lc",
                "ps -ef | grep -E 'bridge|claude|python' | grep -v grep | head -20",
            ],
        ),
        (
            "ports_listening",
            [
                "bash",
                "-lc",
                "ss -tlnp 2>/dev/null | head -20 || netstat -tlnp 2>/dev/null | head -20",
            ],
        ),
        (
            "sprites_services_systemd",
            [
                "bash",
                "-lc",
                "systemctl status sprites-services 2>&1 | head -15; "
                "echo '---'; "
                "systemctl list-units --all 2>&1 | grep -i sprite | head -10; "
                "echo '---'; "
                "ls /etc/systemd/system/ 2>&1 | grep -i sprite | head -10",
            ],
        ),
        (
            "anthropic_proxy_reachable",
            [
                "bash",
                "-lc",
                "curl -sS -o /dev/null -w 'HTTP %{http_code} (%{time_total}s)\\n' "
                "-X POST -H 'Authorization: Bearer probe' "
                "-H 'Content-Type: application/json' "
                "--data '{}' "
                f"{settings.orchestrator_base_url.rstrip('/')}"
                f"/api/_internal/anthropic-proxy/{sandbox.id}/v1/messages "
                "2>&1 | head -5",
            ],
        ),
    ]

    await _send_json(
        websocket,
        {"type": "diag_start", "probe_count": len(probes)},
    )

    for label, argv in probes:
        try:
            res = await provider_typed.exec_oneshot(
                handle,
                argv,
                env={},
                cwd="/",
                timeout_s=10,
            )
            await _send_json(
                websocket,
                {
                    "type": "diag",
                    "label": label,
                    "exit_code": res.exit_code,
                    "stdout": _trunc(res.stdout, limit=8_000),
                    "stderr": _trunc(res.stderr, limit=8_000),
                },
            )
        except SpritesError as exc:
            await _send_json(
                websocket,
                {
                    "type": "diag",
                    "label": label,
                    "exit_code": -1,
                    "error": f"SpritesError: {str(exc)[:300]}",
                },
            )
        except Exception as exc:  # noqa: BLE001
            await _send_json(
                websocket,
                {
                    "type": "diag",
                    "label": label,
                    "exit_code": -1,
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                },
            )

    await _send_json(websocket, {"type": "diag_complete"})


async def _send_error(websocket: WebSocket, message: str) -> None:
    with suppress(WebSocketDisconnect, RuntimeError):
        await websocket.send_text(
            json.dumps({"type": "error", "message": message})
        )


async def _build_status_frame(
    *,
    sandbox: Sandbox,
    bridge_owner: object,
    provider: object,
    transport: str,
) -> dict[str, Any]:
    """Snapshot of what the orchestrator believes about the bridge.

    Includes:
    - transport mode (dial_back vs service_proxy)
    - service status (stopped/starting/running/...) when service_proxy
    - claude auth wiring summary (which env vars are configured)
    - bridge metadata persisted on the Sandbox doc
    Designed to make 'why is Claude auth broken' visible at a glance.
    """
    body: dict[str, Any] = {
        "type": "status",
        "sandbox_id": str(sandbox.id),
        "transport": transport,
        "bridge_setup_fingerprint": sandbox.bridge_setup_fingerprint,
        "bridge_wheel_sha": sandbox.bridge_wheel_sha,
        "bridge_version": sandbox.bridge_version,
        "bridge_connected_at": (
            sandbox.bridge_connected_at.isoformat()
            if sandbox.bridge_connected_at is not None
            else None
        ),
        "bridge_token_hash_set": sandbox.bridge_token_hash is not None,
        "claude_auth": {
            "mode": settings.claude_auth_mode,
            "anthropic_base_url_template": (
                f"{settings.orchestrator_base_url.rstrip('/')}"
                f"/api/_internal/anthropic-proxy/{sandbox.id}"
            ),
            # We can't reach into the running service to inspect its
            # actual env, but we describe what *should* be there.
            "expected_env_vars": [
                "ANTHROPIC_BASE_URL",
                "CLAUDE_CODE_API_BASE_URL",
                "ANTHROPIC_AUTH_TOKEN",
                "BRIDGE_TOKEN",
                "BRIDGE_TRANSPORT",
            ],
        },
    }

    if transport == "service_proxy" and isinstance(bridge_owner, BridgeSessionFleet):
        body["service_proxy"] = {
            "service_name": BRIDGE_SERVICE_NAME,
            "listen_port": settings.bridge_listen_port,
        }
        # Fetch live service status — best-effort. Skip on dial_back.
        if provider is not None:
            try:
                from sandbox_provider import SandboxProvider

                provider_typed = cast("SandboxProvider", provider)
                status = await provider_typed.service_status(
                    _handle_of(sandbox), name=BRIDGE_SERVICE_NAME
                )
                body["service_proxy"]["status"] = {
                    "status": status.status,
                    "pid": status.pid,
                    "started_at": status.started_at,
                    "error": status.error,
                }
            except SpritesError as exc:
                body["service_proxy"]["status_error"] = str(exc)[:200]
            except Exception as exc:  # noqa: BLE001
                body["service_proxy"]["status_error"] = (
                    f"{type(exc).__name__}: {str(exc)[:200]}"
                )
    return body
