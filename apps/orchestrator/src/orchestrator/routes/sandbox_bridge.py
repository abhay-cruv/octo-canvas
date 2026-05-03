"""Bridge daemon observability + control — slice 8 Phase 8c.

Surfaces the bridge process running inside the sprite to the
dashboard (and to anyone debugging via curl):

- `GET /api/sandboxes/{id}/bridge/status` — is it up? what version?
  pid? when did it last connect to the orchestrator? recent log tail?
- `POST /api/sandboxes/{id}/bridge/relaunch` — kill + restart the
  daemon without doing a full Reset (which wipes /work).
- `GET /api/sandboxes/{id}/bridge/log?lines=N` — last N lines of
  `/var/log/octo/bridge.log`. Useful for "what blew up at startup?"

Backed entirely by `provider.exec_oneshot` — no new Protocol surface.
Auth: session cookie + ownership of the sandbox.
"""

from __future__ import annotations

from typing import Annotated, cast

import structlog
from beanie import PydanticObjectId
from db.models import Sandbox, User
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sandbox_provider import SandboxHandle, SandboxProvider, SpritesError

from ..middleware.auth import require_user

router = APIRouter()
_logger = structlog.get_logger("sandbox_bridge")

_LOG_PATH = "/var/log/octo/bridge.log"
_PID_PATH = "/opt/bridge/bridge.pid"
_DEFAULT_TAIL_LINES = 200
_MAX_TAIL_LINES = 2_000


class BridgeStatusResponse(BaseModel):
    sandbox_id: str
    is_running: bool
    pid: int | None
    bridge_version: str | None
    bridge_connected_at: str | None  # ISO-8601, populated by WSS handshake
    bridge_token_hash_set: bool
    bridge_wheel_sha: str | None
    last_acked_seq_per_chat: dict[str, int]
    log_tail: list[str]
    log_path: str = _LOG_PATH


class BridgeLogResponse(BaseModel):
    sandbox_id: str
    log_path: str = _LOG_PATH
    lines: list[str]
    truncated: bool


class BridgeRelaunchResponse(BaseModel):
    sandbox_id: str
    relaunched: bool
    pid: int | None
    detail: str
    # Phase 8d: did we actually rebuild + push a fresh wheel before
    # relaunching? Lets the caller distinguish "killed + restarted
    # SAME code" from "deployed new code."
    wheel_sha_before: str | None = None
    wheel_sha_after: str | None = None
    wheel_reinstalled: bool = False
    wheel_install_error: str | None = None


def _provider(request: Request) -> SandboxProvider:
    return cast("SandboxProvider", request.app.state.sandbox_provider)


def _handle_of(sandbox: Sandbox) -> SandboxHandle:
    """Same helper used by reconciliation — opaque payload from
    `Sandbox.provider_handle`."""
    from sandbox_provider import SandboxHandle as _Handle

    return _Handle(provider=sandbox.provider_name, payload=sandbox.provider_handle)


async def _load_owned_sandbox(sandbox_id: str, user: User) -> Sandbox:
    try:
        oid = PydanticObjectId(sandbox_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(404, detail="sandbox not found")
    sandbox = await Sandbox.get(oid)
    if sandbox is None or sandbox.user_id != user.id:
        raise HTTPException(404, detail="sandbox not found")
    if sandbox.status == "destroyed":
        raise HTTPException(409, detail="sandbox is destroyed")
    return sandbox


async def _exec(
    provider: SandboxProvider, sandbox: Sandbox, cmd: list[str], *, timeout_s: int = 15
) -> tuple[int, str, str]:
    try:
        res = await provider.exec_oneshot(
            _handle_of(sandbox),
            cmd,
            env={},
            cwd="/",
            timeout_s=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        # Sprites SDK rc37 has a `TimeoutError(**kwargs)` bug that
        # raises `TypeError` on timeout — `except SpritesError` would
        # let it escape and 500 the route. Catch broadly and surface
        # the real exception class in the returned error string.
        _logger.warning(
            "bridge_status.exec_failed",
            sandbox_id=str(sandbox.id),
            error=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
        return -1, "", f"{type(exc).__name__}: {str(exc)[:200]}"
    return res.exit_code, res.stdout, res.stderr


@router.get(
    "/{sandbox_id}/bridge/status", response_model=BridgeStatusResponse
)
async def get_bridge_status(
    sandbox_id: str,
    request: Request,
    tail_lines: Annotated[int, Query(ge=0, le=_MAX_TAIL_LINES)] = 50,
    user: User = Depends(require_user),
) -> BridgeStatusResponse:
    sandbox = await _load_owned_sandbox(sandbox_id, user)
    provider = _provider(request)

    # Single shell call gathers everything: pid (if any) + log tail.
    # PID file is canonical — pgrep-with-pattern can't be used because
    # the bash wrapper's argv contains the same string we'd grep for
    # (matching itself). `kill -0` validates the pid is actually alive.
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

    return BridgeStatusResponse(
        sandbox_id=str(sandbox.id),
        is_running=pid is not None,
        pid=pid,
        bridge_version=sandbox.bridge_version,
        bridge_connected_at=(
            sandbox.bridge_connected_at.isoformat()
            if sandbox.bridge_connected_at is not None
            else None
        ),
        bridge_token_hash_set=sandbox.bridge_token_hash is not None,
        bridge_wheel_sha=sandbox.bridge_wheel_sha,
        last_acked_seq_per_chat=dict(sandbox.bridge_last_acked_seq_per_chat),
        log_tail=log_tail,
    )


@router.get(
    "/{sandbox_id}/bridge/log", response_model=BridgeLogResponse
)
async def get_bridge_log(
    sandbox_id: str,
    request: Request,
    lines: Annotated[int, Query(ge=1, le=_MAX_TAIL_LINES)] = _DEFAULT_TAIL_LINES,
    user: User = Depends(require_user),
) -> BridgeLogResponse:
    sandbox = await _load_owned_sandbox(sandbox_id, user)
    provider = _provider(request)
    exit_code, stdout, stderr = await _exec(
        provider,
        sandbox,
        [
            "bash",
            "-lc",
            f"if [ -f {_LOG_PATH} ]; then tail -n {lines} {_LOG_PATH}; fi",
        ],
        timeout_s=10,
    )
    if exit_code != 0:
        return BridgeLogResponse(
            sandbox_id=str(sandbox.id),
            lines=[f"(exec failed: {stderr.strip()[-200:]})"],
            truncated=False,
        )
    out_lines = stdout.splitlines()
    return BridgeLogResponse(
        sandbox_id=str(sandbox.id),
        lines=out_lines,
        truncated=len(out_lines) >= lines,
    )


@router.post(
    "/{sandbox_id}/bridge/relaunch", response_model=BridgeRelaunchResponse
)
async def post_bridge_relaunch(
    sandbox_id: str,
    request: Request,
    user: User = Depends(require_user),
) -> BridgeRelaunchResponse:
    """Kill + restart the bridge daemon without a full Reset. Pulls
    the launch logic out of `Reconciler._ensure_bridge_running` so we
    can fire it on demand. The token rotates on every relaunch (we
    only persist its sha256 — nothing to recover the plaintext for)."""
    sandbox = await _load_owned_sandbox(sandbox_id, user)

    reconciler = getattr(request.app.state, "reconciler", None)
    if reconciler is None:
        raise HTTPException(503, detail="reconciler not initialized")

    ensure_running = getattr(reconciler, "_ensure_bridge_running", None)
    install_wheel = getattr(reconciler, "_install_bridge_wheel", None)
    if ensure_running is None:
        raise HTTPException(503, detail="bridge launch not implemented")
    # Preconditions — surface them clearly rather than letting the
    # method silently no-op.
    if sandbox.bridge_setup_fingerprint is None:
        raise HTTPException(
            409,
            detail={
                "code": "bridge_setup_missing",
                "message": "bridge prerequisites haven't finished installing",
            },
        )
    if sandbox.bridge_wheel_sha is None:
        raise HTTPException(
            409,
            detail={
                "code": "bridge_wheel_missing",
                "message": "bridge wheel hasn't been installed yet — wait for reconcile",
            },
        )
    bridge_config = getattr(request.app.state, "bridge_config", None)
    if bridge_config is None:
        raise HTTPException(503, detail="bridge_config not initialized")
    if not bridge_config.orchestrator_base_url:
        raise HTTPException(
            409,
            detail={
                "code": "no_orchestrator_url",
                "message": (
                    "ORCHESTRATOR_BASE_URL is empty — set it (e.g. via ngrok) so "
                    "the bridge has somewhere to dial."
                ),
            },
        )

    # Rebuild + re-upload the wheel before relaunching so a fresh
    # `pnpm dev` edit to bridge sources actually reaches the sprite.
    # Force-build (no in-memory cache) so a stale uvicorn process
    # can't keep serving an old bundle.
    sha_before = sandbox.bridge_wheel_sha
    wheel_install_error: str | None = None
    if install_wheel is not None:
        try:
            await install_wheel(sandbox)
        except Exception as exc:  # noqa: BLE001
            wheel_install_error = str(exc)[:200]
            _logger.warning(
                "bridge_relaunch.wheel_install_failed",
                sandbox_id=sandbox_id,
                error=wheel_install_error,
            )
    # Re-load the doc so we see the freshly persisted `bridge_wheel_sha`.
    fresh = await Sandbox.get(sandbox.id) if sandbox.id is not None else None
    sha_after = fresh.bridge_wheel_sha if fresh is not None else sha_before
    wheel_reinstalled = sha_before != sha_after

    if fresh is not None:
        sandbox = fresh

    await ensure_running(sandbox)

    # Confirm via the PID file (same primitive as the status route).
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
    detail = "relaunched"
    if exit_code == 0 and stdout.strip():
        try:
            pid = int(stdout.strip().split()[0])
        except ValueError:
            detail = "relaunched (pid parse failed)"
    return BridgeRelaunchResponse(
        sandbox_id=str(sandbox.id),
        relaunched=pid is not None,
        pid=pid,
        detail=detail,
        wheel_sha_before=sha_before,
        wheel_sha_after=sha_after,
        wheel_reinstalled=wheel_reinstalled,
        wheel_install_error=wheel_install_error,
    )


# Suppress unused-import warning when none of `Field` or `BaseModel`
# are touched at module level beyond the response classes above.
_ = Field
