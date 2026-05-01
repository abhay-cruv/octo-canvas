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

1. [docs/agent_context.md](docs/agent_context.md) — **the cold-start primer**. Optimized for agents: distilled facts, repo map, mental model, gotchas, common commands. Read this *first, in full*; it is designed to make every following doc cheaper to skim. If you only have budget for one doc, this is the one.
2. [CLAUDE.md](CLAUDE.md) — entry-point pointer for Claude Code (delegates here)
3. This file (`AGENTS.md`) — code architecture rules
4. [docs/progress.md](docs/progress.md) — what's done, what's active, what's blocked
5. [docs/Contributions.md](docs/Contributions.md) — recent entries reveal the team's working style and recent areas of focus
6. The active slice brief in [docs/slice/](docs/slice/) (currently `slice1.md`)
7. [docs/Plan.md](docs/Plan.md) — only if your task touches design boundaries; otherwise skip

If your change crosses a backend ↔ frontend boundary, also read [docs/engineering.md](docs/engineering.md) for the change flow.

### 1.1 Using `agent_context.md` efficiently

- **Cold-start every session with it.** Don't grep the repo to learn the layout, don't open `Plan.md` for a quick fact — both are answered in `agent_context.md`. Treat the heavy docs (Plan.md, full source trees) as escalation paths only when the primer doesn't cover what you need.
- **Trust it as the index, verify before acting.** The repo map, sandbox model, and gotchas in the primer are kept current; specific file paths and symbol names should still be confirmed with `Read`/`grep` before you edit code that depends on them.
- **Keep it lean.** It's a primer, not a manual. If a fact lives elsewhere (Plan.md inventory, engineering.md change flow, slice brief), link to it rather than copying it in.

### 1.2 You must update `agent_context.md`

It is an **always-update** file (see §3.1). Update it in the same session as your code change whenever the repo's "shape" shifts in a way a future cold-start agent would need to know:

- A new package, app, or top-level directory appears or moves.
- A new source-of-truth boundary, type bridge, or sandbox/runtime invariant is introduced or changed.
- A new gotcha is discovered (a non-obvious flag, a silent-failure mode, a setup step that bites).
- A locked-in stack choice changes (rare — and requires user approval per §2.6).
- A common command changes (new dev/test/codegen invocation a future agent will need).
- The slice status table or "what's next" framing materially shifts.

Do **not** update it for: ephemeral progress (that's [progress.md](docs/progress.md)), per-session activity (that's [Contributions.md](docs/Contributions.md)), or new conventions/change-flow recipes (that's [engineering.md](docs/engineering.md)). If you're unsure which file a fact belongs in, prefer the more specific one and link from `agent_context.md` only if a cold-start agent genuinely needs the pointer.

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

### 2.7 Use graphify-out as your map — first, but verify

The repo has a pre-built knowledge graph in [graphify-out/](graphify-out/) that captures cross-file relationships, communities, and architecture clusters. **For any "how does X relate to Y" / "where is Z implemented" / "what depends on this module" question, consult the graph first.** It's far cheaper (1–2k tokens) than grepping or reading files linearly.

#### Step 0 — Is graphify available?

Before using any `/graphify` command, check that it's installed:

```bash
which graphify || python3 -c "import graphify" 2>/dev/null && echo "ok" || echo "missing"
```

If it's missing:

1. **Ask the user**: "graphify isn't installed. Want me to install it (`pip install graphifyy`) so I can use the pre-built knowledge graph for relationship lookups? (Optional — I can fall back to grep/Read if you'd rather skip.)"
2. If yes → install via `pip install graphifyy` (or `--break-system-packages` on macOS if needed). Then re-run the failing command.
3. If no → fall back to `grep`/`Read`/`Explore` agent for the immediate task. Don't pester again in the same session.

If [graphify-out/graph.json](graphify-out/graph.json) doesn't exist yet either, ask the user before triggering a fresh `/graphify` build (it costs tokens). The graph is most valuable on a repo that's been graphified at least once — for first-touch agents in a fresh clone, default to grep/Read until the user opts in.

#### How to use it efficiently — common cases

| You want | Do this |
| --- | --- |
| A topology overview (god nodes, surprising edges, suggested questions) | Read [graphify-out/GRAPH_REPORT.md](graphify-out/GRAPH_REPORT.md) — it's the audit summary, not the raw graph |
| To answer a relationship question | `/graphify query "<question>"` (BFS, broad context) or `/graphify query "<question>" --dfs` (trace a chain) |
| Shortest path between two concepts | `/graphify path "<NodeA>" "<NodeB>"` |
| Everything connected to one node | `/graphify explain "<NodeName>"` |
| Open the interactive graph | open `graphify-out/graph.html` in a browser |
| Refresh after shipping changes | `/graphify --update` (incremental — re-extracts only changed files; cheap) |

**Never load `graphify-out/graph.json` directly into context** — it's the raw data, not meant for reading. Use the query subcommands; they emit a token-budget-aware ranked subgraph.

#### Other useful capabilities (use when relevant — don't pull all of these by default)

| Capability | Command | When it earns its keep |
| --- | --- | --- |
| **Add an external doc** to the corpus (paper, tweet, arxiv URL, blog post, YouTube) | `/graphify add <url> --author "..." --contributor "..."` | When the user shares a URL that should be persisted as project context. Auto-runs `--update`. |
| **Agent-crawlable wiki** (one Markdown article per community + index) | `/graphify --wiki` | Onboarding a new agent or human cold; cheaper than reading the full report. Output: `graphify-out/wiki/index.md`. |
| **Live MCP server** so agents can query the graph as tools (`query_graph`, `get_neighbors`, `god_nodes`, `shortest_path`, etc.) | `/graphify --mcp` | When you want a sub-agent to consult the graph mid-task without re-running CLI commands. |
| **Auto-rebuild on commit** | `graphify hook install` | Long-lived branches with frequent code changes — keeps the graph from going stale silently. |
| **Watch a folder** and auto-rebuild on save | `/graphify --watch` | Active dev sessions where you want the graph to stay current without manual `--update` calls. |
| **Re-cluster only** (don't re-extract — useful after manual graph edits) | `/graphify --cluster-only` | Rare. Skip unless you've hand-edited the graph. |
| **Deep-mode extraction** (richer INFERRED edges) | `/graphify --mode deep` | Use sparingly — more INFERRED edges = more edges that need verification. Costs more tokens. |
| **Directed graph** (preserves edge direction source→target) | `/graphify --directed` | When you actually need to reason about call-graph direction (e.g., "what calls `require_user`?" vs "what does `require_user` call?"). |
| **Export to other tools** | `--svg` (embed in Notion/GitHub) · `--graphml` (Gephi/yEd) · `--neo4j` (Cypher file) · `--neo4j-push <uri>` (live push) | When the user wants to explore the graph in their preferred tool. |

When in doubt: **start with `GRAPH_REPORT.md` and `/graphify query`**, escalate to other capabilities only when the basic ones don't answer the question.

#### When the graph might be stale

Findings from graphify are hypotheses, not facts. The graph reflects the corpus *at the last `/graphify` run* and may miss:

- Files added or substantially edited since
- Renames (the old node will be gone after `--update` but stale relationships may persist briefly)
- INFERRED edges (model-reasoned, audit tag visible in the report) — those need verification before acting on them

**Workflow**:

1. Confirm graphify is installed (Step 0). If not, ask the user.
2. Query graphify first for a lead.
3. **Verify the lead by reading the actual file(s)** before making decisions or writing code based on it.
4. If the graph clearly disagrees with reality (file gone, signature changed, no longer present), **run `/graphify --update`** to incrementally re-extract changed files. Don't run a full `/graphify` rebuild unless the user asks — it's expensive.

#### Don't

- Don't silently install graphify without asking the user — it's a tool choice, not a required dep.
- Don't act on an INFERRED or AMBIGUOUS edge without reading the source file.
- Don't replace `grep`/`Read` with graphify when you already know the exact file/symbol — it's slower for known-target lookups.
- Don't trigger a full rebuild after every change. Use `--update` for incremental, or skip if the change was small.
- Don't load `graph.json` directly into context. Use the query subcommands.
- Don't use `/graphify --mode deep` reflexively — the extra INFERRED edges aren't free and most need verification anyway.

### 2.8 Frontend theme — light mode, light/transparent surfaces, black accents

The web app is **light-mode only** in v1 and beyond. There is no dark-mode toggle planned. Every contributor (human or agent) writes UI components against this palette:

#### Surfaces (backgrounds)

- Page background: `bg-white` or `bg-gray-50`
- Cards / panels: `bg-white` with `border border-gray-200`, optionally `shadow-sm`
- Overlays / modals / tooltips: `bg-white/80 backdrop-blur` (transparency + blur preferred over solid grays)
- Hover/focus states: `bg-gray-100`, `bg-gray-50/50`, never colored hover backgrounds

#### Text & accents

- Primary text: `text-black` or `text-gray-900`
- Secondary text: `text-gray-600`
- Disabled/placeholder: `text-gray-400`
- Primary action button: `bg-black text-white hover:bg-gray-800` (black-on-light is the canonical CTA — see [apps/web/src/routes/login.tsx](apps/web/src/routes/login.tsx))
- Secondary button: `bg-gray-200 text-black hover:bg-gray-300` or `bg-white border border-gray-300`
- Borders: `border-gray-200` (default), `border-black` (emphasis)

#### Banned

- **No `dark:` Tailwind variants** anywhere. The app does not respond to `prefers-color-scheme: dark`.
- **No saturated brand colors** (`bg-blue-500`, `bg-red-500`, etc.) on backgrounds or large surfaces. Saturated colors are reserved for narrow semantic uses: error text (`text-red-600`), warning text (`text-amber-600`), success indicator (`text-green-600`). Never as a fill.
- **No gradient backgrounds** unless explicitly approved.
- **No glassmorphism beyond simple `backdrop-blur`** — keep it subtle.
- **No custom hex colors** in component code. Use Tailwind's gray/black palette; if you need a brand color, surface it to the user before adding to the Tailwind config.

#### shadcn/ui (when added per slice)

- Initialize with the **neutral** color theme (zinc/gray base), not slate or stone unless the user picks otherwise.
- Don't pull in shadcn's dark theme tokens.
- Component-level overrides go in [apps/web/src/components/ui/](apps/web/src/components/ui/) or the equivalent — keep them adherent to the rules above.

If a design need genuinely doesn't fit this palette, surface it to the user before deviating (per §3.5 deviation protocol).

#### Responsiveness

The web app must work across mobile, tablet, and desktop. Every UI component is responsive by default — there is no separate mobile build.

- **Mobile-first**: write base styles for the smallest viewport (~320px), then layer up with Tailwind breakpoints (`sm:`, `md:`, `lg:`, `xl:`). Don't write desktop-first and patch mobile after.
- **Test at three widths** before declaring a UI task done: ~375px (phone), ~768px (tablet), ≥1280px (desktop). Resize the browser or use devtools device emulation.
- **Layout**: prefer flex/grid with `flex-wrap`, `gap-*`, and responsive column counts (`grid-cols-1 md:grid-cols-2 lg:grid-cols-3`) over fixed widths. Avoid hardcoded `w-[...]px` for containers — use `max-w-*` + `w-full`.
- **Touch targets**: interactive elements ≥ 44×44px on mobile. Use `py-3 px-4` minimums on buttons; don't shrink them at small breakpoints.
- **Typography**: scale with breakpoints where it matters (`text-2xl md:text-4xl`). Never let headings overflow their container — use `break-words` / `truncate` deliberately.
- **No horizontal scroll** at any supported width. If content overflows, fix the layout, don't add `overflow-x-auto` as a band-aid (tables and code blocks are the legitimate exceptions).
- **Navigation**: long horizontal nav must collapse to a menu on mobile. Sidebars become drawers or stack above content.
- **Images & media**: `max-w-full h-auto` by default; use `object-cover` / `object-contain` purposefully.

If a layout genuinely can't be made responsive (e.g. a complex data viz), surface it to the user before shipping a desktop-only screen.

---

## 3. Documentation rules

### 3.1 Always-update files

Update these on every meaningful change. They're the live state of the project.

| File | What to update | When |
| --- | --- | --- |
| [docs/Contributions.md](docs/Contributions.md) | One-line entries naming who (human or agent) did what | Every session, no exceptions |
| [docs/progress.md](docs/progress.md) | Slice status, current punch list, recent changes | Every session that ships code |
| [docs/engineering.md](docs/engineering.md) | New conventions, change-flow patterns, gotchas you hit | Whenever you set a new precedent |
| [docs/agent_context.md](docs/agent_context.md) | Distilled facts a cold-starting agent needs (repo map, mental model, gotchas, common commands) | Whenever the repo's "shape" shifts — new pkg/app/boundary, new gotcha, changed setup or codegen command, changed stack invariant. See §1.1–§1.2. |

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
