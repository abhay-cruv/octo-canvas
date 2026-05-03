from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from db import mongo
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sandbox_provider import SpritesProvider

from .lib.env import settings
from .lib.logger import logger
from .lib.provider_factory import build_sandbox_provider
from .lib.redis_client import redis_client
from .routes import (
    anthropic_proxy,
    auth,
    chats,
    internal,
    me,
    repos,
    sandbox,
    sandbox_bridge,
    sandbox_fs,
    sandbox_git,
)
from beanie import PydanticObjectId
from db.models import Sandbox

from .services.bridge_owner import BridgeOwner
from .services.bridge_session import BridgeSessionFleet
from .services.event_store import append_chat_event
from .services.fs_watcher import FsWatcher
from .services.reconciliation import Reconciler
from .services.sandbox_manager import BridgeRuntimeConfig, SandboxManager
from .services.user_agent.loop import UserAgentLoop
from .ws import bridge as ws_bridge
from .ws import bridge_debug as ws_bridge_debug
from .ws import chats as ws_chats
from .ws import fs_watch as ws_fs_watch
from .ws import pty as ws_pty
from .ws import web as ws_web
from .ws.chat_fanout import ChatFanout
from .ws.task_fanout import TaskFanout


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    await mongo.connect(settings.mongodb_uri)

    # Redis is optional in slice 4 — failures are logged but don't kill the
    # orchestrator; the manager's redis_write helpers tolerate `None`.
    redis_handle = None
    try:
        await redis_client.connect(settings.redis_url)
        redis_handle = redis_client.client
    except Exception as exc:
        logger.warning("redis.connect_failed", url=settings.redis_url, error=str(exc))

    provider = build_sandbox_provider()
    bridge_config = BridgeRuntimeConfig(
        orchestrator_base_url=settings.orchestrator_base_url,
        # SecretStr → plain str only here, used by the slice-8
        # Anthropic proxy route. NEVER goes into the bridge env.
        _anthropic_api_key=settings.anthropic_api_key.get_secret_value(),
        claude_auth_mode=settings.claude_auth_mode,
        max_live_chats_per_sandbox=settings.bridge_max_live_chats_per_sandbox,
        idle_after_disconnect_s=settings.bridge_idle_after_disconnect_s,
        transport=settings.bridge_transport,
        listen_port=settings.bridge_listen_port,
    )
    manager = SandboxManager(provider=provider, redis=redis_handle)
    app.state.sandbox_manager = manager
    app.state.sandbox_provider = provider
    app.state.bridge_config = bridge_config
    # `reconciler` is constructed below once we know whether the
    # service_proxy fleet exists — it gets injected so the bridge-launch
    # branch in `_run` calls the right path.
    app.state.redis_handle = redis_handle

    # Slice 8 §4: shared httpx.AsyncClient for the Anthropic reverse
    # proxy. HTTP/2 keeps Anthropic's streaming connections multiplexed.
    # `read=600s` covers long message-stream responses; `connect=10s`
    # fails fast on dead routes; `pool=10s` mirrors the upstream's
    # expectations so we don't hold a borrowed connection forever.
    app.state.anthropic_proxy_client = httpx.AsyncClient(
        http2=True,
        timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0),
    )
    fs_watcher = FsWatcher(provider, redis=redis_handle)
    await fs_watcher.start()
    app.state.fs_watcher = fs_watcher

    # TaskFanout (slice 5a) only spins up if Redis is connected. Without
    # Redis, single-instance event delivery still works via direct
    # in-process dispatch — but the WS endpoint will error on subscribe.
    fanout: TaskFanout | None = None
    if redis_handle is not None:
        fanout = TaskFanout(redis_handle)
        await fanout.start()
    app.state.task_fanout = fanout

    # Slice 8 Phase 8b: chat-keyed pub/sub fanout for `/ws/web/chats/{id}`.
    chat_fanout: ChatFanout | None = None
    if redis_handle is not None:
        chat_fanout = ChatFanout(redis_handle)
        await chat_fanout.start()
    app.state.chat_fanout = chat_fanout

    # Slice 8: bridge transport. Two interchangeable implementations
    # behind the same `.send(sandbox_id, frame)` shape:
    #   - dial_back (legacy): bridge dials orchestrator WSS; routed via
    #     Redis pub/sub by `BridgeOwner`.
    #   - service_proxy (new): bridge runs as a Sprites Service; the
    #     orchestrator dials in via Sprites' /proxy WSS via
    #     `BridgeSessionFleet`.
    bridge_owner: BridgeOwner | BridgeSessionFleet
    if settings.bridge_transport == "service_proxy":
        async def _bridge_event(
            chat_id: PydanticObjectId,
            data: dict[str, object],
            frame: object,
        ) -> None:
            from db.models import Chat as _Chat
            from db.models import User as _User

            chat = await _Chat.get(chat_id)
            if chat is None:
                return
            user = await _User.get(chat.user_id)
            user_agent_enabled = bool(user and user.user_agent_enabled)
            frame_session_id = getattr(frame, "claude_session_id", None)
            claude_session_id = frame_session_id or chat.claude_session_id
            # Persist the FIRST claude_session_id we see for this chat
            # so subsequent events (which arrive WITHOUT session_id on
            # the wire — only `chat.started` / `result` carry one)
            # land in the same seq space. Without this, every bridge
            # restart spawned a fresh SDK client → new session_id →
            # events split across multiple seq spaces → FE replay sees
            # bunched turn_ends after turn 1 because mongo sorts by
            # seq and seq=2 has a `result` row from each session.
            if (
                frame_session_id
                and chat.claude_session_id != frame_session_id
            ):
                chat.claude_session_id = frame_session_id
                await chat.save()
                claude_session_id = frame_session_id
            await append_chat_event(
                chat_id,
                frame,  # type: ignore[arg-type]
                claude_session_id=claude_session_id,
                redis=redis_handle,
                user_agent_enabled=user_agent_enabled,
            )
            # Mirror dial-back behavior: any event flips the latest
            # queued turn → running.
            from db.models import ChatTurn as _ChatTurn

            latest = (
                await _ChatTurn.find(_ChatTurn.chat_id == chat_id)
                .sort(-_ChatTurn.started_at)  # type: ignore[arg-type]
                .limit(1)
                .to_list()
            )
            if latest and latest[0].status == "queued":
                latest[0].status = "running"
                await latest[0].save()

        def _bridge_env_for(sandbox: Sandbox) -> dict[str, str]:
            from orchestrator.services.sandbox_manager import mint_bridge_token

            token = mint_bridge_token()
            return bridge_config.env_for(
                sandbox_id=str(sandbox.id), bridge_token=token
            )

        fleet = BridgeSessionFleet(
            provider=provider,
            listen_port=settings.bridge_listen_port,
            on_event=_bridge_event,
            bridge_env_for=_bridge_env_for,
        )
        await fleet.start()
        bridge_owner = fleet
        app.state.reconciler = Reconciler(
            provider, bridge_config=bridge_config, bridge_session_fleet=fleet
        )
    else:
        # Cross-instance bridge ownership singleton. Tolerates a missing
        # Redis (single-instance dev path).
        bridge_owner = BridgeOwner(redis=redis_handle)
        await bridge_owner.start()
        app.state.reconciler = Reconciler(provider, bridge_config=bridge_config)
    app.state.bridge_owner = bridge_owner

    # Slice 8 Phase 8b: BE user-agent loop subscribes to `chat:*:ua`
    # and emits `UserAgentSuggestion` + auto-reply timers. Tolerates
    # missing Redis (no-op without it — passthrough chat path still
    # works).
    user_agent_loop = UserAgentLoop(
        redis=redis_handle,
        bridge_owner=bridge_owner,
        anthropic_api_key=settings.anthropic_api_key.get_secret_value(),
    )
    await user_agent_loop.start()
    app.state.user_agent_loop = user_agent_loop

    # Slice 7: clear any stale `activity` / `activity_started_at` /
    # `last_reconcile_error` left over from a prior process that died
    # mid-reconcile (uvicorn reload, OOM, deploy). The end-of-pass
    # cleanup didn't get to run, so the dashboard would otherwise show
    # a stuck banner with hours of fake elapsed time. Touches only live
    # sandboxes (no point on `destroyed`/`failed`).
    try:
        cleared = await mongo.sandboxes.update_many(
            {
                "status": {"$in": ["cold", "warm", "running"]},
                "activity": {"$ne": None},
            },
            {
                "$set": {
                    "activity": None,
                    "activity_detail": None,
                    "activity_started_at": None,
                    "last_reconcile_error": None,
                }
            },
        )
        if cleared.modified_count:
            logger.info(
                "orchestrator.cleared_stale_activity",
                count=cleared.modified_count,
            )
    except Exception as exc:
        logger.warning("orchestrator.clear_stale_activity_failed", error=str(exc))

    logger.info("orchestrator.startup_complete")

    try:
        yield
    finally:
        try:
            await fs_watcher.stop()
        except Exception as exc:
            logger.warning("fs_watcher.stop_failed", error=str(exc))

        if fanout is not None:
            try:
                await fanout.stop()
            except Exception as exc:
                logger.warning("task_fanout.stop_failed", error=str(exc))

        if chat_fanout is not None:
            try:
                await chat_fanout.stop()
            except Exception as exc:
                logger.warning("chat_fanout.stop_failed", error=str(exc))

        try:
            await user_agent_loop.stop()
        except Exception as exc:
            logger.warning("user_agent_loop.stop_failed", error=str(exc))

        try:
            await bridge_owner.stop()
        except Exception as exc:
            logger.warning("bridge_owner.stop_failed", error=str(exc))

        if isinstance(provider, SpritesProvider):
            try:
                await provider.aclose()
            except Exception as exc:
                logger.warning("provider.close_failed", error=str(exc))

        try:
            await app.state.anthropic_proxy_client.aclose()
        except Exception as exc:
            logger.warning("anthropic_proxy_client.close_failed", error=str(exc))

        await redis_client.disconnect()
        await mongo.disconnect()
        logger.info("orchestrator.shutdown_complete")


app = FastAPI(title="octo-canvas orchestrator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_base_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(me.router, prefix="/api", tags=["me"])
app.include_router(repos.router, prefix="/api/repos", tags=["repos"])
app.include_router(sandbox.router, prefix="/api/sandboxes", tags=["sandboxes"])
app.include_router(sandbox_fs.router, prefix="/api/sandboxes", tags=["sandbox-fs"])
app.include_router(sandbox_git.router, prefix="/api/sandboxes", tags=["sandbox-git"])
app.include_router(
    sandbox_bridge.router, prefix="/api/sandboxes", tags=["sandbox-bridge"]
)
app.include_router(chats.router, prefix="/api/chats", tags=["chats"])
app.include_router(ws_web.router, tags=["ws"])
app.include_router(ws_pty.router, tags=["ws-pty"])
app.include_router(ws_fs_watch.router, tags=["ws-fs-watch"])
app.include_router(ws_bridge.router, tags=["ws-bridge"])
app.include_router(ws_bridge_debug.router, tags=["ws-bridge-debug"])
app.include_router(ws_chats.router, tags=["ws-chats"])

# Slice 8 §4: Anthropic reverse proxy. Production-required (it's how the
# bridge talks to Anthropic without ever holding the real key) — NOT
# gated by `allow_internal_endpoints`. Auth is per-request via the
# bridge's bearer token vs `Sandbox.bridge_token_hash`.
app.include_router(
    anthropic_proxy.router, prefix="/api/_internal", tags=["anthropic-proxy"]
)

if settings.allow_internal_endpoints:
    app.include_router(internal.router, prefix="/api/_internal", tags=["internal"])


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness + Mongo reachability. 503 if Mongo is down so load balancers
    drop us out of rotation instead of accepting requests we can't serve."""
    mongo_ok = await mongo.ping()
    if not mongo_ok:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "mongo": False},
        )
    return JSONResponse(content={"status": "ok", "mongo": True})
