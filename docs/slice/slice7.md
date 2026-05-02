# Slice 7 — Sprite image bake + runtime installation + agent_config bootstrap

The "make the sandbox ready for the agent" slice. Slice 6 just shipped an IDE shell that proves the sandbox is reachable end-to-end (FS panel, file editor, terminal). Slice 7 makes it ready for **slice 8**'s agent runtime by baking everything the agent will need into the sprite image and installing language runtimes on demand. This is the slice that turns "we have a Linux box" into "we have a developer workstation pre-loaded for any of the user's repos."

This slice ends at "**a user-connected repo's detected runtimes (Node X, Python Y) and system packages get installed in the sandbox; the sprite image carries Node ≥ 20, the pinned `claude` CLI binary, the bridge wheel, runtime managers (nvm/pyenv/etc), and a working bridge entrypoint that boots cleanly even though there's no orchestrator-side bridge handler yet (slice 8 adds that).**" It deliberately does **not** include the bridge↔orchestrator WSS handler, the Chat data model, or any agent invocation — those are slice 8.

**Do not build features beyond this slice.** No `/ws/bridge/{sandbox_id}` handler. No `Chat` model. No `claude-agent-sdk` invocation. No agent UI wiring beyond what slice 6 already shipped (the dummy panel stays dummy until slice 8).

---

## What this slice replaces / completes

Three previously-deferred items collapse into this slice:

1. **Slice-5b followup**: "Runtime install deferred to slice 6 — `nvm`/`pyenv`/etc owned by agent runtime" ([progress.md](../progress.md) "Slice-5b open followups"). That responsibility lands here, decoupled from agent runtime so we can verify it independently.
2. **Sprite image bake** that the slice-8 agent depends on: Node + `claude` CLI + bridge wheel. The earlier slice-6 draft owned this; we moved it here so slice 8 just consumes a ready image.
3. **`python_packages/agent_config/`** scaffolding (currently empty per agent_context.md repo-map): the `ClaudeCredentials` Protocol, the system-prompt templates, the dev-agent prompt — all the static config the agent will need. Slice 7 fills the package; slice 8 consumes it.

---

## Calls baked in (push back if any are wrong)

1. **Sprite image is the canonical artifact.** A new `apps/bridge/Dockerfile.sprite` is the source of truth for what's inside every sprite. Built and pushed in CI on every merge to main. Tagged with the git commit SHA + a `latest` floating tag. The orchestrator's `SandboxProvider.create()` accepts an image tag (slice 5b's `Sandbox` provision call gets a new `image_tag: str | None = None` arg defaulting to `BRIDGE_IMAGE_TAG` env var). Build steps:
   - **Base**: Sprites' image expectation (Ubuntu LTS + passwordless sudo, per slice 5b's `apt-get` convention).
   - **System**: `apt-get install -y curl ca-certificates git build-essential` plus the slice-3+5b `system_packages` baseline (`libpq-dev`, `libxml2-dev`, etc — derived from a static "v1 baseline" list curated in `apps/bridge/sprite-baseline-packages.txt`).
   - **Python 3.12** + `uv` (already required by the bridge). `uv` installs to `/usr/local/bin/uv`.
   - **Node ≥ 20** via NodeSource (`curl -fsSL https://deb.nodesource.com/setup_20.x | bash -` then `apt-get install -y nodejs`). Pin major version in the Dockerfile.
   - **`claude` CLI** at a pinned version: `npm i -g @anthropic-ai/claude-code@<pinned>`. Pin recorded in `apps/bridge/CLAUDE_CLI_VERSION` (one-line file). Boot-time check: bridge runs `claude --version` and refuses to start on mismatch.
   - **Runtime managers** preinstalled but no language versions (those install on demand per repo): `nvm` at `/usr/local/nvm`, `pyenv` at `/usr/local/pyenv`, `rbenv` at `/usr/local/rbenv`. Activated via `/etc/profile.d/octo-runtimes.sh` so `bash -l` and `bash -i` both pick them up. Verified by smoke test: `bash -l -c 'nvm --version && pyenv --version'` exits 0.
   - **Bridge wheel**: built from `apps/bridge/` workspace (`uv build`), copied into image as `/opt/bridge/octo_bridge-<v>.whl`, installed via `uv pip install --system /opt/bridge/octo_bridge-<v>.whl`.
   - **Entrypoint**: `python -m bridge.main`. The bridge is allowed to start with no orchestrator URL configured (in slice 7 it just logs "no `ORCHESTRATOR_WS_URL`, idling" and stays alive). Slice 8 flips this to "dial home, fail fast if unreachable."
2. **Image build runs in CI on every main-branch merge.** New GitHub Actions workflow `.github/workflows/sprite-image.yml`. Steps: build the bridge wheel from a clean checkout, `docker build`, push to a registry (env-configured: `SPRITE_IMAGE_REGISTRY` — for v1 we use Sprites' image registry per their docs; if Sprites accepts external registries, GHCR is the fallback). Tag pattern: `sha-<short>` + `latest`. Failed builds block merge. Smoke test inside the build: `docker run --rm <image> bash -l -c 'claude --version && python -m bridge.main --self-check && nvm --version'` exits 0; `--self-check` is a new bridge flag that loads the package, checks env-var schema, and exits 0 (no WSS connect).
3. **Runtime install is per-chat, on-demand, by the agent — not by the reconciler.** Slice 5b reconciler stays focused on `apt-get install` for `system_packages`. Language-runtime install (`nvm install 20.11.0`, `pyenv install 3.12.4`, etc.) happens **inside the agent's working session** in slice 8. Slice 7's job is to make sure the *managers* exist, the activation script is correct, and the agent has a documented procedure (in the dev-agent system prompt, see #5 below). **Do not build a server-side runtime-install endpoint.** The agent's `Bash` tool runs `nvm install <version>` itself when needed; the result goes into the worktree's `.nvmrc` etc. Persistence: `nvm`/`pyenv` install caches live under `/usr/local/nvm/versions/` and `/usr/local/pyenv/versions/` — survives sandbox hibernation, lost on `Reset` (slice 5b's `rm -rf /work` doesn't touch them; that's deliberate).
4. **Introspection-derived `runtimes` field is the *target*, not auto-installed.** Slice 5b ships `RepoIntrospection.runtimes: list[Runtime]`. Slice 7 surfaces these on the dashboard repo card with a "Runtimes the agent will install on first chat" hint, but installs nothing eagerly. The dev-agent prompt (#5) tells the agent to consult `runtimes` and call `nvm install` / `pyenv install` once before any work that needs them. **No new server-side endpoint, no new state.** Just UI surfacing + prompt instruction.
5. **`python_packages/agent_config/` filled in** with everything slice 8 will consume statically. New layout:
   ```
   python_packages/agent_config/
   ├── pyproject.toml
   └── src/agent_config/
       ├── __init__.py
       ├── credentials.py        # ClaudeCredentials Protocol + PlatformApiKeyCredentials
       ├── prompts/
       │   ├── __init__.py
       │   └── dev_agent.py      # render_dev_agent_prompt(repo, introspection, claude_md_text)
       └── tools/
           ├── __init__.py
           └── allowlist.py      # canonical tool allowlist for the dev agent
   ```
   The Protocol per [Plan.md §14.7](../Plan.md). v1 implementation: `PlatformApiKeyCredentials` reads `ANTHROPIC_API_KEY` from env; that's it. The `dev_agent.py` template renders inputs (repo metadata, introspection, optional in-repo CLAUDE.md) into the system prompt — slice 8 calls it on each session spawn. **Not yet wired** to a running agent in slice 7, but the package is importable, type-checked, and unit-tested.
6. **Bridge skeleton ships in slice 7, idle.** `apps/bridge/` becomes a real workspace member (currently empty per agent_context.md). Layout per [slice8.md](slice8.md) §8 minus the WSS / session-mux logic — slice 7 ships only:
   - `pyproject.toml` (uv workspace member; depends on `claude-agent-sdk`, `websockets`, `pydantic`, `agent_config`, `shared_models`).
   - `src/bridge/main.py` — entrypoint. Reads env, logs configuration, validates `agent_config.credentials` is constructible, supports `--self-check` (exits 0 immediately), supports `--version` (prints baked CLI + wheel versions). Without `--self-check` and without `ORCHESTRATOR_WS_URL`, sleeps forever and logs heartbeat lines (so `docker run` doesn't exit immediately).
   - `src/bridge/config.py` — pydantic-settings model for env vars. Single source of truth for `BRIDGE_TOKEN`, `ORCHESTRATOR_WS_URL`, `MAX_LIVE_CHATS_PER_SANDBOX`, `IDLE_AFTER_DISCONNECT_S`, `CLAUDE_AUTH_MODE`.
   - `tests/test_self_check.py` — smoke test for `--self-check`.
   No WSS client, no MCP, no session mux — those are slice 8.
7. **Sprite-provisioning passes the new env vars and image tag.** Slice 5b's `SandboxProvider.create()` widens to accept `image_tag: str | None`. Slice 7 widens it again (callsite-only): orchestrator's `SandboxManager.get_or_create` mints a `BRIDGE_TOKEN` (256-bit token, `secrets.token_urlsafe(32)`), hashes it (`Sandbox.bridge_token_hash`), and passes the plaintext + `ORCHESTRATOR_WS_URL` + `ANTHROPIC_API_KEY` (from orchestrator env) + `CLAUDE_AUTH_MODE="platform_api_key"` into the sprite's env at provision time. **The bridge does not connect yet** (`ORCHESTRATOR_WS_URL` may even be left blank in slice 7 to avoid noise; bridge will idle), but the env wiring is verified. Slice 8 flips on the WSS handler and the bridge connects.
8. **Sandbox doc widening** (subset of [slice8.md](slice8.md) call #11; the rest lands in slice 8): `bridge_token_hash: str | None`, `bridge_image_tag: str | None`. NOT yet adding `bridge_version`, `bridge_connected_at`, or `bridge_last_acked_seq_per_chat` — those are slice 8's because they require a running connection.
9. **Frontend repo card surfaces `runtimes` + the "agent will install on first chat" hint.** Replaces the slice-5b "detected runtimes" pill row with a small banner that says "Agent will install: Node 20, Python 3.12 (cached after first use)" or similar. Editable overrides already exist (slice-5b `IntrospectionOverrides.runtimes`).
10. **Verification**. Slice 7 ships green when:
    - The image builds in CI on a clean checkout.
    - `docker run --rm <image> bash -l -c 'claude --version && python -m bridge.main --self-check'` exits 0.
    - Provisioning a sandbox in dev (with `BRIDGE_IMAGE_TAG` pointing at the new image) results in a running sprite where `provider.exec_oneshot(['bash', '-l', '-c', 'nvm --version && claude --version'])` exits 0.
    - The bridge process inside the sprite is alive and emitting heartbeat logs (no WSS connection — that's expected in slice 7).
    - `python_packages/agent_config/` imports cleanly, `PlatformApiKeyCredentials().env()` returns `{"ANTHROPIC_API_KEY": "..."}` when `ANTHROPIC_API_KEY` is set.

---

## Context from slice 5b (and slice 6)

- **Slice 5b**: passwordless sudo, `apt-get` deduped, fixed git config at `/etc/octo-canvas/gitconfig` via `GIT_CONFIG_GLOBAL`. Slice 7's image preserves this; the Dockerfile sources/installs into the same paths the reconciler expects.
- **Slice 5b**: `RepoIntrospection.runtimes` + `system_packages` already detected. Slice 7 *uses* runtimes (banner UI + dev-agent prompt input) and *consumes* `system_packages` baked into the image (a static curated baseline; per-repo additions still install via reconciler).
- **Slice 6**: IDE shell shipped — file tree, file editor, terminal. Slice 7 doesn't change them. The terminal is the manual escape hatch for verifying nvm/pyenv work; the user can `nvm install 20` from the terminal in slice 6 to prove the pipeline before slice 8 even ships.
- **Slice 5a**: WS plumbing for `/ws/web/...`. Slice 7 doesn't touch it.
- Pyright strict + TS strict are the bar.

---

## What "done" looks like

After this slice:

1. CI builds and pushes the sprite image on every main-branch merge.
2. A developer can `docker run` the image locally and `bash -l -c 'claude --version'` works.
3. Provisioning a fresh sandbox via `POST /api/sandboxes` boots a sprite from the new image; `bridge --self-check` passes inside it; the bridge process idles cleanly.
4. The web dashboard's repo card shows the "agent will install" banner driven by `runtimes` introspection.
5. From the slice-6 terminal, the user can run `nvm install 20 && node --version` and it works (proves runtime managers are wired).
6. `python_packages/agent_config/` is importable; `PlatformApiKeyCredentials` resolves env when `ANTHROPIC_API_KEY` is set.
7. `pnpm typecheck && pnpm lint && pnpm test && pnpm build` all green.
8. Bridge `pytest` (just `--self-check` smoke for now) green.

---

## What to build

### 1. Sprite image — `apps/bridge/Dockerfile.sprite`

New file. Multi-stage: builder stage builds the bridge wheel via `uv build`; final stage installs system deps + Node + CLI + runtime managers + the wheel. Documented base assumptions (Sprites' image expectation; `sudo -n` available).

Pin the Node major in the Dockerfile and the CLI version in `apps/bridge/CLAUDE_CLI_VERSION`. Pin pyenv/nvm/rbenv to specific commits (security + reproducibility).

### 2. CI workflow — `.github/workflows/sprite-image.yml`

Trigger on `push: branches: [main]` and `workflow_dispatch`. Steps:
1. Checkout.
2. Build bridge wheel (`uv build apps/bridge/`).
3. `docker build -t <registry>/octo-sprite:sha-${SHA::8} -t <registry>/octo-sprite:latest -f apps/bridge/Dockerfile.sprite .`.
4. In-build smoke test (RUN line in Dockerfile): `bash -l -c 'claude --version && python -m bridge.main --self-check && nvm --version && pyenv --version'`.
5. Push (gated on registry creds being available; PRs build but don't push).

Output: image SHA tag committed back to `apps/bridge/CURRENT_IMAGE.txt` for traceability (or just relied on as a registry artifact).

### 3. `agent_config` package — `python_packages/agent_config/`

Per call #5. Files:
- `pyproject.toml` — uv workspace member, deps on pydantic + shared_models.
- `src/agent_config/credentials.py` — `ClaudeCredentials` Protocol + `PlatformApiKeyCredentials` impl.
- `src/agent_config/prompts/dev_agent.py` — `render_dev_agent_prompt(...) -> str` template; reads from a Jinja-style or f-string-based skeleton in the same dir.
- `src/agent_config/tools/allowlist.py` — canonical list for slice 8 (`["Read","Write","Edit","Bash","Glob","Grep","ask_user_clarification"]`).
- `tests/test_credentials.py`, `tests/test_dev_agent_prompt.py` — pure-function unit tests.

Register in workspace pyproject. Pyright-clean.

### 4. Bridge skeleton — `apps/bridge/`

Per call #6. Files:
- `apps/bridge/pyproject.toml`, `src/bridge/{main.py, config.py, __init__.py}`, `tests/test_self_check.py`.
- Entrypoint `python -m bridge.main` — uses `argparse` for `--self-check` and `--version`.
- Config via pydantic-settings: required `BRIDGE_TOKEN`, optional `ORCHESTRATOR_WS_URL` (no error if blank in slice 7), optional bounds (`MAX_LIVE_CHATS_PER_SANDBOX=5`, `IDLE_AFTER_DISCONNECT_S=300`, `CLAUDE_AUTH_MODE="platform_api_key"`).
- Default loop without `ORCHESTRATOR_WS_URL`: log every 60s `bridge: idle (no ORCHESTRATOR_WS_URL configured)`, sleep, repeat. Slice 8 replaces this with the WSS dialer.

### 5. Sandbox provisioning — `apps/orchestrator/src/orchestrator/services/sandbox_manager.py`

Widen `get_or_create` to:
1. Mint `bridge_token = secrets.token_urlsafe(32)`; hash with sha256; persist `Sandbox.bridge_token_hash`.
2. Pass into `provider.create()` env: `BRIDGE_TOKEN`, `ORCHESTRATOR_WS_URL` (from `ORCHESTRATOR_BASE_URL` + `/ws/bridge/{sandbox_id}`; may be blank in slice 7 dev), `ANTHROPIC_API_KEY` (from orchestrator env), `CLAUDE_AUTH_MODE="platform_api_key"`, `MAX_LIVE_CHATS_PER_SANDBOX`, `IDLE_AFTER_DISCONNECT_S`.
3. Pass `image_tag = settings.bridge_image_tag` (new `Settings` field, default `"latest"`).

### 6. Provider widening — `python_packages/sandbox_provider/`

Add `image_tag: str | None` to `SandboxProvider.create()`'s signature. `SpritesProvider` forwards it to the Sprites SDK's spawn call (Sprites supports a `image` parameter per their docs). `MockSandboxProvider` records it for assertion in tests.

### 7. Frontend repo card — `apps/web/src/components/RepoCard.tsx` (or wherever the introspection pills live)

Replace the slice-5b "detected runtimes" pill row with a banner:
- Title: "Agent setup"
- Body: "Will install on first chat: Node 20.x, Python 3.12.x" (joined from `repo.introspection.runtimes`).
- Edit button hooks the existing slice-5b override flow.

If `runtimes` is empty: show "No language runtimes detected — agent will use system defaults".

### 8. Tests

- Bridge unit tests (`apps/bridge/tests/`): `--self-check` exits 0; missing `BRIDGE_TOKEN` exits non-zero with helpful error.
- Agent_config unit tests: `PlatformApiKeyCredentials.env()` returns the right dict; missing env raises; `render_dev_agent_prompt` produces stable output for a fixture introspection.
- Orchestrator tests: `SandboxManager.get_or_create` writes `bridge_token_hash` (verified non-empty, 64 hex chars); env vars passed to provider include `BRIDGE_TOKEN`.
- CI: image-build smoke is its own GitHub Actions test; not in pytest.
- Manual smoke (documented): provision a sandbox; from the slice-6 terminal run `claude --version`, `nvm install 20`, verify they work.

### 9. Docs

- Update [docs/agent_context.md](../agent_context.md) gotchas: add a row noting the sprite image bake + version-pin location (`apps/bridge/CLAUDE_CLI_VERSION`).
- Update [docs/engineering.md](../engineering.md) with the sprite-image-rebuild recipe (when do you bump the CLI version, how do you redeploy).
- Update [docs/progress.md](../progress.md) row.
- Update [docs/Contributions.md](../Contributions.md) entry.

---

## Out of scope (explicit)

- Bridge↔orchestrator WSS handler (`/ws/bridge/{sandbox_id}`). Slice 8.
- `Chat` data model, `ChatTurn`, multi-session multiplexing, MCP `ask_user_clarification`. Slice 8.
- Worktree-based repo layout. Slice 8.
- User-facing "switch chats" UI. Slice 8.
- Hard token-budget enforcement, User Agent. Slice 8b.
- Git push, PR open. Slice 9.
- 24h Mongo / S3 cold-archive. Slice 10.
- BYOK / OAuth Claude credentials. Reserved (Protocol exists; impls don't).

---

## Risks

1. **Sprites' image-registry constraints.** Sprites may require images from their own registry / specific format. Verify before writing CI: confirm with [docs/sprites/v0.0.1-rc43/python.md](../sprites/v0.0.1-rc43/python.md) and Sprites support if unclear. Fallback: bake at the `cmd` level instead of image (run install scripts via `exec_oneshot` on first boot) — slower but works without a registry. **Decide at slice kickoff.**
2. **CLI binary version drift between dev (laptop) and sprite.** Boot-time `claude --version` check refuses to start on mismatch. Pin in `CLAUDE_CLI_VERSION`; bump = image rebuild.
3. **Image bloat.** nvm + pyenv + rbenv + Node + Python 3.12 + apt baseline = a few hundred MB. Acceptable for v1; revisit if cold-spawn latency bites.
4. **Runtime managers conflict with `apt-get`-installed Node/Python.** Don't install Node from `apt` — use NodeSource only. Don't install Python from `apt` outside what Ubuntu ships. nvm/pyenv add to PATH via the activation script.
5. **`/etc/profile.d/octo-runtimes.sh` only runs in login shells.** Some Sprites Exec invocations use `bash -c`, not `bash -l`. Document the gotcha; the slice-5b `exec_oneshot` already passes `bash -l -c` per convention. The `claude` CLI's own `Bash` tool should run with login shells (slice 8 verifies).
6. **CI registry creds in PRs.** Build-but-don't-push for forks; full push only on `main`. Don't accidentally let a malicious PR push to the registry.
7. **`agent_config` package becoming a dumping ground.** Keep it scoped: credentials Protocol + prompts + tool allowlist. Anything chat- or session-shaped belongs in slice 8's `apps/bridge/`.
8. **Bridge wheel build in CI is slow on cold cache.** Cache `uv` + `pip` layers. Consider building the wheel as a separate workflow step, then `COPY --from=builder` into the sprite image.

---

## Acceptance — copy-paste checklist

- [ ] `pnpm typecheck` clean.
- [ ] `pnpm lint` clean.
- [ ] `pnpm test` green; new orchestrator + agent_config + bridge tests included.
- [ ] `uv build apps/bridge/` produces a wheel locally.
- [ ] `docker build -f apps/bridge/Dockerfile.sprite .` succeeds locally.
- [ ] `docker run --rm <image> bash -l -c 'claude --version && python -m bridge.main --self-check && nvm --version && pyenv --version'` exits 0.
- [ ] CI workflow `.github/workflows/sprite-image.yml` green on a test branch (push-only-on-main behaviour verified).
- [ ] Provisioning a sandbox in dev with `BRIDGE_IMAGE_TAG=<new-sha>` results in a sprite where `provider.exec_oneshot(['bash', '-l', '-c', 'claude --version'])` exits 0.
- [ ] From the slice-6 terminal, `nvm install 20 && node --version` works.
- [ ] `Sandbox.bridge_token_hash` is populated after provision; never logged or returned in API responses.
- [ ] Repo card "Agent setup" banner renders with detected runtimes.
- [ ] [docs/progress.md](../progress.md) row updated.
- [ ] [docs/Contributions.md](../Contributions.md) entry added.
- [ ] [docs/agent_context.md](../agent_context.md) gotchas + status line updated.
- [ ] [docs/engineering.md](../engineering.md) gains the sprite-image-rebuild recipe.
- [ ] User signs off → this brief is frozen; corrections live in `progress.md`.
