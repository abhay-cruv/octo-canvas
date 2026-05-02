"""Per-sandbox reconciliation — slice 5b.

Diffs the sandbox's `/work` listing against the `Repo` rows bound to it,
issues clone/remove ops to converge, runs `apt-get install` for the union
of `system_packages` from every repo's introspection, and (if anything
mutated) snapshots a fresh `clean` checkpoint so Reset is millisecond-fast.

Event-driven only — invoked from sandbox/repo routes after the relevant
state change. No background timer in slice 5b.

Per-sandbox `asyncio.Lock` ensures serial execution: two concurrent
triggers (e.g. simultaneous connect-repo + wake) are serialized; the
second waits for the first then runs another pass against fresh state.
Mongo is canonical — the reconciler reads `Repo` rows and the sprite's
filesystem at the start of each pass and writes back at the end.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog
from beanie import PydanticObjectId
from db import mongo
from db.models import Repo, Sandbox, User
from sandbox_provider import SandboxHandle, SpritesError

if TYPE_CHECKING:
    from sandbox_provider import SandboxProvider

_logger = structlog.get_logger("reconciliation")

WORK_ROOT = "/work"
APT_TIMEOUT_S = 600
CLONE_TIMEOUT_S = 300

# Fixed-path git config + credentials. Decoupled from `$HOME` so we
# don't rely on env passthrough between exec calls being consistent —
# Sprites' exec sometimes drops/replaces env keys, which previously
# caused git_setup to write credentials under one HOME and clone to
# look under a different one. With `GIT_CONFIG_GLOBAL` pointing at a
# fixed file and the credential helper using an absolute path, every
# git invocation finds the same config and credentials.
GIT_CONFIG_PATH = "/etc/octo-canvas/gitconfig"
GIT_CRED_PATH = "/etc/octo-canvas/git-credentials"
GIT_ENV: dict[str, str] = {
    "GIT_CONFIG_GLOBAL": GIT_CONFIG_PATH,
    "GIT_TERMINAL_PROMPT": "0",
}


@dataclass
class ReconciliationResult:
    cloned: list[str] = field(default_factory=lambda: [])
    removed: list[str] = field(default_factory=lambda: [])
    failed: list[tuple[str, str]] = field(default_factory=lambda: [])
    apt_installed: list[str] = field(default_factory=lambda: [])
    checkpoint_taken: bool = False
    new_checkpoint_id: str | None = None
    skipped: bool = False
    skipped_reason: str | None = None


def _handle_of(sandbox: Sandbox) -> SandboxHandle:
    return SandboxHandle(
        provider=sandbox.provider_name,
        payload=dict(sandbox.provider_handle),
    )


# Per-sandbox lock map. Lives at module scope: per-process singleton, sized
# by the count of unique sandboxes ever reconciled by this orchestrator
# instance. Locks aren't reaped — they're cheap (one mutex per sandbox) and
# the alternative (cleanup on destroy) introduces a race.
_locks: dict[PydanticObjectId, asyncio.Lock] = {}


def _lock_for(sandbox_id: PydanticObjectId) -> asyncio.Lock:
    lock = _locks.get(sandbox_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[sandbox_id] = lock
    return lock


class Reconciler:
    """One per-orchestrator-process. Holds a `SandboxProvider` reference;
    routes pull this from `app.state.reconciler`."""

    def __init__(self, provider: SandboxProvider) -> None:
        self._provider = provider

    async def reconcile(self, sandbox_id: PydanticObjectId) -> ReconciliationResult:
        async with _lock_for(sandbox_id):
            try:
                return await self._run(sandbox_id)
            except Exception as exc:
                # Defensive: any unexpected exception (network timeout
                # not wrapped by the provider, schema decode error,
                # etc.) bails the run cleanly instead of leaving repos
                # stuck at `pending` forever. Mark every still-pending
                # / cloning repo for this sandbox as `failed` so the
                # FE stops polling and the user can retry via Wake.
                _logger.warning(
                    "reconcile.unexpected_error",
                    sandbox_id=str(sandbox_id),
                    error=str(exc)[:300],
                )
                await mongo.repos.update_many(
                    {
                        "sandbox_id": sandbox_id,
                        "clone_status": {"$in": ["pending", "cloning"]},
                    },
                    {
                        "$set": {
                            "clone_status": "failed",
                            "clone_error": f"reconcile aborted: {str(exc)[:200]}",
                        }
                    },
                )
                # Clear any in-flight activity banner.
                if sandbox_id in _locks:
                    await mongo.sandboxes.update_one(
                        {"_id": sandbox_id},
                        {"$set": {"activity": None, "activity_detail": None}},
                    )
                result = ReconciliationResult()
                result.skipped = True
                result.skipped_reason = f"error:{type(exc).__name__}"
                return result

    async def _run(self, sandbox_id: PydanticObjectId) -> ReconciliationResult:
        result = ReconciliationResult()
        sandbox = await Sandbox.get(sandbox_id)
        if sandbox is None or sandbox.status in ("destroyed", "failed"):
            result.skipped = True
            result.skipped_reason = (
                "sandbox_missing" if sandbox is None else f"sandbox_status:{sandbox.status}"
            )
            return result
        if sandbox.status in ("provisioning", "resetting"):
            result.skipped = True
            result.skipped_reason = f"sandbox_transient:{sandbox.status}"
            return result
        # Don't auto-warm a paused sandbox just to clone. The user
        # explicitly chose `cold`; reconciliation will run on the next
        # explicit wake.
        if sandbox.status == "cold":
            result.skipped = True
            result.skipped_reason = "sandbox_cold"
            return result

        # Claim any orphan repos owned by this user. Covers users who
        # provisioned before slice 5b shipped (the route's fresh-provision
        # bulk-bind only fires on the *first* provision call).
        await mongo.repos.update_many(
            {"user_id": sandbox.user_id, "sandbox_id": None},
            {"$set": {"sandbox_id": sandbox_id, "clone_status": "pending"}},
        )
        repos = await Repo.find(Repo.sandbox_id == sandbox_id).to_list()
        user = await User.get(sandbox.user_id)
        if user is None:
            result.skipped = True
            result.skipped_reason = "user_missing"
            return result

        # 1. Diff: what's on disk vs what should be. Two-level walk
        # because Repo.full_name = "<owner>/<repo>" and Sprites' fs_list
        # returns one level at a time. The mock returns full_name strings
        # directly for back-compat with our pre-real-fs tests, so we
        # accept either shape.
        on_disk: set[str] = set()
        try:
            top = await self._provider.fs_list(_handle_of(sandbox), WORK_ROOT)
        except SpritesError as exc:
            if not exc.retriable and "not found" in str(exc).lower():
                top = []
            else:
                raise
        for entry in top:
            if entry.kind != "dir":
                continue
            if "/" in entry.name:
                # Mock-style: "owner/repo" already.
                on_disk.add(entry.name)
                continue
            owner = entry.name
            try:
                sub = await self._provider.fs_list(_handle_of(sandbox), f"{WORK_ROOT}/{owner}")
            except SpritesError:
                continue
            for s in sub:
                if s.kind == "dir":
                    on_disk.add(f"{owner}/{s.name}")
        wanted = {r.full_name: r for r in repos}

        to_clone = [r for full_name, r in wanted.items() if full_name not in on_disk]
        to_remove = sorted(on_disk - set(wanted))
        mutated = False

        # Self-heal: any repo that's already on disk (e.g. after a
        # checkpoint-restore Reset) but whose Mongo `clone_status` says
        # otherwise — flip to `ready`. Without this, the FE shows
        # "pending" forever for repos that the fast-reset path already
        # restored from the checkpoint.
        for full_name, r in wanted.items():
            if full_name in on_disk and r.clone_status != "ready" and r.id is not None:
                await mongo.repos.update_one(
                    {"_id": r.id},
                    {
                        "$set": {
                            "clone_status": "ready",
                            "clone_path": f"{WORK_ROOT}/{full_name}",
                            "clone_error": None,
                        }
                    },
                )

        # 2a. One-time git setup. Writes ~/.gitconfig (identity) and
        # ~/.git-credentials (OAuth token) inside the sandbox so plain
        # `git clone https://github.com/...` works for the agent AND any
        # interactive shell session — no per-command auth flags needed.
        # Skipped when the configured token fingerprint matches the
        # user's current token, so this is essentially a no-op after the
        # first reconciliation pass.
        if to_clone:
            # Make sure `/work` exists before *anything* else cwds into
            # it. Fresh sprites don't have it.
            try:
                await self._provider.exec_oneshot(
                    _handle_of(sandbox),
                    ["mkdir", "-p", WORK_ROOT],
                    env={},
                    cwd="/",
                    timeout_s=15,
                )
            except SpritesError as exc:
                _logger.warning(
                    "reconcile.mkdir_work_failed",
                    sandbox_id=str(sandbox_id),
                    error=str(exc),
                )
            await _set_activity(sandbox, "configuring_git", None)
            await self._ensure_git_setup(sandbox, user)

        # 2b. apt install — once per pass, deduped union of every alive
        # repo's detected + override-merged system_packages. Skipped if empty.
        # `apt-get update` first — Sprites' base images often ship without
        # cached package lists, so `install` alone returns "Unable to
        # locate package …" or exits 1 with empty stderr.
        apt_pkgs = _merge_system_packages(repos)
        if apt_pkgs and to_clone:
            await _set_activity(sandbox, "installing_packages", ", ".join(apt_pkgs[:5]))
            try:
                upd = await self._provider.exec_oneshot(
                    _handle_of(sandbox),
                    # `sudo -n` so we don't hang on a password prompt if
                    # passwordless sudo isn't configured. dpkg requires
                    # root; Sprites exec runs unprivileged by default.
                    ["sudo", "-n", "apt-get", "update"],
                    env={"DEBIAN_FRONTEND": "noninteractive"},
                    cwd="/",
                    timeout_s=APT_TIMEOUT_S,
                )
                if upd.exit_code != 0:
                    _logger.warning(
                        "reconcile.apt_update_failed",
                        sandbox_id=str(sandbox_id),
                        exit_code=upd.exit_code,
                        stderr=upd.stderr[-500:],
                    )
                exec_result = await self._provider.exec_oneshot(
                    _handle_of(sandbox),
                    ["sudo", "-n", "apt-get", "install", "-y", *apt_pkgs],
                    env={"DEBIAN_FRONTEND": "noninteractive"},
                    cwd="/",
                    timeout_s=APT_TIMEOUT_S,
                )
                if exec_result.exit_code == 0:
                    result.apt_installed = list(apt_pkgs)
                else:
                    _logger.warning(
                        "reconcile.apt_install_failed",
                        sandbox_id=str(sandbox_id),
                        exit_code=exec_result.exit_code,
                        stderr=exec_result.stderr[-1000:],
                        stdout=exec_result.stdout[-500:],
                    )
            except SpritesError as exc:
                _logger.warning(
                    "reconcile.apt_install_error",
                    sandbox_id=str(sandbox_id),
                    error=str(exc),
                )

        # 3. Clones — serialized. Re-check sandbox status between clones
        # so a mid-flight pause/destroy stops the loop quickly instead of
        # plowing through all remaining repos.
        for repo in to_clone:
            await asyncio.sleep(0)  # cooperative cancellation point
            fresh = await Sandbox.get(sandbox_id)
            if fresh is None or fresh.status not in ("warm", "running"):
                _logger.info(
                    "reconcile.aborted",
                    sandbox_id=str(sandbox_id),
                    reason=f"status:{fresh.status if fresh else 'missing'}",
                )
                break
            await _set_activity(sandbox, "cloning", repo.full_name)
            ok = await self._clone_one(sandbox, repo, user.github_access_token)
            if ok:
                result.cloned.append(repo.full_name)
                mutated = True
            else:
                result.failed.append((repo.full_name, repo.clone_error or "unknown"))

        # 4. Removes — serialized.
        for full_name in to_remove:
            try:
                await self._provider.fs_delete(
                    _handle_of(sandbox),
                    f"{WORK_ROOT}/{full_name}",
                    recursive=True,
                )
                result.removed.append(full_name)
                mutated = True
            except SpritesError as exc:
                _logger.warning(
                    "reconcile.remove_failed",
                    sandbox_id=str(sandbox_id),
                    full_name=full_name,
                    error=str(exc),
                )

        # 5. Checkpoint only if mutated.
        if mutated:
            await _set_activity(sandbox, "checkpointing", None)
            try:
                ckpt = await self._provider.snapshot(
                    _handle_of(sandbox), comment=f"clean@{int(time.time())}"
                )
                sandbox.clean_checkpoint_id = str(ckpt)
                # Atomic field update for the same reason as
                # `_set_activity`: avoid clobbering concurrent destroy
                # / reset writes via a stale full-doc save.
                if sandbox.id is not None:
                    await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
                        {"$set": {"clean_checkpoint_id": str(ckpt)}}
                    )
                result.checkpoint_taken = True
                result.new_checkpoint_id = str(ckpt)
            except SpritesError as exc:
                _logger.warning(
                    "reconcile.snapshot_failed",
                    sandbox_id=str(sandbox_id),
                    error=str(exc),
                )

        await _set_activity(sandbox, None, None)
        _logger.info(
            "reconcile.done",
            sandbox_id=str(sandbox_id),
            cloned=len(result.cloned),
            removed=len(result.removed),
            failed=len(result.failed),
            checkpoint=result.new_checkpoint_id,
        )
        return result

    async def _ensure_git_setup(self, sandbox: Sandbox, user: User) -> None:
        """One-time-per-token git setup inside the sandbox.

        Writes:
        - `~/.gitconfig`: identity (`user.name`, `user.email`) + sets
          `credential.helper=store` for github.com so subsequent ops
          read auth from `~/.git-credentials`.
        - `~/.git-credentials`: a single line
          `https://x-access-token:<token>@github.com` so any
          `git clone https://github.com/...` (or push, fetch, pull) just
          works without per-command auth flags.

        After this runs once, the sandbox is a properly-configured git
        workstation for the user — same commands work for the agent and
        any human shell session.

        The OAuth token *does* land on disk inside the sandbox at
        `~/.git-credentials`. That's fine: the sandbox is per-user and
        isolated, and the token is already in our control plane (Mongo).
        Sandbox destroy or reset wipes the file with the rest of the FS.

        Idempotent — skipped when the configured token fingerprint
        already matches the user's current token.
        """
        token = user.github_access_token or ""
        if not token:
            return  # caller already short-circuits clones with no token
        fp = hashlib.sha256(token.encode()).hexdigest()
        if sandbox.git_configured_token_fp == fp:
            return  # already configured for this exact token

        name = user.github_username or "octo-canvas user"
        email = user.email or f"{user.github_username}@users.noreply.github.com"
        # Write to fixed paths under /etc/octo-canvas/. `sudo -n` because
        # /etc/ is root-owned and the sprite exec runs unprivileged. The
        # `GIT_CONFIG_GLOBAL` env var (set on every later git command via
        # `GIT_ENV`) tells git to read our config file regardless of $HOME,
        # so clones from any user/HOME find the same credentials.
        cred_line = f"https://x-access-token:{token}@github.com"
        script = (
            "set -eu\n"
            'sudo -n mkdir -p "$(dirname "$GIT_CONFIG")"\n'
            'sudo -n tee "$GIT_CRED_FILE" > /dev/null <<EOF\n'
            "$GIT_CRED_LINE\n"
            "EOF\n"
            'sudo -n chmod 644 "$GIT_CRED_FILE"\n'
            'sudo -n tee "$GIT_CONFIG" > /dev/null <<EOF\n'
            "[user]\n"
            "\tname = $GIT_USER_NAME\n"
            "\temail = $GIT_USER_EMAIL\n"
            "[credential]\n"
            f"\thelper = store --file={GIT_CRED_PATH}\n"
            "[init]\n"
            "\tdefaultBranch = main\n"
            "EOF\n"
            'sudo -n chmod 644 "$GIT_CONFIG"\n'
        )
        try:
            res = await self._provider.exec_oneshot(
                _handle_of(sandbox),
                ["sh", "-c", script],
                env={
                    "GIT_USER_NAME": name,
                    "GIT_USER_EMAIL": email,
                    "GIT_CRED_LINE": cred_line,
                    "GIT_CONFIG": GIT_CONFIG_PATH,
                    "GIT_CRED_FILE": GIT_CRED_PATH,
                },
                cwd="/",
                timeout_s=30,
            )
        except SpritesError as exc:
            _logger.warning(
                "reconcile.git_setup_failed",
                sandbox_id=str(sandbox.id),
                error=_redact_token(str(exc), token)[:200],
            )
            return
        if res.exit_code != 0:
            _logger.warning(
                "reconcile.git_setup_nonzero",
                sandbox_id=str(sandbox.id),
                exit_code=res.exit_code,
                stderr=_redact_token(res.stderr, token)[-1000:],
                stdout=_redact_token(res.stdout, token)[-500:],
            )
            return
        sandbox.git_configured_token_fp = fp
        if sandbox.id is not None:
            await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
                {"$set": {"git_configured_token_fp": fp}}
            )
        _logger.info(
            "reconcile.git_setup_done",
            sandbox_id=str(sandbox.id),
            user=user.github_username,
        )

    async def _clone_one(self, sandbox: Sandbox, repo: Repo, token: str | None) -> bool:
        if not token:
            await _mark_clone_failed(repo, "github_reauth_required")
            return False

        repo.clone_status = "cloning"
        repo.clone_error = None
        await repo.save()

        target = f"{WORK_ROOT}/{repo.full_name}"
        url = f"https://github.com/{repo.full_name}.git"
        owner = repo.full_name.split("/", 1)[0]
        # Single exec for both `mkdir <owner>` and `git clone`. Each
        # `exec_oneshot` opens its own WebSocket; Sprites' Exec
        # endpoint flakes the handshake on rapid back-to-back connects,
        # so doing both steps in one shell halves the per-repo failure
        # surface. Plain HTTPS URL — auth comes from the credential
        # helper that `_ensure_git_setup` already configured.
        clone_script = (
            f'mkdir -p "{WORK_ROOT}/{owner}" && '
            f"git clone --depth 1 --branch "
            f'"{repo.default_branch}" "{url}" "{target}"'
        )
        argv = ["sh", "-c", clone_script]
        try:
            res = await self._provider.exec_oneshot(
                _handle_of(sandbox),
                argv,
                # HOME must match what `_ensure_git_setup` wrote credentials
                # to — otherwise git looks elsewhere and falls back to
                # terminal prompt → "could not read Username".
                env=GIT_ENV,
                cwd="/",
                timeout_s=CLONE_TIMEOUT_S,
            )
        except SpritesError as exc:
            await _mark_clone_failed(repo, _redact_token(str(exc), token or "")[:200])
            return False

        if res.exit_code != 0:
            full = _redact_token(res.stderr, token or "")
            full_lower = full[-500:].lower()
            if "401" in full_lower or "authentication failed" in full_lower:
                kind_prefix = "github_reauth_required"
            elif "couldn't find remote ref" in full_lower or "remote branch" in full_lower:
                kind_prefix = "branch_not_found"
            else:
                kind_prefix = f"clone_failed (exit {res.exit_code})"
            # Save the full stderr (truncated to 1500 chars to fit in
            # Mongo comfortably) so the user can see what actually broke.
            detail = full[-1500:].strip()
            reason = f"{kind_prefix}: {detail}" if detail else kind_prefix
            await _mark_clone_failed(repo, reason)
            return False

        repo.clone_status = "ready"
        repo.clone_path = target
        repo.clone_error = None
        await repo.save()
        return True


async def _set_activity(sandbox: Sandbox, activity: str | None, detail: str | None) -> None:
    """Update the sandbox's progress banner using an atomic per-field
    `$set`, NOT `sandbox.save()`. The reconciler may have loaded the
    sandbox doc minutes ago; a full `save()` here would overwrite a
    destroyed/failed/reset status set by a concurrent route handler.
    `$set` only touches the two activity fields, leaving everything
    else intact.

    Best-effort — a failed update is logged but doesn't abort
    reconciliation."""
    if sandbox.id is None:
        return
    sandbox.activity = activity  # keep in-memory copy in sync
    sandbox.activity_detail = detail
    try:
        await Sandbox.find_one(Sandbox.id == sandbox.id).update(  # pyright: ignore[reportGeneralTypeIssues]
            {"$set": {"activity": activity, "activity_detail": detail}}
        )
    except Exception as exc:
        _logger.warning(
            "reconcile.set_activity_failed",
            sandbox_id=str(sandbox.id),
            activity=activity,
            error=str(exc),
        )


def _redact_token(text: str, token: str) -> str:
    """Strip the OAuth token from any string before persisting/logging."""
    if not token or token not in text:
        return text
    return text.replace(token, "<redacted>")


async def _mark_clone_failed(repo: Repo, reason: str) -> None:
    repo.clone_status = "failed"
    # Mongo string field — truncate at 4KB to keep doc sizes sane.
    repo.clone_error = reason[:4000]
    await repo.save()
    _logger.warning(
        "reconcile.clone_failed",
        repo_id=str(repo.id),
        full_name=repo.full_name,
        reason=reason[:300],  # log preview; full reason on the doc
    )


def _merge_system_packages(repos: list[Repo]) -> list[str]:
    """Union of detected + overrides across every alive repo, deduped."""
    pkgs: set[str] = set()
    for repo in repos:
        if repo.clone_status == "failed":
            # A failing repo's introspection is still a hint, but skip it
            # if it was a transient detection error (e.g. tree-fetch failed).
            pass
        intr = repo.introspection_detected
        if intr is not None:
            pkgs.update(intr.system_packages)
        ovr = repo.introspection_overrides
        if ovr is not None and ovr.system_packages is not None:
            pkgs.update(ovr.system_packages)
    return sorted(pkgs)
