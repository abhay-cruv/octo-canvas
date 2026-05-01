# progress.md

Live state of the project. **Update this file every session that ships code.**

Sibling docs: [agent_context.md](agent_context.md) (quick-start) · [engineering.md](engineering.md) (change flow) · [Plan.md](Plan.md) (full design).

---

## Slice status

| # | Slice | Status | Notes |
|---|---|---|---|
| 0 | Scaffolding | ✅ shipped | Skeleton repo, placeholders, build/dev/test plumbing across both langs |
| 1 | GitHub OAuth + user persistence | ✅ code shipped, ⬜ verifying | `User` + `Session` collections, `/login` → `/dashboard` flow, `require_user` dependency |
| 2 | GitHub App + repo connection | ⬜ not started | Brief not yet written; awaiting slice 1 sign-off |
| 3 | Repo introspection | ⬜ not started | |
| 4 | Sandbox provider (Sprites) — per-user, multi-repo | ⬜ not started | |
| 5 | WebSocket transport | ⬜ not started | |
| 6 | Tasks + Agent SDK invocation | ⬜ not started | |
| 7 | Git ops + PR creation | ⬜ not started | |
| 8 | Event log persistence (S3) | ⬜ not started | |

---

## Active slice — Slice 1 verification

### Punch list

1. ⬜ `uv sync --all-packages --all-extras` (Python deps install)
2. ⬜ `docker compose up -d` (Mongo running)
3. ⬜ `.env` populated with real `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, `AUTH_SECRET`, plus `MONGODB_URI`, `WEB_BASE_URL`, `ORCHESTRATOR_BASE_URL`, `VITE_ORCHESTRATOR_BASE_URL`
4. ⬜ Restart `pnpm dev` (picks up the Vite `envDir` fix and the OAuth credentials)
5. ⬜ Walk the sign-in flow at http://localhost:5173 → `/login` → GitHub → `/dashboard` → "Sign out"
6. ⬜ Verify `users` and `sessions` documents land in Mongo and clear correctly on sign-out
7. ⬜ `pnpm typecheck && pnpm lint && pnpm test` all green
8. ⬜ `pnpm --filter @vibe-platform/api-types gen:api-types` so [../packages/api-types/generated/schema.d.ts](../packages/api-types/generated/schema.d.ts) reflects the live OpenAPI schema (currently the scaffolding stub)
9. ⬜ User reviews and approves slice 1; *only then* author `slice2.md`

### Known issues / blockers

- _none currently_

---

## Recent changes (newest first)

### 2026-05-01

- Expanded [../AGENTS.md](../AGENTS.md) §2.7 with: (a) **Step 0 install check** — if `graphify` isn't installed, ask the user before installing, fall back to grep/Read if they decline; same for first-touch agents in fresh clones with no `graphify-out/`; and (b) a second usage table of **less-common-but-useful capabilities**: `/graphify add <url>` (ingest external docs/papers/tweets/YouTube), `/graphify --wiki` (agent-crawlable Markdown), `/graphify --mcp` (live MCP server), `graphify hook install` (auto-rebuild on commit), `--watch`, `--cluster-only`, `--mode deep`, `--directed`, `--svg`/`--graphml`/`--neo4j[-push]`. Mirrored the install-check rule + new capabilities in [agent_context.md](agent_context.md), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md).
- Added **§2.7 Use graphify-out first** to [../AGENTS.md](../AGENTS.md): rules + table for using the pre-built knowledge graph in [../graphify-out/](../graphify-out/) as a low-token map for relationship/architecture questions, with strict verification rules (treat as hypotheses, read the actual file before acting, run `/graphify --update` if stale, never load `graph.json` directly into context).
- Added **§2.8 Frontend theme — light mode only** to [../AGENTS.md](../AGENTS.md): canonical Tailwind palette (white/`bg-gray-50` surfaces, `bg-white/80 backdrop-blur` overlays, `bg-black text-white` CTAs, `border-gray-200` borders) and explicit bans (no `dark:` variants, no saturated colors on backgrounds, no gradients, no custom hex in component code). Existing CTAs in [../apps/web/src/routes/login.tsx](../apps/web/src/routes/login.tsx) already match this convention.
- Mirrored both new rules as one-liners in [agent_context.md](agent_context.md), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md). Added rows to [../CLAUDE.md](../CLAUDE.md)'s "where things live" table so the entry-point file routes Claude Code to both new sections.
- Trimmed [../CLAUDE.md](../CLAUDE.md) to a **thin pointer file** (entry point for Claude Code: read-order, where-things-live table, what-to-update-when-you-ship). Stack tables stay in [Plan.md §5](Plan.md), banned dependencies + package-manager rules moved into [../AGENTS.md](../AGENTS.md) §2.6 ("Dependency & tooling constraints"). Plan.md §5 cross-refs updated to point at AGENTS.md §2.6 for the *rule*; Plan.md remains the inventory.
- Trimmed [../CLAUDE.md](../CLAUDE.md) to **stack rules only** (dependencies, package managers, strictness, workspace facts). Removed "Source-of-truth bridges" and "Where things go" sections (they were arch rules) and replaced with a pointer block to [Plan.md](Plan.md), [../AGENTS.md](../AGENTS.md), [agent_context.md](agent_context.md), [progress.md](progress.md), and [engineering.md](engineering.md).
- Established the **slice-brief authoring workflow** in [../AGENTS.md](../AGENTS.md) §3.2 + §5.2: starting a new slice means *creating* `docs/slice/slice{n}.md` before writing code; the active brief is editable while in-flight; once the user signs off, the brief is frozen and corrections live in `progress.md`. Updated [agent_context.md](agent_context.md) to mirror the rule.
- Renamed `docs/CONTRIBUTING.md` → `docs/engineering.md` (the file documents engineering change-flow, not contribution process). Updated all references across [../AGENTS.md](../AGENTS.md), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md), [agent_context.md](agent_context.md), [progress.md](progress.md), [TESTING.md](TESTING.md), [Plan.md](Plan.md).
- Created [Contributions.md](Contributions.md) — append-only "who did what" log that every human and agent updates per session. Distinct from progress.md (project state).
- Established agent-rules architecture: created [../AGENTS.md](../AGENTS.md) (canonical), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md), [agent_context.md](agent_context.md), [progress.md](progress.md) (this file). Pointed [../CLAUDE.md](../CLAUDE.md) at AGENTS.md.
- Documented the "modular, reuse before write, doc-update policy" rules in AGENTS.md.
- Updated [Plan.md](Plan.md) sandbox model: one persistent Sprite per user holding all of that user's connected repos under `/work/<full_name>/` (was per-repo). Affects §3, §4, §8 (data model — added `sandboxes` collection), §9 (HTTP API — `/api/sandbox/*`), §10 (WS endpoint moved to `/ws/bridge/sandboxes/{sandbox_id}`), §13–§15 (lifecycle + bridge runtime + git workflow), §18 (slice plan), §19 (risks).
- Moved most documentation into `docs/`: `Plan.md`, `scaffold.md`, `TESTING.md`, `CONTRIBUTING.md` (later renamed to `engineering.md`), `slice/slice1.md`. `README.md` and `CLAUDE.md` stay at root. Plan.md internal links rewritten for the new location; other moved docs may still have stale links.
- Fixed Vite environment loading: [../apps/web/vite.config.ts](../apps/web/vite.config.ts) now has `envDir: '../..'` so the repo-root `.env` is read (previously caused a blank page because `import.meta.env.VITE_ORCHESTRATOR_BASE_URL` was undefined and [../apps/web/src/lib/api.ts](../apps/web/src/lib/api.ts) threw at module load).

---

## Followups noted but not actioned

- The other docs moved into `docs/` (`scaffold.md`, `TESTING.md`, `engineering.md`, `slice/slice1.md`) likely have stale internal links assuming repo-root paths. Sweep when convenient.
- README.md (still at root) references docs that have moved. Update when README is touched for any other reason.
- Auto-regeneration of `api-types` on backend changes is intentionally manual for v1; revisit post-v1.
- Webhook delivery in local dev (slice 2) — needs smee.io / ngrok flow documented in slice 2 brief.

---

## Update protocol for this file

When you finish a session, before reporting "done":

1. Move completed punch-list items to a "✅" entry under **Recent changes** with a one-line note.
2. Add new known issues under **Known issues / blockers** if you hit any.
3. If a slice transitions state, update the **Slice status** table.
4. Add anything you noticed but didn't fix to **Followups noted but not actioned**.
5. Append a one-line entry to [Contributions.md](Contributions.md) — *who did what*, separate from the *what state is the project in* tracked here.

Keep entries concise — prose belongs in [Plan.md](Plan.md), state belongs here, attribution belongs in Contributions.md.
