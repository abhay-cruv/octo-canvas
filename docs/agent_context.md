# agent_context.md

Distilled context for any AI coding agent picking up work in this repo. Read this before reading any other doc.

> Sibling docs: [progress.md](progress.md) (active state) · [Contributions.md](Contributions.md) (who-did-what log) · [engineering.md](engineering.md) (change flow) · [Plan.md](Plan.md) (full design — heavy, only if needed) · [../AGENTS.md](../AGENTS.md) (rules — incl. §2.6 stack, §3.5 deviation protocol) · [../CLAUDE.md](../CLAUDE.md) (Claude Code entry-point pointer).

---

## TL;DR

- **Product**: a tool where a user connects GitHub repos, files chat-driven coding tasks, and a Claude Agent SDK process running in a Fly Sprite makes the changes and opens a PR.
- **Sandbox model**: **one persistent Sprite per user**, holding *all* of that user's connected repos under `/work/<full_name>/`. One active agent run at a time per sandbox; rest queue.
- **Stack**: Python 3.12 + FastAPI + Beanie (Mongo) on the backend; Vite + React 18 + TanStack on the frontend; Turborepo across uv (Python) and pnpm (TS) workspaces.
- **Status**: Slices 0 + 1 (scaffolding + GitHub OAuth) shipped. Slice 2 (GitHub App + repo connection) is next; brief not yet written.

---

## Repo map (where things live)

```
apps/
  web/                  Vite SPA — React 18, TanStack Router/Query, Tailwind
  orchestrator/         FastAPI service — auth, DB, GitHub, WS gateway
  bridge/               Python entry point baked into the Sprite image
packages/
  api-types/            TS types generated from /openapi.json (do NOT hand-edit)
  tsconfig/             Shared TS configs
python_packages/        Reusable Python imported by both apps
  shared_models/        Pydantic models = wire-shape source of truth (HTTP + WS)
  db/                   Beanie models + connect/disconnect
  sandbox_provider/     Sprites Protocol + impl (slice 4)
  github_integration/   githubkit + GitHub App helpers (slice 2)
  repo_introspection/   Detect language/framework (slice 3)
  agent_config/         System prompts, tool allowlists (slice 6)
docs/
  Plan.md               Full design — heavy, do NOT update without permission
  progress.md           Active state — UPDATE on every session
  agent_context.md      This file — UPDATE when repo "shape" changes
  engineering.md        Change flow & conventions — UPDATE when conventions evolve
  Contributions.md      Append-only log of who did what — UPDATE every session
  TESTING.md            Three-layer test strategy
  scaffold.md           Historical brief (slice 0)
  slice/slice1.md       Historical brief (slice 1)
```

Top-level rules files: [`../AGENTS.md`](../AGENTS.md), [`../CLAUDE.md`](../CLAUDE.md), [`../.github/copilot-instructions.md`](../.github/copilot-instructions.md), [`../.antigravity/instructions.md`](../.antigravity/instructions.md). All point back to AGENTS.md as canonical.

---

## Mandatory mental model

**Two source-of-truth invariants. Never violate.**

1. **Pydantic models in `python_packages/shared_models/` are the wire shape.** FastAPI request/response schemas use them. WebSocket messages use them. Their TS twins are *generated* into `packages/api-types/generated/schema.d.ts` — never hand-edited.
2. **DB shape ≠ API shape.** `db.models.User` (Beanie `Document`) is internal. `shared_models.UserResponse` (`BaseModel`) is the wire shape. Convert at the route boundary; never reuse a Beanie doc as a `response_model`.

---

## Coding rules (compressed; full text in [`../AGENTS.md`](../AGENTS.md))

- **Reuse before writing.** `grep`/`rg` first. Never duplicate. Extend existing code; don't fork it.
- **Modular files.** One responsibility per file. Soft caps: Python 300 lines, TS 250 lines, function 50 lines.
- **Strict typing everywhere.** Pyright strict, TS `strict: true` + `noUncheckedIndexedAccess`. No `any` / `Any` outside generated code.
- **No defensive code for impossible cases.** No comments restating well-named code. No future-proofing scaffolding.
- **Always update `docs/progress.md`, `docs/Contributions.md`, and `docs/engineering.md`** when you ship code or set a new convention. **Do not** touch `docs/Plan.md`, `CLAUDE.md`, `README.md`, or `scaffold.md` unless the user explicitly says so.
- **Slice briefs are special.** The *active* slice's brief at `docs/slice/slice{n}.md` is editable — when you start a new slice, create it; when scope shifts or the brief diverges from reality, reconcile. Once the user signs off on a slice, its brief is frozen. See [../AGENTS.md](../AGENTS.md) §5.
- **Deviation protocol.** If your work contradicts [Plan.md](Plan.md), the active slice brief, or any other arch doc — *stop, surface the divergence to the user, and wait for direction on whether the plan should be updated*. Never silently edit Plan.md to justify code already written, and never build past a known plan conflict. See [../AGENTS.md](../AGENTS.md) §3.5.

---

## Stack constraints (compressed; full rule in [`../AGENTS.md`](../AGENTS.md) §2.6, full inventory in [Plan.md §5](Plan.md))

- Python via **uv only** (`uv run <cmd>`). Never `pip install` directly.
- TypeScript via **pnpm only**. Never `npm` or `yarn`.
- Cross-language tasks via **Turborepo** (`pnpm <task>` from root).
- **Banned**: Hono, Express, tRPC, Drizzle, Bun, Next.js, Prisma, Clerk, Better Auth, Poetry, conda, rye, mypy, black, isort, flake8.

---

## Common commands

```bash
# Setup (first time)
docker compose up -d
cp .env.example .env                          # then fill in secrets
pnpm install
uv sync --all-packages --all-extras           # NOTE the flags — bare `uv sync` is wrong

# Develop
pnpm dev                                      # runs web (5173), orchestrator (3001), bridge

# Verify before "done"
pnpm typecheck && pnpm lint && pnpm test

# Single-package commands
pnpm --filter @vibe-platform/orchestrator test
pnpm --filter @vibe-platform/orchestrator typecheck
pnpm --filter @vibe-platform/web typecheck

# Single pytest test
uv run pytest apps/orchestrator/tests/test_auth.py::test_logout_clears_session -v

# Regenerate TS types after backend changes (orchestrator must be running)
pnpm --filter @vibe-platform/orchestrator dev   # terminal 1
pnpm --filter @vibe-platform/api-types gen:api-types   # terminal 2
```

---

## Gotchas (you will hit one of these — read them)

1. **`uv sync` flags** — bare `uv sync` only installs the root. Always `uv sync --all-packages --all-extras`.
2. **Vite envDir** — `.env` lives at repo root, not in `apps/web/`. `apps/web/vite.config.ts` sets `envDir: '../..'`. Without it, `import.meta.env.VITE_*` is undefined and the SPA renders blank because [../apps/web/src/lib/api.ts](../apps/web/src/lib/api.ts) throws at module load.
3. **OAuth App ≠ GitHub App** — slice 1 uses an OAuth App for sign-in. Slice 2 introduces a GitHub App for repo access. Both live in GitHub → Settings → Developer settings, both are needed eventually, they are different artifacts.
4. **Beanie `init_beanie` registration** — adding a `Document` class without registering it in [../python_packages/db/src/db/connect.py](../python_packages/db/src/db/connect.py)'s `document_models` list silently fails to query.
5. **`datetime.utcnow()` is forbidden** — deprecated in 3.12, fails Pyright strict. Use `datetime.now(UTC)` via a `_now()` helper. See [engineering.md](engineering.md).
6. **DB shape vs API shape** — never reuse a Beanie `Document` as a FastAPI `response_model`.
7. **Pytest event loop** — DB-touching tests must use the `httpx.AsyncClient + ASGITransport` fixture. Don't add `TestClient`-based tests for DB-touching code; the event-loop wiring breaks.
8. **No hand-editing `packages/api-types/generated/schema.d.ts`** — regenerate via the codegen step in [engineering.md](engineering.md).
9. **GitHub installations vary across repos** — different connected repos in the same sandbox can be on different GitHub App installations (different orgs). Mint per-repo install tokens at run-start time; never share or persist.

---

## Sandbox model — read this before touching slice 4+ work

- **One Sprite per user**, deterministic name `vibe-sbx-{user_id}`. All of that user's repos live in it under `/work/<full_name>/`.
- Lifecycle states: `none → spawning → running → idle → hibernated → resumed → running …`. Destroyed only on explicit user request. Sign-out does **not** destroy.
- One active agent run at a time per sandbox; the rest queue in Redis (`sandbox:{user_id}:queue`).
- The bridge is **long-lived per sandbox**, not per task. It `cd`s into the relevant repo subdir per `StartRun` directive.
- Reconciliation: on `ClientHello`, the orchestrator diffs the user's connected `repos` against the bridge's reported `cloned_repos` and issues `EnsureRepoCloned` / `RemoveRepo` until they match.

Full design: [Plan.md §13–§15](Plan.md).

---

## Verification recipe (the "done" bar)

1. `pnpm typecheck` — Pyright strict + tsc, all green
2. `pnpm lint` — ruff + ESLint, all green
3. `pnpm test` — pytest (real Mongo, mocked GitHub) + Vitest, all green
4. If you touched a route or response model: regenerate api-types (see Common commands above)
5. If you touched UI: exercise the affected flow in a browser
6. Update [progress.md](progress.md) with what changed
7. Append a one-line entry to [Contributions.md](Contributions.md)
8. Update [engineering.md](engineering.md) if you set a new convention

---

## When in doubt, ask. Don't:

- Don't introduce a banned dependency (see [../AGENTS.md](../AGENTS.md) §2.6).
- Don't edit Plan.md, scaffold.md, slice briefs, README.md, or CLAUDE.md without explicit user direction.
- Don't refactor existing code structurally to fit your case — surface it and wait.
- Don't start work on slice N+1 before slice N is approved.
- Don't fix a problem outside the current slice's scope without surfacing it.
