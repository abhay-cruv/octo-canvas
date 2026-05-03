"""Application-level layer over `SandboxProvider`.

Encapsulates the v1 routing rule "one running sandbox per user" and the
state-machine for our sandbox doc. The provider interface is opaque — this
layer never reaches into `provider_handle.payload`.

State machine (see [slice4.md §5](../../../../docs/slice/slice4.md)):

    none-doc → POST /api/sandboxes → provisioning
    provisioning → provider.create succeeds → cold | warm | running
    provisioning → provider.create fails → failed

    cold | warm | running → POST .../wake → running (force-warm via no-op exec)
    cold | warm | running → POST .../reset → resetting → provisioning → ...
    cold | warm | running → POST .../destroy → destroyed
    failed → reset → resetting → provisioning → ...
    failed → destroy → destroyed

Sprites auto-hibernates after idle. We resync the live status from the
provider via `refresh_status` (called from routes that read state).

Mongo is the source of truth. Redis is a hot cache only — never read sandbox
state from Redis as primary in this slice. Slice 5a's WS hot path will read
from Redis for sticky-routing decisions.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from beanie import PydanticObjectId
from db import mongo
from db.models import Sandbox
from sandbox_provider import SandboxHandle, SandboxProvider, SpritesError
from shared_models.sandbox import SandboxStatus

if TYPE_CHECKING:
    from redis.asyncio.client import Redis

_logger = structlog.get_logger("sandbox_manager")

# Statuses from which the corresponding action is legal. The route layer
# maps violations to HTTP 409. Keep these in lock-step with the table in
# [slice4.md §5](../../../../docs/slice/slice4.md).
_ALIVE: tuple[SandboxStatus, ...] = ("cold", "warm", "running")
_WAKE_FROM: tuple[SandboxStatus, ...] = _ALIVE
_PAUSE_FROM: tuple[SandboxStatus, ...] = _ALIVE  # pause on cold is a no-op
_RESET_FROM: tuple[SandboxStatus, ...] = (*_ALIVE, "failed")
_DESTROY_FROM: tuple[SandboxStatus, ...] = (*_ALIVE, "failed", "provisioning")


class IllegalSandboxTransitionError(Exception):
    """Raised when a state transition is rejected by the matrix. Routes map
    this to HTTP 409."""

    def __init__(self, from_status: SandboxStatus, action: str) -> None:
        super().__init__(f"cannot {action} a sandbox in status {from_status!r}")
        self.from_status = from_status
        self.action = action


def _now() -> datetime:
    return datetime.now(UTC)


def _handle_of(sandbox: Sandbox) -> SandboxHandle:
    """Reconstruct the provider handle from persisted fields."""
    return SandboxHandle(
        provider=sandbox.provider_name,
        payload=dict(sandbox.provider_handle),
    )


@dataclass(frozen=True)
class BridgeRuntimeConfig:
    """Slice 7 — values the reconciler's `installing_bridge` phase needs
    when it launches the bridge daemon inside the sprite. Sprites is
    already a VM, so there is no image bake; the reconciler installs
    the `claude` CLI + bridge wheel + nvm/pyenv/rbenv via `exec_oneshot`
    and launches the daemon with these env vars overlaid.

    **The real Anthropic API key never enters the sprite.** `env_for(...)`
    emits `ANTHROPIC_BASE_URL` pointing at the orchestrator's
    `/api/_internal/anthropic-proxy/<sandbox_id>` route (slice 8) and
    `ANTHROPIC_API_KEY=<bridge_token>` — a sandbox-scoped synthetic
    token only valid through our proxy. The proxy validates the token
    against `Sandbox.bridge_token_hash` and forwards to api.anthropic.com
    with the real key from the orchestrator's env. The user has terminal
    + agent-Bash access inside the sprite, so anything readable from
    process env / `/proc/<pid>/environ` is presumed leaked — only the
    proxy approach is safe.

    `_anthropic_api_key` stays on the dataclass so the proxy route
    (server-side) can read it. The leading underscore + the `__repr__`
    override below ensure it never appears in logs.
    """

    orchestrator_base_url: str
    # Pydantic SecretStr from the orchestrator's `Settings`; converted
    # to plain str only by the proxy route, never by anything that
    # serializes to a sprite.
    _anthropic_api_key: str = ""
    claude_auth_mode: str = "platform_api_key"
    max_live_chats_per_sandbox: int = 5
    idle_after_disconnect_s: int = 300
    # `dial_back` (legacy WSS-out from sprite) or `service_proxy`
    # (Sprites Service + proxy WSS in). Affects which env vars we
    # emit and which reconciler launch path runs.
    transport: str = "dial_back"
    # TCP port the bridge listens on inside the sprite when
    # `transport == "service_proxy"`. Ignored in dial_back mode.
    listen_port: int = 9300

    def env_for(self, *, sandbox_id: str, bridge_token: str) -> dict[str, str]:
        """Build the env-var overlay applied at bridge-launch time.

        `ORCHESTRATOR_WS_URL` / `ANTHROPIC_BASE_URL` may resolve to
        empty strings in dev (no public URL configured); the bridge
        tolerates this in slice 7 by idling. Slice 8 will require them.

        The returned dict NEVER contains the real `_anthropic_api_key`.

        Anthropic env-var design (verified 2026-05; passes forward to
        slice 8's proxy implementation):

        - `CLAUDE_CODE_API_BASE_URL` is the *priority* env var the
          `claude` CLI v2.1.118 checks first. It falls back to
          `ANTHROPIC_BASE_URL`, then `api.anthropic.com`. We set
          BOTH because `ANTHROPIC_BASE_URL` alone has a known bug
          where the CLI's interactive mode ignored it
          (anthropics/claude-code#36998); setting the higher-
          priority var hedges against future regressions.
        - `ANTHROPIC_AUTH_TOKEN` (Bearer mode) is what proxies use,
          per the LiteLLM convention. The CLI sends it as
          `Authorization: Bearer <token>`. Takes priority over
          `ANTHROPIC_API_KEY` when both are set, so we deliberately
          omit `ANTHROPIC_API_KEY` to keep the auth shape
          unambiguous.

        The `bridge_token` is the per-sandbox synthetic token —
        readable from sprite env / agent's Bash tool, but only
        valid against our proxy. The proxy validates the SHA-256
        against `Sandbox.bridge_token_hash` and swaps in the real
        `_anthropic_api_key` from `BridgeRuntimeConfig` (held only
        on the orchestrator, never piped).
        """
        base = (self.orchestrator_base_url or "").rstrip("/")
        ws_url = ""
        proxy_base = ""
        if base:
            ws_url = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
            ws_url = f"{ws_url}/ws/bridge/{sandbox_id}"
            proxy_base = f"{base}/api/_internal/anthropic-proxy/{sandbox_id}"
        env: dict[str, str] = {
            "BRIDGE_TOKEN": bridge_token,
            # Always present — even in service_proxy mode the bridge
            # surfaces its own sandbox id in logs / errors.
            "SANDBOX_ID": sandbox_id,
            "CLAUDE_AUTH_MODE": self.claude_auth_mode,
            "MAX_LIVE_CHATS_PER_SANDBOX": str(self.max_live_chats_per_sandbox),
            "IDLE_AFTER_DISCONNECT_S": str(self.idle_after_disconnect_s),
            # Priority var (CLI v2.1.118 checks this first) — hedge
            # against the interactive-mode regression where
            # `ANTHROPIC_BASE_URL` alone got ignored.
            "CLAUDE_CODE_API_BASE_URL": proxy_base,
            "ANTHROPIC_BASE_URL": proxy_base,
            # Bearer-mode auth: the CLI sends
            # `Authorization: Bearer <bridge_token>`. The proxy
            # validates this header (NOT `x-api-key`) and swaps in
            # the real key as `x-api-key` for the upstream call.
            "ANTHROPIC_AUTH_TOKEN": bridge_token,
            "BRIDGE_TRANSPORT": self.transport,
        }
        if self.transport == "dial_back":
            # Legacy: bridge dials orchestrator WSS. Needs the public
            # URL so it knows where to call home.
            env["ORCHESTRATOR_WS_URL"] = ws_url
        else:
            # service_proxy: bridge listens on TCP, orchestrator dials
            # in via Sprites' /proxy WSS. No outbound URL required.
            env["BRIDGE_LISTEN_PORT"] = str(self.listen_port)
        return env

    def __repr__(self) -> str:
        # Default dataclass repr would print the secret. Mask it.
        return (
            f"BridgeRuntimeConfig(orchestrator_base_url={self.orchestrator_base_url!r}, "
            f"_anthropic_api_key={'***' if self._anthropic_api_key else ''!r}, "
            f"claude_auth_mode={self.claude_auth_mode!r}, "
            f"max_live_chats_per_sandbox={self.max_live_chats_per_sandbox}, "
            f"idle_after_disconnect_s={self.idle_after_disconnect_s})"
        )


async def _clear_runtime_install_state(sandbox_id: PydanticObjectId | None) -> None:
    """Slice 7: clear `Repo.runtime_install_error` + `runtimes_installed_at`
    on every Repo bound to this sandbox so the dashboard "Agent setup"
    banner doesn't show stale state after a reset/destroy. Reconcile
    re-populates them on the next pass.

    Uses raw `mongo.repos.update_many` because Beanie's `find().update()`
    chain silently no-ops in some configurations — the slice-5b lesson
    that's documented in [agent_context.md](../../../../docs/agent_context.md).
    """
    if sandbox_id is None:
        return
    await mongo.repos.update_many(
        {"sandbox_id": sandbox_id},
        {"$set": {"runtime_install_error": None, "runtimes_installed_at": None}},
    )


def _hash_bridge_token(token: str) -> str:
    """SHA-256 hex of the plaintext bridge token. Persisted on the
    Sandbox doc; the bridge presents the plaintext at the slice-8 WSS
    handshake and the orchestrator hashes + compares."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_bridge_token() -> str:
    """Fresh URL-safe token (~256 bits). Use at bridge-launch time."""
    return secrets.token_urlsafe(32)


class SandboxManager:
    def __init__(
        self,
        provider: SandboxProvider,
        redis: "Redis | None",
    ) -> None:
        self._provider = provider
        self._redis = redis

    @property
    def provider_name(self) -> str:
        return self._provider.name

    # ── Lookup ────────────────────────────────────────────────────────────

    async def get_or_create(self, user_id: PydanticObjectId) -> Sandbox:
        """Return the user's most-recent non-`destroyed` sandbox, creating
        one with `status='provisioning'` AND calling `provider.create()` if
        none exists. Idempotent on the second call (returns the existing
        doc rather than provisioning a second sprite)."""
        existing = (
            await Sandbox.find(
                Sandbox.user_id == user_id,
                {"status": {"$ne": "destroyed"}},
            )
            .sort("-created_at")
            .first_or_none()
        )
        if existing is not None:
            return existing
        doc = Sandbox(user_id=user_id, provider_name=self._provider.name)
        await doc.create()
        _logger.info("sandbox.created", sandbox_id=str(doc.id), user_id=str(user_id))
        return await self._provision(doc)

    async def list_for_user(self, user_id: PydanticObjectId) -> list[Sandbox]:
        return await Sandbox.find(Sandbox.user_id == user_id).sort("-created_at").to_list()

    async def refresh_status(self, sandbox: Sandbox) -> Sandbox:
        """Resync live status from the provider. No-ops for sandboxes that
        aren't currently alive (provisioning / resetting / destroyed / failed
        all stay as-is — they're owned by manager transitions)."""
        if sandbox.status not in _ALIVE:
            return sandbox
        try:
            state = await self._provider.status(_handle_of(sandbox))
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)
        sandbox.status = state.status
        sandbox.public_url = state.public_url
        # Once Sprites confirms the sprite has actually idled, drop the
        # "pausing" banner.
        if sandbox.activity == "pausing" and sandbox.status == "cold":
            sandbox.activity = None
            sandbox.activity_detail = None
        await sandbox.save()
        await self._redis_write(sandbox)
        return sandbox

    # ── Transitions ───────────────────────────────────────────────────────

    async def wake(self, sandbox: Sandbox) -> Sandbox:
        if sandbox.status not in _WAKE_FROM:
            raise IllegalSandboxTransitionError(sandbox.status, "wake")
        try:
            state = await self._provider.wake(_handle_of(sandbox))
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)
        sandbox.status = state.status
        sandbox.public_url = state.public_url
        sandbox.last_active_at = _now()
        await sandbox.save()
        await self._redis_write(sandbox)
        _logger.info("sandbox.waked", sandbox_id=str(sandbox.id), status=sandbox.status)
        return sandbox

    async def pause(self, sandbox: Sandbox) -> Sandbox:
        """Force the sandbox to release compute. Sprites has no explicit
        force-pause API; the provider implementation kills active exec
        sessions so Sprites' idle timer can fire. Returned status may still
        be `warm` for a few seconds before going cold — the route
        schedules a delayed re-sync to converge the doc to `cold`."""
        if sandbox.status == "cold":
            return sandbox  # idempotent — already paused
        if sandbox.status not in _PAUSE_FROM:
            raise IllegalSandboxTransitionError(sandbox.status, "pause")
        # Set the activity banner *before* the provider call so the FE's
        # next poll already shows "pausing…" rather than a misleading
        # "warm".
        sandbox.activity = "pausing"
        sandbox.activity_detail = None
        await sandbox.save()
        try:
            state = await self._provider.pause(_handle_of(sandbox))
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)
        sandbox.status = state.status
        sandbox.public_url = state.public_url
        if sandbox.status == "cold":
            sandbox.activity = None
        await sandbox.save()
        await self._redis_write(sandbox)
        _logger.info("sandbox.paused", sandbox_id=str(sandbox.id), status=sandbox.status)
        return sandbox

    async def reset(self, sandbox: Sandbox) -> Sandbox:
        """Wipe `/work` on the sprite and let reconciliation re-clone.

        We don't destroy the sprite — that's wasteful and slow, and
        loses the git config + apt cache + anything else the user has
        installed. We also don't restore from checkpoint — that
        preserves the repos verbatim, which makes Reset feel like a
        no-op. Middle ground: `rm -rf /work` via exec (Sprites' own
        fs/delete refuses to delete the work-root with 400), leave the
        rest of the sprite alone, kick reconcile to re-clone fresh.

        Same `Sandbox._id`, same `provider_handle`, `reset_count`
        incremented, `last_reset_at` updated. If the sprite is cold,
        we wake it first so the wipe + reconcile have somewhere to
        run."""
        if sandbox.status not in _RESET_FROM:
            raise IllegalSandboxTransitionError(sandbox.status, "reset")

        was_cold = sandbox.status == "cold"
        was_failed = sandbox.status == "failed"
        sandbox.status = "resetting"
        await sandbox.save()
        await self._redis_write(sandbox)

        # Failed sandboxes have a broken sprite — wiping /work won't
        # recover them. Fall back to destroy+create so the user gets a
        # working sandbox.
        if was_failed:
            return await self._reset_via_recreate(sandbox)

        # Wake if it was cold so fs_delete + reconcile actually run.
        if was_cold:
            try:
                woken = await self._provider.wake(_handle_of(sandbox))
                sandbox.status = woken.status
                sandbox.public_url = woken.public_url
            except SpritesError as exc:
                _logger.warning(
                    "sandbox.reset.wake_failed",
                    sandbox_id=str(sandbox.id),
                    error=str(exc),
                )

        # Wipe everything under `/work`. We can't use `fs_delete /work`
        # directly — Sprites' fs/delete returns 400 for the work-root
        # path itself. `rm -rf /work && mkdir -p /work` via exec is
        # reliable: idempotent if the dir doesn't exist yet, and the
        # next reconcile pass treats `/work` as fresh-empty.
        try:
            wipe = await self._provider.exec_oneshot(
                _handle_of(sandbox),
                ["sh", "-c", "rm -rf /work && mkdir -p /work"],
                env={},
                cwd="/",
                timeout_s=60,
            )
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)
        if wipe.exit_code != 0:
            _logger.warning(
                "sandbox.reset.wipe_nonzero",
                sandbox_id=str(sandbox.id),
                exit_code=wipe.exit_code,
                stderr=wipe.stderr[-500:],
            )

        # Pull live status — the wipe doesn't change lifecycle but the
        # sprite may have shifted (e.g., still warming after wake).
        try:
            state = await self._provider.status(_handle_of(sandbox))
            sandbox.status = state.status
            sandbox.public_url = state.public_url
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)

        sandbox.reset_count += 1
        sandbox.last_reset_at = _now()
        sandbox.last_active_at = _now()
        sandbox.failure_reason = None
        # /work is gone, so the previous checkpoint no longer reflects
        # current state. Drop it; reconcile takes a fresh one.
        sandbox.clean_checkpoint_id = None
        await sandbox.save()
        await self._redis_write(sandbox)
        # Reset wipes /work but leaves /usr/local/{nvm,pyenv,rbenv,cargo,
        # rustup,go-versions} intact (slice 5b's design). The reconciler's
        # `installing_runtimes` phase is idempotent, so repos that were
        # already "Installed: …" stay accurate after reset — keep the
        # banner. We only clear runtime-install state when the sprite
        # itself is destroyed (see `destroy()` and `_reset_via_recreate`).
        _logger.info(
            "sandbox.reset.workdir_wiped",
            sandbox_id=str(sandbox.id),
            status=sandbox.status,
        )
        return sandbox

    async def _reset_via_recreate(self, sandbox: Sandbox) -> Sandbox:
        """Used only for `failed` sandboxes where the sprite itself is
        broken and a `/work` wipe wouldn't recover it. Destroy and
        provision a fresh one with the same `Sandbox._id`."""
        try:
            await self._provider.destroy(_handle_of(sandbox))
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)
        sandbox.provider_handle = {}
        sandbox.public_url = None
        sandbox.reset_count += 1
        sandbox.last_reset_at = _now()
        sandbox.failure_reason = None
        sandbox.status = "provisioning"
        sandbox.clean_checkpoint_id = None
        sandbox.git_configured_token_fp = None
        # Sprite is gone, so the bridge prerequisites need reinstalling
        # too — clear the fingerprint so the next reconcile re-runs
        # `installing_bridge` from scratch.
        sandbox.bridge_setup_fingerprint = None
        await sandbox.save()
        await _clear_runtime_install_state(sandbox.id)
        return await self._provision(sandbox)

    async def destroy(self, sandbox: Sandbox) -> Sandbox:
        if sandbox.status == "destroyed":
            return sandbox  # idempotent
        if sandbox.status not in _DESTROY_FROM:
            raise IllegalSandboxTransitionError(sandbox.status, "destroy")

        # Best-effort destroy at the provider. If we never got past
        # `provisioning` (provider.create raised but flushed to mongo via
        # _mark_failed), there's no handle to clean up.
        if sandbox.provider_handle:
            try:
                await self._provider.destroy(_handle_of(sandbox))
            except SpritesError as exc:
                # Still mark our doc destroyed; the operator can clean up
                # the orphan sprite via Sprites' dashboard.
                _logger.warning(
                    "sandbox.destroy.provider_failed",
                    sandbox_id=str(sandbox.id),
                    error=str(exc),
                )

        sandbox.status = "destroyed"
        sandbox.destroyed_at = _now()
        sandbox.public_url = None
        await sandbox.save()
        await self._redis_clear(sandbox)
        # Drop runtime-install banners on the connected Repos —
        # there's no sandbox to be installed in anymore. Repo docs
        # themselves stay (slice 2's connect/disconnect lifecycle).
        await _clear_runtime_install_state(sandbox.id)
        _logger.info("sandbox.destroyed", sandbox_id=str(sandbox.id))
        return sandbox

    # ── Internals ─────────────────────────────────────────────────────────

    async def _provision(self, sandbox: Sandbox) -> Sandbox:
        if sandbox.id is None:
            raise RuntimeError("sandbox.id is None")
        sandbox.status = "provisioning"
        sandbox.failure_reason = None
        await sandbox.save()
        try:
            handle = await self._provider.create(
                sandbox_id=str(sandbox.id),
                labels=[f"user:{sandbox.user_id}"],
            )
        except SpritesError as exc:
            return await self._mark_failed(sandbox, exc)

        # Pull the live state to get the public URL + initial status.
        try:
            state = await self._provider.status(handle)
        except SpritesError as exc:
            # Created but couldn't read status — store the handle so destroy
            # can clean up, then mark failed.
            sandbox.provider_handle = dict(handle.payload)
            await sandbox.save()
            return await self._mark_failed(sandbox, exc)

        sandbox.provider_handle = dict(handle.payload)
        sandbox.status = state.status
        sandbox.public_url = state.public_url
        sandbox.spawned_at = _now()
        sandbox.last_active_at = _now()
        await sandbox.save()
        await self._redis_write(sandbox)
        _logger.info(
            "sandbox.provisioned",
            sandbox_id=str(sandbox.id),
            provider=sandbox.provider_name,
            status=sandbox.status,
        )
        return sandbox

    async def _mark_failed(self, sandbox: Sandbox, exc: SpritesError) -> Sandbox:
        sandbox.status = "failed"
        sandbox.failure_reason = str(exc)[:500]
        sandbox.public_url = None
        await sandbox.save()
        await self._redis_clear(sandbox)
        _logger.warning(
            "sandbox.failed",
            sandbox_id=str(sandbox.id),
            error=sandbox.failure_reason,
        )
        return sandbox

    async def _redis_write(self, sandbox: Sandbox) -> None:
        if self._redis is None:
            return
        key = f"sandbox:{sandbox.id}"
        try:
            await self._redis.hset(  # type: ignore[misc]
                key,
                mapping={
                    "status": sandbox.status,
                    "public_url": sandbox.public_url or "",
                    "last_active_at": (
                        sandbox.last_active_at.isoformat() if sandbox.last_active_at else ""
                    ),
                },
            )
            await self._redis.expire(key, 90)
        except Exception as exc:
            _logger.warning(
                "sandbox.redis_write_failed",
                sandbox_id=str(sandbox.id),
                error=str(exc),
            )

    async def _redis_clear(self, sandbox: Sandbox) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.delete(f"sandbox:{sandbox.id}")
        except Exception as exc:
            _logger.warning(
                "sandbox.redis_clear_failed",
                sandbox_id=str(sandbox.id),
                error=str(exc),
            )
