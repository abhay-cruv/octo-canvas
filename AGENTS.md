# AGENTS.md

Canonical rules for any AI coding agent (Claude Code, Codex, Copilot, Antigravity, Cursor, etc.) working in this repo. Codex reads this file by default; other agents have small pointer configs that defer here.

> **Stack inventory & rationale** live in [docs/Plan.md §5](docs/Plan.md). Don't duplicate the inventory here; the *rule* version (banned deps, uv-only, pnpm-only) is in §2.6 of this file.
> **Architecture & feature plan** lives in [docs/Plan.md](docs/Plan.md). Don't duplicate it here.
> **Active state** lives in [docs/progress.md](docs/progress.md). Update it.
> **Quick-start for agents** is [docs/agent_context.md](docs/agent_context.md). Read it first.
> **Entry point for Claude Code** is [CLAUDE.md](CLAUDE.md) — a thin pointer to this file and the docs above.

---

## 1. Read before you write

Every agent session, before making changes, read in this order:

1. [docs/agent_context.md](docs/agent_context.md) — distilled brief, optimized for agents
2. [CLAUDE.md](CLAUDE.md) — entry-point pointer for Claude Code (delegates here)
3. This file (`AGENTS.md`) — code architecture rules
4. [docs/progress.md](docs/progress.md) — what's done, what's active, what's blocked
5. [docs/Contributions.md](docs/Contributions.md) — recent entries reveal the team's working style and recent areas of focus
6. The active slice brief in [docs/slice/](docs/slice/) (currently `slice1.md`)
7. [docs/Plan.md](docs/Plan.md) — only if your task touches design boundaries; otherwise skip

If your change crosses a backend ↔ frontend boundary, also read [docs/engineering.md](docs/engineering.md) for the change flow.

---

## 2. Architecture rules

### 2.1 Modular and small

- One file = one responsibility. If a file does two unrelated things, split it.
- **Soft caps**: Python module ≤ 300 lines, TS module ≤ 250 lines, function ≤ 50 lines. These are signals, not laws — exceeding them is fine when cohesion is genuinely high; otherwise split.
- Routes: one file per resource (`routes/auth.py`, `routes/repos.py`). Never a monolithic `routes.py`.
- React components: one component per file unless trivially co-located. Co-located helpers go right above the component, no `<200-line-utils>` files.
- Python packages live under `python_packages/<pkg>/src/<pkg>/` with explicit submodules; no kitchen-sink `utils.py` or `helpers.py`.

### 2.2 Reuse before you write

**Before creating any new function, type, component, route, or package**, search the repo for an existing one:

```bash
# Quick reuse check — run these before writing
grep -rn "<thing-you-want-to-name>" apps/ packages/ python_packages/
rg "def <similar_name>|class <SimilarName>" apps/ python_packages/    # if ripgrep available
```

If something close exists:
- **Use it.** If it needs a small tweak, extend it (don't fork it).
- If it needs a structural change to fit your case, **stop and ask the user** before refactoring.
- **Never duplicate.** Copy-pasting an existing function under a new name is the most-rejected pattern in review.

If you genuinely need new code, place it where future callers will look:
- Used by both apps → `python_packages/<existing or new pkg>/`
- Used by web only → `packages/<pkg>/` or `apps/web/src/lib/`
- App-internal → that app's `src/`

### 2.3 Source-of-truth bridges (do not break)

- Pydantic models in `python_packages/shared_models/` are the wire-shape source of truth for HTTP **and** WebSocket. TS types are generated; never hand-edited.
- DB shape (`db.models.*` Beanie `Document`) ≠ API shape (`shared_models.*` `BaseModel`). Convert at the route boundary.
- See [docs/engineering.md](docs/engineering.md) for the full backend-change flow.

### 2.4 Strictness

- Python: Pyright **strict**. No untyped functions. No `Any` outside generated code.
- TypeScript: `strict: true`, `noUncheckedIndexedAccess: true`. No `any` outside generated code.
- Targeted `# pyright: ignore[<rule>]` is acceptable for known third-party type gaps (e.g., Authlib). Never disable strict mode globally.

### 2.5 Don't add what wasn't asked for

- No defensive error handling for cases that can't happen.
- No backwards-compatibility shims when you can change the code in place.
- No TODO scaffolding for "future" features. Ship the slice; the future is the next slice.
- No comments explaining what well-named code already says.

### 2.6 Dependency & tooling constraints

#### Stack — locked in, do not change without explicit approval

- **Backend (orchestrator):** Python 3.12+, FastAPI, Beanie (Pydantic + Motor), Authlib, httpx, githubkit, structlog, pydantic-settings.
- **Bridge:** Python 3.12+, `claude-agent-sdk`, `websockets`, GitPython.
- **Frontend:** TypeScript 5.x (`strict: true`, `noUncheckedIndexedAccess: true`), Vite SPA, React 18, TanStack Router (file-based), TanStack Query, `openapi-fetch`, Tailwind CSS, shadcn/ui.
- **Tooling:** Turborepo runs commands across pnpm and uv workspaces.

If you think the project needs something not on this list, **surface it to the user and wait** — don't add it.

The why-we-picked-each-one rationale lives in [docs/Plan.md §5](docs/Plan.md) (concern × choice × reason tables). This file is the rule; Plan.md is the inventory.

#### Package managers — pick the right one, never mix

- Python: `uv` only. Run scripts via `uv run <command>`. Never `pip install` directly. Never Poetry, conda, or rye.
- TypeScript: `pnpm` only (≥ 9). Never `npm` or `yarn`.
- Cross-language tasks: Turborepo. Use `pnpm <task>` from the repo root for everything (it delegates to both ecosystems).

#### Banned — do not introduce without explicit approval

Hono, Express, tRPC, Drizzle, Bun, Next.js, Prisma, Clerk, Better Auth, Poetry, conda, rye, npm, yarn, mypy, black, isort, flake8.

If a feature seems to need one of these, surface it to the user instead of adding it.

#### Adding a new dependency that *isn't* banned

1. Check that nothing already in the stack solves the problem (see [docs/Plan.md §5](docs/Plan.md) for the full inventory).
2. Pin the version explicitly. No floating ranges on production deps.
3. Add it to the right manifest: `apps/<app>/pyproject.toml` or `apps/<app>/package.json` — never the repo root unless it's dev-tooling shared across all workspaces.
4. Note the addition in [docs/Contributions.md](docs/Contributions.md).

---

## 3. Documentation rules

### 3.1 Always-update files

Update these on every meaningful change. They're the live state of the project.

| File | What to update | When |
| --- | --- | --- |
| [docs/Contributions.md](docs/Contributions.md) | One-line entries naming who (human or agent) did what | Every session, no exceptions |
| [docs/progress.md](docs/progress.md) | Slice status, current punch list, recent changes | Every session that ships code |
| [docs/engineering.md](docs/engineering.md) | New conventions, change-flow patterns, gotchas you hit | Whenever you set a new precedent |
| [docs/agent_context.md](docs/agent_context.md) | Distilled facts that future agents will need | When the repo's "shape" changes (new pkg, new boundary, new gotcha) |

### 3.2 Slice briefs — editable while active, frozen when done

[docs/slice/slice{n}.md](docs/slice/) is special:

- **The active slice's brief is editable.** When you start a new slice, **create** `docs/slice/slice{n}.md` (using prior slice briefs as the template). When you discover something the brief should have said, edit it. When the brief diverges from what was actually built, reconcile it.
- **Completed slice briefs are frozen.** Once the user approves a slice as done, its brief becomes append-only history. Don't rewrite a shipped slice's brief; capture corrections in [docs/progress.md](docs/progress.md) under "Recent changes" instead.
- **Only one slice is active at a time.** See §5.

### 3.3 Touch-only-when-asked files

Do **not** edit these unless the user explicitly says so.

- [docs/Plan.md](docs/Plan.md) — design + slice plan. Lock during slice execution.
- [docs/scaffold.md](docs/scaffold.md) — historical scaffolding brief. Frozen.
- Frozen slice briefs (see §3.2). The *active* slice brief is in-flight and editable.
- [CLAUDE.md](CLAUDE.md) — thin entry-point pointer for Claude Code. Stable; only edit when read-order or doc structure changes.
- [README.md](README.md) — user-facing setup. Update only when setup steps change.

If you believe one of these needs to change, surface it to the user and wait.

### 3.4 No new docs without a clear reader

Don't create new `.md` files unless asked. If you need to capture something, append to one of the always-update files above.

### 3.5 Deviation protocol — when reality and the plan disagree, ask

The arch docs ([docs/Plan.md](docs/Plan.md), the active slice brief in [docs/slice/](docs/slice/), and to a lesser extent [docs/agent_context.md](docs/agent_context.md) and [CLAUDE.md](CLAUDE.md)) are the agreed-upon design. **If you find yourself building something that contradicts them, stop.**

This includes — but is not limited to — discovering that:

- A planned API endpoint, data model field, or WebSocket message doesn't actually fit the use case.
- A boundary the plan draws (e.g., what lives in `python_packages/` vs an app's `src/`) is wrong for the change you're making.
- The slice brief's "out of scope" list excludes something the slice actually needs.
- A locked-in stack choice (see §2.6) genuinely doesn't solve the problem.
- The sandbox / type-bridge / auth model needs a tweak you didn't expect.

**What to do:**

1. **Stop coding the deviating change.** Don't ship it silently.
2. **Surface the divergence to the user.** State: what you were trying to do, what the plan says, what reality is forcing, and your recommendation.
3. **Wait for direction.** The user decides one of:
   - "Keep the plan; rework your approach to match." → revert and retry.
   - "Update the plan to match reality, then proceed." → user explicitly authorizes the arch-doc edit. *Only then* do you edit [docs/Plan.md](docs/Plan.md), the slice brief, or any other touch-only-when-asked doc.
   - "Both — update the plan and adjust the implementation." → do them in that order.
4. **Log the deviation.** Whatever the resolution, append an entry to [docs/Contributions.md](docs/Contributions.md) noting the deviation and the decision. If the plan was updated, also note the change in [docs/progress.md](docs/progress.md).

**Never silently:**

- Edit [docs/Plan.md](docs/Plan.md) to retroactively justify code you've already written.
- Build past a known plan conflict hoping the user won't notice.
- Treat the slice's "out of scope" list as advisory.

The plan is a contract. Renegotiate it openly when needed; don't break it on the side.

---

## 4. Verification before "done"

Run these before claiming a task is complete:

```bash
pnpm typecheck && pnpm lint && pnpm test    # all three must be green
```

For backend changes that move the API shape, also regenerate TS types — see [docs/engineering.md](docs/engineering.md) §"Type generation flow".

For UI changes, manually exercise the affected flow in a browser. Type-checks pass ≠ feature works.

---

## 5. Slice discipline

The repo ships in numbered slices (see [docs/Plan.md](docs/Plan.md) §18). Each slice is end-to-end and stacks on the previous.

### 5.1 The slice brief is the contract

Each slice has a brief at `docs/slice/slice{n}.md`. The brief defines: scope, what to build, hard rules, acceptance criteria, when-done summary template. It is the contract between the user and the agents working on the slice.

### 5.2 Authoring rules

- **Starting a new slice**: create `docs/slice/slice{n}.md` *before* writing code, using the prior slice's brief as the structural template. Sections required: *Context from the previous task*, *What "done" looks like*, *What to build*, *What's intentionally out of scope*, *Hard rules — do not violate*, *Acceptance criteria*, *When done*.
- **Working on the active slice**: edit `docs/slice/slice{n}.md` when you discover something the brief should have said, when scope shifts (with user approval), or when you reconcile the brief with what you actually built.
- **Slice goes done**: the user signs off. After that the brief is **frozen** — no more edits. Future corrections live in [docs/progress.md](docs/progress.md) under "Recent changes".
- **Don't fork** an existing slice into a new file mid-flight. If scope splits, surface that to the user and wait for direction.

### 5.3 Execution rules

- **Do not start slice N+1 before slice N is approved.** Hard rule from the slice briefs.
- Within a slice, do not ship features the brief didn't ask for. The "out of scope" list in the brief is binding.
- If you find a clearly-needed change outside the slice scope, surface it and wait.
- Update [docs/progress.md](docs/progress.md)'s "Slice status" table when a slice transitions state (`⬜` → active → `✅`).

---

## 6. Per-tool config files

This file is canonical. Other agent configs delegate here:

- [`.github/copilot-instructions.md`](.github/copilot-instructions.md) — GitHub Copilot
- [`.antigravity/instructions.md`](.antigravity/instructions.md) — Google Antigravity
- [`CLAUDE.md`](CLAUDE.md) — Claude Code (thin pointer to this file + the docs)
- This file — Codex (default location)

If you need to add a new tool, add a thin pointer file; do not duplicate the rules.
