"""Dev-only event injection — slice 5a.

Mounted only when `settings.allow_internal_endpoints` is true. Lets a
developer (or pytest) drive the WS without a real agent yet.
"""

import asyncio

from beanie import PydanticObjectId
from db.models import Sandbox, Task, User
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from shared_models.wire_protocol import DebugEvent

from ..middleware.auth import require_user
from ..services.event_store import append_event

router = APIRouter()


# ── Slice 8 Phase 8d: no-auth bridge debug endpoints ──────────────────


class _DevBridgeStatusResponse(BaseModel):
    sandbox_id: str
    is_running: bool
    pid: int | None
    bridge_version: str | None
    bridge_connected_at: str | None
    bridge_wheel_sha: str | None
    log_tail: list[str]


class _DevBridgeRelaunchResponse(BaseModel):
    sandbox_id: str
    relaunched: bool
    pid: int | None
    wheel_sha_before: str | None
    wheel_sha_after: str | None
    wheel_reinstalled: bool
    wheel_install_error: str | None


class _DevBridgeKillResponse(BaseModel):
    sandbox_id: str
    killed: list[int]
    stdout: str
    stderr: str


@router.post("/sandboxes/{sandbox_id}/bridge/quick-patch")
async def dev_bridge_quick_patch(
    sandbox_id: str, request: Request
) -> dict[str, object]:
    """Quick fix: in-place sed of installed bridge to bind 0.0.0.0."""
    from .sandbox_bridge import _exec, _provider

    try:
        oid = PydanticObjectId(sandbox_id)
    except Exception:
        raise HTTPException(404, detail="sandbox not found")
    sandbox = await Sandbox.get(oid)
    if sandbox is None:
        raise HTTPException(404, detail="sandbox not found")
    provider = _provider(request)
    shell = (
        "F=/opt/bridge/.venv/lib/python3.12/site-packages/bridge/main.py; "
        "grep -n 'host=' $F | head -3; "
        "sed -i 's/host=\"127.0.0.1\"/host=\"0.0.0.0\"/g' $F; "
        "echo '---after---'; "
        "grep -n 'host=' $F | head -3"
    )
    exit_code, stdout, stderr = await _exec(
        provider, sandbox, ["bash", "-lc", shell], timeout_s=10
    )
    return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr[-1000:]}


@router.post("/sandboxes/{sandbox_id}/bridge/launch-debug")
async def dev_bridge_launch_debug(
    sandbox_id: str, request: Request
) -> dict[str, object]:
    """Run a minimal manual bridge launch with full stdout/stderr
    capture so we can see what's actually failing."""
    from .sandbox_bridge import _exec, _provider

    try:
        oid = PydanticObjectId(sandbox_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(404, detail="sandbox not found")
    sandbox = await Sandbox.get(oid)
    if sandbox is None:
        raise HTTPException(404, detail="sandbox not found")
    provider = _provider(request)

    # Use the same env the fleet would inject — minted token + proxy URL.
    # We validate the bridge is actually capable of running real chat
    # against the live orchestrator proxy, in isolation from any
    # currently-running bridge.
    from ..lib.env import settings as _settings
    from ..services.sandbox_manager import _hash_bridge_token, mint_bridge_token

    bridge_token = mint_bridge_token()
    token_hash = _hash_bridge_token(bridge_token)
    if sandbox.id is not None:
        await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
            {"$set": {"bridge_token_hash": token_hash}}
        )

    proxy_base = (
        f"{_settings.orchestrator_base_url.rstrip('/')}"
        f"/api/_internal/anthropic-proxy/{sandbox_id}"
    )

    # Launch bridge as a daemon (nohup+setsid) writing to a log file,
    # then read the log file. This way we don't depend on Sprites' exec
    # timeout — the launch itself is sub-second, and we read the log
    # afterwards.
    # Two-phase: quick launch, then quick read. Each call <8s so
    # we don't hit Sprites' exec timeout.
    launch_shell = (
        "sudo -n install -d -m 0755 -o $(id -un) -g $(id -un) /var/log/octo 2>&1 || true; "
        "pkill -9 -f 'bridge\\.main' 2>/dev/null || true; "
        "rm -f /opt/bridge/bridge.pid; "
        "echo '===== launch '$(date -u +%FT%TZ)' =====' > /var/log/octo/bridge-debug.log; "
        f'BRIDGE_TRANSPORT=service_proxy BRIDGE_LISTEN_PORT=9300 SANDBOX_ID="{sandbox_id}" '
        f'BRIDGE_TOKEN="{bridge_token}" ANTHROPIC_AUTH_TOKEN="{bridge_token}" '
        f'ANTHROPIC_BASE_URL="{proxy_base}" CLAUDE_CODE_API_BASE_URL="{proxy_base}" '
        'WORK_ROOT=/work CLAUDE_AUTH_MODE=platform_api_key '
        'setsid nohup /opt/bridge/.venv/bin/python -m bridge.main '
        '   >> /var/log/octo/bridge-debug.log 2>&1 < /dev/null & '
        'echo $! > /opt/bridge/bridge.pid; sleep 0.5; echo started'
    )
    await _exec(provider, sandbox, ["bash", "-lc", launch_shell], timeout_s=8)
    # Sleep a bit (in our process, not in the sprite) to let bridge run/die
    await asyncio.sleep(5)
    read_shell = (
        "P=$(cat /opt/bridge/bridge.pid 2>/dev/null || echo ''); "
        'if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then echo "BRIDGE_ALIVE pid=$P"; else echo "BRIDGE_DEAD"; fi; '
        "ss -tlnp 2>/dev/null | grep 9300 || echo 'not listening'; "
        "echo '===== log ====='; cat /var/log/octo/bridge-debug.log 2>/dev/null"
    )
    exit_code, stdout, stderr = await _exec(
        provider, sandbox, ["bash", "-lc", read_shell], timeout_s=8
    )
    return {
        "sandbox_id": sandbox_id,
        "exit_code": exit_code,
        "stdout": stdout[-8000:],
        "stderr": stderr[-2000:],
    }


@router.post("/sandboxes/{sandbox_id}/bridge/launch-debug-old")
async def dev_bridge_launch_debug_old(
    sandbox_id: str, request: Request
) -> dict[str, object]:
    """[unused] kept temporarily."""
    from .sandbox_bridge import _exec, _provider

    try:
        oid = PydanticObjectId(sandbox_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(404, detail="sandbox not found")
    sandbox = await Sandbox.get(oid)
    if sandbox is None:
        raise HTTPException(404, detail="sandbox not found")
    provider = _provider(request)

    shell = (
        "echo no-op"
    )
    exit_code, stdout, stderr = await _exec(
        provider, sandbox, ["bash", "-lc", shell], timeout_s=20
    )
    return {
        "sandbox_id": sandbox_id,
        "exit_code": exit_code,
        "stdout": stdout[-4000:],
        "stderr": stderr[-2000:],
    }


@router.post("/sandboxes/{sandbox_id}/bridge/force-relaunch")
async def dev_bridge_force_relaunch(
    sandbox_id: str, request: Request
) -> dict[str, object]:
    """Service-proxy mode: force `fleet.restart(sandbox)` which kills
    by-port and relaunches with a fresh token."""
    try:
        oid = PydanticObjectId(sandbox_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(404, detail="sandbox not found")
    sandbox = await Sandbox.get(oid)
    if sandbox is None:
        raise HTTPException(404, detail="sandbox not found")
    fleet = getattr(request.app.state, "bridge_owner", None)
    from ..services.bridge_session import BridgeSessionFleet
    if not isinstance(fleet, BridgeSessionFleet):
        raise HTTPException(409, detail="not in service_proxy mode")
    await fleet.restart(sandbox)
    return {"sandbox_id": sandbox_id, "ok": True}


@router.post("/sandboxes/{sandbox_id}/bridge/kill")
async def dev_bridge_kill(
    sandbox_id: str, request: Request
) -> _DevBridgeKillResponse:
    """Force-kill any process bound to bridge port 9300 inside the sprite.
    Cleanup hatch when the launch script's `kill` couldn't find the
    actual port owner (e.g. PID file points at a long-dead pid)."""
    from .sandbox_bridge import _exec, _provider

    try:
        oid = PydanticObjectId(sandbox_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(404, detail="sandbox not found")
    sandbox = await Sandbox.get(oid)
    if sandbox is None:
        raise HTTPException(404, detail="sandbox not found")
    provider = _provider(request)

    shell = (
        "PIDS=$(pgrep -f 'bridge\\.main' || true); "
        'echo "killing: $PIDS"; '
        'for P in $PIDS; do kill -9 "$P" 2>/dev/null || true; done; '
        "rm -f /opt/bridge/bridge.pid; "
        "sleep 0.5; "
        "REMAINING=$(pgrep -f 'bridge\\.main' || true); "
        'echo "remaining: $REMAINING"'
    )
    exit_code, stdout, stderr = await _exec(
        provider, sandbox, ["bash", "-lc", shell], timeout_s=15
    )
    killed: list[int] = []
    for line in stdout.splitlines():
        if line.startswith("killing: "):
            for tok in line.removeprefix("killing: ").split():
                try:
                    killed.append(int(tok))
                except ValueError:
                    pass
    return _DevBridgeKillResponse(
        sandbox_id=sandbox_id,
        killed=killed,
        stdout=stdout[-2000:],
        stderr=stderr[-2000:],
    )


@router.get("/sandboxes/{sandbox_id}/bridge/diagnose")
async def dev_bridge_diagnose(
    sandbox_id: str, request: Request
) -> dict[str, object]:
    """One-shot diagnostic battery. Curl-friendly — paste the output
    when something's broken inside the sprite.

    `curl localhost:3001/api/_internal/sandboxes/<id>/bridge/diagnose | jq`
    """
    from .sandbox_bridge import _exec, _provider
    from ..lib.env import settings as _settings

    try:
        oid = PydanticObjectId(sandbox_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(404, detail="sandbox not found")
    sandbox = await Sandbox.get(oid)
    if sandbox is None:
        raise HTTPException(404, detail="sandbox not found")
    provider = _provider(request)

    probes: list[tuple[str, str]] = [
        ("uname", "uname -a; cat /etc/os-release | head -5"),
        ("bridge_debug_log", "echo '== /var/log/octo/bridge.log =='; tail -n 60 /var/log/octo/bridge.log 2>&1; echo '== /.sprite/logs/services/bridge.log =='; tail -n 80 /.sprite/logs/services/bridge.log 2>&1"),
        (
            "installed_tcp_server_source",
            # Check whether the seq-stamping code is in the installed
            # wheel. Returns the relevant lines from tcp_server.py.
            "echo '---tcp_server.py exists?---'; "
            "ls -la /opt/bridge/.venv/lib/python*/site-packages/bridge/tcp_server.py 2>&1; "
            "echo '---grep seq---'; "
            "grep -n 'seq\\|next_seq' /opt/bridge/.venv/lib/python*/site-packages/bridge/tcp_server.py 2>&1 | head -20; "
            "echo '---grep emit---'; "
            "grep -n -A 8 'async def emit' /opt/bridge/.venv/lib/python*/site-packages/bridge/tcp_server.py 2>&1 | head -30",
        ),
        (
            "bridge_wheel_installed",
            "ls -la /opt/bridge/wheels/ 2>&1 | head -10; "
            "echo '---installed-main---'; "
            "ls -la /opt/bridge/.venv/lib/python*/site-packages/bridge/main.py 2>&1; "
            "echo '---version---'; "
            "/opt/bridge/.venv/bin/python -m bridge --version 2>&1 || echo 'FAILED'",
        ),
        (
            "bridge_self_check",
            "BRIDGE_TRANSPORT=service_proxy "
            "BRIDGE_LISTEN_PORT=9300 "
            "SANDBOX_ID=diagprobe "
            "BRIDGE_TOKEN=diagprobe "
            "ANTHROPIC_AUTH_TOKEN=diagprobe "
            "ANTHROPIC_BASE_URL=http://localhost:1 "
            "/opt/bridge/.venv/bin/python -m bridge --self-check 2>&1 || true",
        ),
        ("claude_cli_version", "claude --version 2>&1 | head -3"),
        (
            "toolchain_present",
            "command -v uv 2>&1; command -v node 2>&1; "
            "[ -d /usr/local/nvm ] && echo nvm_ok || echo nvm_MISSING; "
            "[ -d /usr/local/pyenv ] && echo pyenv_ok || echo pyenv_MISSING; "
            "[ -d /usr/local/rbenv ] && echo rbenv_ok || echo rbenv_MISSING; "
            "[ -x /usr/local/cargo/bin/rustup ] && echo rustup_ok || echo rustup_MISSING; "
            "[ -x /opt/bridge/.venv/bin/python ] && echo bridge_venv_ok || echo bridge_venv_MISSING",
        ),
        (
            "running_processes",
            "ps -ef | grep -E 'bridge|claude|python' | grep -v grep | head -20",
        ),
        (
            "ports_listening",
            "ss -tlnp 2>/dev/null | head -20 || netstat -tlnp 2>/dev/null | head -20",
        ),
        (
            "sprites_services_systemd",
            "systemctl status sprites-services 2>&1 | head -15; "
            "echo '---list---'; "
            "systemctl list-units --all 2>&1 | grep -i sprite | head -10; "
            "echo '---etc---'; "
            "ls /etc/systemd/system/ 2>&1 | grep -i sprite | head -10",
        ),
        (
            "anthropic_proxy_reachable",
            "curl -sS -o /dev/null -w 'HTTP %{http_code} (%{time_total}s)\\n' "
            "-X POST -H 'Authorization: Bearer probe' "
            "-H 'Content-Type: application/json' --data '{}' "
            f"{_settings.orchestrator_base_url.rstrip('/')}"
            f"/api/_internal/anthropic-proxy/{sandbox_id}/v1/messages 2>&1 | head -5",
        ),
    ]

    results: list[dict[str, object]] = []
    for label, shell in probes:
        exit_code, stdout, stderr = await _exec(
            provider, sandbox, ["bash", "-lc", shell], timeout_s=10
        )
        results.append(
            {
                "label": label,
                "exit_code": exit_code,
                "stdout": stdout[-4000:],
                "stderr": stderr[-2000:],
            }
        )

    return {
        "sandbox_id": sandbox_id,
        "transport": _settings.bridge_transport,
        "bridge_setup_fingerprint": sandbox.bridge_setup_fingerprint,
        "bridge_wheel_sha": sandbox.bridge_wheel_sha,
        "bridge_version": sandbox.bridge_version,
        "orchestrator_base_url": _settings.orchestrator_base_url,
        "probes": results,
    }


@router.get("/sandboxes/{sandbox_id}/bridge/status")
async def dev_bridge_status(
    sandbox_id: str, request: Request, tail_lines: int = 200
) -> _DevBridgeStatusResponse:
    """Auth-free bridge status. Mirrors `/api/sandboxes/{id}/bridge/status`
    but skips `require_user` so curl works without a session cookie —
    only registered when `ALLOW_INTERNAL_ENDPOINTS=true`."""
    from .sandbox_bridge import _LOG_PATH, _PID_PATH, _exec, _provider

    try:
        oid = PydanticObjectId(sandbox_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(404, detail="sandbox not found")
    sandbox = await Sandbox.get(oid)
    if sandbox is None:
        raise HTTPException(404, detail="sandbox not found")
    provider = _provider(request)
    shell = (
        f"PID=''; "
        f'if [ -f {_PID_PATH} ]; then '
        f'CAND=$(cat {_PID_PATH} 2>/dev/null || true); '
        f'if [ -n "$CAND" ] && kill -0 "$CAND" 2>/dev/null; then '
        f'PID="$CAND"; '
        f"fi; fi; "
        f'echo "PID=$PID"; '
        f"if [ -f {_LOG_PATH} ]; then "
        f"echo '---LOG_BEGIN---'; "
        f"tail -n {tail_lines} {_LOG_PATH}; "
        f"echo '---LOG_END---'; "
        f"fi"
    )
    exit_code, stdout, _stderr = await _exec(
        provider, sandbox, ["bash", "-lc", shell], timeout_s=10
    )
    pid: int | None = None
    log_tail: list[str] = []
    if exit_code == 0:
        in_log = False
        for line in stdout.splitlines():
            if line.startswith("PID="):
                rest = line.removeprefix("PID=").strip()
                if rest:
                    try:
                        pid = int(rest.split()[0])
                    except ValueError:
                        pid = None
            elif line == "---LOG_BEGIN---":
                in_log = True
            elif line == "---LOG_END---":
                in_log = False
            elif in_log:
                log_tail.append(line)
    return _DevBridgeStatusResponse(
        sandbox_id=str(sandbox.id),
        is_running=pid is not None,
        pid=pid,
        bridge_version=sandbox.bridge_version,
        bridge_connected_at=(
            sandbox.bridge_connected_at.isoformat()
            if sandbox.bridge_connected_at is not None
            else None
        ),
        bridge_wheel_sha=sandbox.bridge_wheel_sha,
        log_tail=log_tail,
    )


@router.post("/sandboxes/{sandbox_id}/bridge/relaunch")
async def dev_bridge_relaunch(
    sandbox_id: str, request: Request
) -> _DevBridgeRelaunchResponse:
    """Auth-free relaunch — same chain as the auth'd version. Surfaces
    `wheel_sha_before/after` so you can verify fresh code reached the
    sprite."""
    from .sandbox_bridge import _PID_PATH, _exec, _provider

    try:
        oid = PydanticObjectId(sandbox_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(404, detail="sandbox not found")
    sandbox = await Sandbox.get(oid)
    if sandbox is None:
        raise HTTPException(404, detail="sandbox not found")
    reconciler = getattr(request.app.state, "reconciler", None)
    if reconciler is None:
        raise HTTPException(503, detail="reconciler not initialized")
    install_wheel = getattr(reconciler, "_install_bridge_wheel", None)
    ensure_running = getattr(reconciler, "_ensure_bridge_running", None)
    if ensure_running is None:
        raise HTTPException(503, detail="bridge launch not implemented")

    sha_before = sandbox.bridge_wheel_sha
    wheel_install_error: str | None = None
    if install_wheel is not None:
        try:
            await install_wheel(sandbox)
        except Exception as exc:  # noqa: BLE001
            wheel_install_error = str(exc)[:200]

    fresh = await Sandbox.get(oid)
    sha_after = fresh.bridge_wheel_sha if fresh is not None else sha_before
    wheel_reinstalled = sha_before != sha_after
    if fresh is not None:
        sandbox = fresh

    await ensure_running(sandbox)

    provider = _provider(request)
    exit_code, stdout, _stderr = await _exec(
        provider,
        sandbox,
        [
            "bash",
            "-lc",
            f"if [ -f {_PID_PATH} ]; then "
            f'P=$(cat {_PID_PATH} 2>/dev/null || true); '
            f'if [ -n "$P" ] && kill -0 "$P" 2>/dev/null; then echo "$P"; fi; '
            f"fi",
        ],
        timeout_s=5,
    )
    pid: int | None = None
    if exit_code == 0 and stdout.strip():
        try:
            pid = int(stdout.strip().split()[0])
        except ValueError:
            pid = None
    return _DevBridgeRelaunchResponse(
        sandbox_id=str(sandbox.id),
        relaunched=pid is not None,
        pid=pid,
        wheel_sha_before=sha_before,
        wheel_sha_after=sha_after,
        wheel_reinstalled=wheel_reinstalled,
        wheel_install_error=wheel_install_error,
    )


class InjectEventBody(BaseModel):
    message: str


class CreateTaskResponse(BaseModel):
    id: str


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(user: User = Depends(require_user)) -> CreateTaskResponse:
    """Insert a placeholder `Task` owned by the caller. Slice 6 replaces this
    with a real `POST /api/tasks` that takes a prompt + repo_id."""
    task = Task(user_id=user.id)  # type: ignore[arg-type]
    await task.insert()
    assert task.id is not None
    return CreateTaskResponse(id=str(task.id))


@router.post("/tasks/{task_id}/events", status_code=status.HTTP_202_ACCEPTED)
async def inject_event(
    task_id: str,
    body: InjectEventBody,
    request: Request,
    user: User = Depends(require_user),
) -> dict[str, int | str]:
    """Append a `DebugEvent` to the task's event log + publish to Redis. Seq
    is allocated by `append_event`; the request body is just `message`."""

    try:
        oid = PydanticObjectId(task_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task_not_found") from exc

    task = await Task.get(oid)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task_not_found")
    if task.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    redis_handle = getattr(request.app.state, "redis_handle", None)
    event = await append_event(
        oid,
        DebugEvent(seq=0, message=body.message),
        redis=redis_handle,
    )
    return {"task_id": str(oid), "seq": event.seq}
