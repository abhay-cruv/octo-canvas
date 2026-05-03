"""Bridge entrypoint.

Slice 7 surfaces:

- `python -m bridge --self-check` — load config, validate the
  `ClaudeCredentials` impl is constructible, exit 0. CI smoke calls
  this from inside the sprite image build.
- `python -m bridge --version` — print bridge wheel + baked `claude`
  CLI version. Useful for the boot-time mismatch check slice 8 wires
  in.
- `python -m bridge` — boot, log configuration, and idle-loop
  forever (60s heartbeat). Slice 8 replaces the idle loop with the
  WSS dialer.

The bridge is intentionally allowed to run without
`ORCHESTRATOR_WS_URL` in slice 7 so dev sprites don't spam connection
errors before the WSS handler exists.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from agent_config import ClaudeCredentials, PlatformApiKeyCredentials

from bridge import __version__ as BRIDGE_VERSION
from bridge.config import BridgeSettings, ClaudeAuthMode, baked_cli_version, load_settings
from bridge.lib.logger import configure_logging, get_logger

_HEARTBEAT_INTERVAL_S = 60


def _build_credentials(mode: ClaudeAuthMode) -> ClaudeCredentials:
    if mode == "platform_api_key":
        return PlatformApiKeyCredentials()
    # `user_oauth` / `user_api_key` are reserved by the Protocol per
    # Plan.md §14.7 but have no impl until BYOK lands.
    raise SystemExit(f"unsupported claude auth mode: {mode!r}")


def _self_check(settings: BridgeSettings) -> int:
    logger = get_logger("bridge.self_check")
    creds = _build_credentials(settings.claude_auth_mode)
    # Don't actually call `creds.env()` — that would require the
    # `ANTHROPIC_API_KEY` to be present at image-build time, which
    # it isn't. Just prove the impl is constructible and reports the
    # expected mode.
    logger.info(
        "bridge.self_check.ok",
        bridge_version=BRIDGE_VERSION,
        cli_version=baked_cli_version(),
        claude_auth_mode=creds.mode,
        has_orchestrator_url=bool(settings.orchestrator_ws_url),
    )
    return 0


def _print_version() -> int:
    print(f"bridge {BRIDGE_VERSION} (claude-cli {baked_cli_version()})")
    return 0


async def _idle_loop(settings: BridgeSettings) -> None:
    """Slice 7 fallback when no orchestrator URL is set — just logs a
    heartbeat. Slice 8's `_run_dialer` is what actually does work."""
    logger = get_logger("bridge.idle")
    while True:
        logger.info(
            "bridge.idle.heartbeat",
            bridge_version=BRIDGE_VERSION,
            cli_version=baked_cli_version(),
        )
        await asyncio.sleep(_HEARTBEAT_INTERVAL_S)


async def _run_dialer(settings: BridgeSettings) -> None:
    """Slice 8: dial `/ws/bridge/{sandbox_id}` and run the bridge."""
    from shared_models.wire_protocol import (
        CancelChat,
        OrchestratorToBridge,
        UserMessage as WireUserMessage,
    )

    from bridge.chat_mux import ChatMux
    from bridge.ws_client import WsClient

    logger = get_logger("bridge.dialer")
    credentials = _build_credentials(settings.claude_auth_mode)

    ws_holder: dict[str, WsClient] = {}
    mux_holder: dict[str, ChatMux] = {}

    async def emit(chat_id: str, frame_type: str, payload: dict[str, object]) -> None:
        ws = ws_holder.get("ws")
        if ws is not None:
            await ws.emit(chat_id, frame_type, payload)

    async def handle_command(frame: OrchestratorToBridge) -> None:
        mux = mux_holder.get("mux")
        if mux is None:
            return
        if isinstance(frame, WireUserMessage):
            await mux.handle_user_message(
                chat_id=frame.chat_id,
                text=frame.text,
                claude_session_id=frame.claude_session_id,
                permission_mode=getattr(frame, "permission_mode", None),
            )
        elif isinstance(frame, CancelChat):
            await mux.cancel(frame.chat_id)
        # Ping / Ack / ChatState handled inside `WsClient`. PauseChat /
        # SessionEnv are reserved variants — dropped on the floor in v1.

    mux = ChatMux(
        cwd=settings.work_root,
        credentials=credentials,
        emit=emit,
        max_live_chats=settings.max_live_chats_per_sandbox,
    )
    mux_holder["mux"] = mux

    # `BridgeRuntimeConfig.env_for(...)` already builds the full
    # `wss://<orch>/ws/bridge/<sandbox_id>` URL — use as-is. (Earlier
    # versions of this file appended the path again, producing
    # `/ws/bridge/<id>/ws/bridge/<id>` and a 403 from the orchestrator.)
    ws_url = settings.orchestrator_ws_url
    ws = WsClient(
        url=ws_url,
        bridge_token=settings.bridge_token,
        bridge_version=BRIDGE_VERSION,
        handle_command=handle_command,
    )
    ws_holder["ws"] = ws

    logger.info(
        "bridge.dialer.start",
        url=ws_url,
        sandbox_id=settings.sandbox_id,
        max_live_chats=settings.max_live_chats_per_sandbox,
        idle_exit_s=settings.idle_after_disconnect_s,
    )
    # Phase 8d: bridge runs only while there's chat work. After
    # `IDLE_AFTER_DISCONNECT_S` seconds with `mux.has_live_chats() ==
    # False`, exit cleanly so Sprites can hibernate the sandbox. The
    # orchestrator's `_ensure_bridge_running` (or `BridgeOwner.kick_idle_bridge`
    # falling through) relaunches us when the next user message arrives.
    ws_task = asyncio.create_task(ws.run(), name="ws-client")
    idle_task = asyncio.create_task(
        _wait_for_idle(mux, settings.idle_after_disconnect_s),
        name="idle-watch",
    )
    try:
        done, _pending = await asyncio.wait(
            {ws_task, idle_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if idle_task in done and not ws_task.done():
            logger.info(
                "bridge.dialer.idle_exit",
                idle_after_s=settings.idle_after_disconnect_s,
            )
            await ws.stop()
            ws_task.cancel()
        else:
            idle_task.cancel()
        for t in (ws_task, idle_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
    finally:
        await mux.shutdown()


async def _wait_for_idle(
    mux: "object",  # ChatMux — typed loose to avoid circular import
    idle_after_s: int,
    *,
    poll_s: float = 5.0,
) -> None:
    """Returns when `mux.has_live_chats()` has been False continuously
    for `idle_after_s` seconds. Default poll cadence is 5s — we'd
    rather err a few seconds late than burn cpu. Tests pass a smaller
    `poll_s` to keep the suite fast.

    Any new chat resets the counter, so a chat that fires + finishes
    + is replaced inside the window keeps the bridge alive without
    flapping."""
    quiet_since: float | None = None
    while True:
        await asyncio.sleep(poll_s)
        has_live = bool(getattr(mux, "has_live_chats", lambda: True)())
        now = asyncio.get_event_loop().time()
        if has_live:
            quiet_since = None
            continue
        if quiet_since is None:
            quiet_since = now
            continue
        if now - quiet_since >= idle_after_s:
            return


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bridge", description="octo-canvas sprite bridge")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Validate config + credentials impl, then exit 0.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print bridge + baked CLI versions and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)

    if args.version:
        return _print_version()

    try:
        settings = load_settings()
    except Exception as exc:  # noqa: BLE001 — surface the config error nicely
        get_logger("bridge.startup").error("bridge.config.load_failed", error=str(exc))
        return 2

    if args.self_check:
        return _self_check(settings)

    # `BRIDGE_TOKEN` is only required when there's an orchestrator to
    # talk to — without `ORCHESTRATOR_WS_URL` the bridge idles and the
    # token would never be presented anywhere. This keeps `pnpm dev`
    # working on a laptop where neither var is set.
    if settings.orchestrator_ws_url and not settings.bridge_token:
        get_logger("bridge.startup").error(
            "bridge.config.missing_bridge_token",
            hint=(
                "ORCHESTRATOR_WS_URL is set but BRIDGE_TOKEN is empty — "
                "the bridge cannot authenticate to the orchestrator. "
                "Either set BRIDGE_TOKEN (orchestrator mints one at "
                "provision) or unset ORCHESTRATOR_WS_URL to idle locally."
            ),
        )
        return 2
    if settings.orchestrator_ws_url and not settings.sandbox_id:
        get_logger("bridge.startup").error(
            "bridge.config.missing_sandbox_id",
            hint="ORCHESTRATOR_WS_URL requires SANDBOX_ID to build the WSS path.",
        )
        return 2

    get_logger("bridge.startup").info(
        "bridge.started",
        bridge_version=BRIDGE_VERSION,
        cli_version=baked_cli_version(),
        claude_auth_mode=settings.claude_auth_mode,
        bridge_transport=settings.bridge_transport,
        orchestrator_ws_url=settings.orchestrator_ws_url or "(unset)",
        listen_port=settings.bridge_listen_port,
    )
    try:
        if settings.bridge_transport == "service_proxy":
            asyncio.run(_run_listener(settings))
        elif settings.orchestrator_ws_url:
            asyncio.run(_run_dialer(settings))
        else:
            asyncio.run(_idle_loop(settings))
    except KeyboardInterrupt:
        return 0
    return 0


async def _run_listener(settings: BridgeSettings) -> None:
    """Slice 8 service_proxy: bind a TCP server on `BRIDGE_LISTEN_PORT`
    and let the orchestrator dial in via Sprites' `WSS .../proxy`. No
    outbound connection from the bridge — the orchestrator owns the
    connection lifecycle."""
    from bridge.tcp_server import run_tcp_server

    credentials = _build_credentials(settings.claude_auth_mode)
    # Sprites' /proxy WSS resolves `localhost` to the sandbox's
    # internal interface (10.0.0.1, not 127.0.0.1). Bind to 0.0.0.0
    # so both loopback (local exec) and proxy traffic reach us.
    await run_tcp_server(
        host="0.0.0.0",  # noqa: S104 — sandbox is single-tenant; orchestrator owns access
        port=settings.bridge_listen_port,
        work_root=settings.work_root,
        credentials=credentials,
        max_live_chats=settings.max_live_chats_per_sandbox,
    )


if __name__ == "__main__":
    sys.exit(main())
