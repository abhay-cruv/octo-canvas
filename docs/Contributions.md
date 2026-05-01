# Contributions.md

Append-only log of **who did what** in this repo. Every human contributor and every AI coding agent appends one or more entries per session.

This file is for **attribution and history**. It is *not* the project state (that lives in [progress.md](progress.md)) and it is *not* design context (that lives in [Plan.md](Plan.md) and [agent_context.md](agent_context.md)).

---

## Entry format

```markdown
### YYYY-MM-DD — Author / agent identifier

- One-line summary of the change. Reference files with [path](path) where useful.
- Another change in the same session.
```

Rules:

- **One block per session.** A session = one continuous working stretch by one author. If you come back later, add a new dated block.
- **Author identifier**:
  - Humans: your name or GitHub handle (`Abhay`, `@abhay-dutt`).
  - AI agents: model + tool, e.g. `Claude Opus 4.7 via Claude Code`, `GPT-4 via Codex CLI`, `Copilot inline`.
- **One bullet per logical change.** A bullet is one short sentence; if you need a paragraph, write it in [progress.md](progress.md) under "Recent changes" and reference it from here.
- **Newest at the top.** Prepend new blocks; don't append.
- **No editing past entries.** This is append-only. If a past entry is wrong, add a new bullet in the current session correcting it.
- **No noise.** Don't log "ran tests" or "read the docs" — log only changes that touched the repo.

---

## Why this file exists

- Humans get credit; agents get auditability.
- Future contributors can see the texture of how the project evolved (cadence, who owned what) without grepping `git log`.
- AI agents picking up cold can read the last few entries to infer "what's the team's working style right now."

For *what changed structurally*, read [progress.md](progress.md). For *who and when*, read this file.

---

## Log

### 2026-05-01 — Claude Opus 4.7 via Claude Code

- Expanded [../AGENTS.md](../AGENTS.md) §2.7 with a Step 0 *install-check* rule (ask user before `pip install graphifyy`, fall back to grep/Read if declined) and a second usage table covering `/graphify add <url>`, `/graphify --wiki`, `/graphify --mcp`, `graphify hook install`, `--watch`, `--cluster-only`, `--mode deep`, `--directed`, and the export modes (`--svg`, `--graphml`, `--neo4j`). Mirrored both additions in [agent_context.md](agent_context.md), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md).
- Added [../AGENTS.md](../AGENTS.md) **§2.7 Use graphify-out first** — codified the "consult the pre-built graph for relationship questions before grepping" workflow with a usage table (`/graphify query|path|explain`, `GRAPH_REPORT.md`), staleness handling (`--update` not full rebuild), and "never load `graph.json` directly" rule. Mirrored in [agent_context.md](agent_context.md), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md).
- Added [../AGENTS.md](../AGENTS.md) **§2.8 Frontend theme** — light mode only, no `dark:` variants, white / `bg-gray-50` / `bg-white/80 backdrop-blur` surfaces, black text/CTAs, no saturated colors on backgrounds, no gradients, no custom hex in component code. Mirrored as one-liners in agent_context, Copilot, Antigravity. Added pointers in CLAUDE.md "where things live" table.
- Added **deviation protocol** as [../AGENTS.md](../AGENTS.md) §3.5: when work contradicts Plan.md, the active slice brief, or any arch doc, the agent must *stop, surface the divergence, and wait for direction* before editing arch docs or building past the conflict. Mirrored as a bullet in [agent_context.md](agent_context.md), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), and [../.antigravity/instructions.md](../.antigravity/instructions.md).
- Swept remaining stale "CLAUDE.md as stack-rules home" references in [../AGENTS.md](../AGENTS.md) (§3.3 description and §6 per-tool list), [agent_context.md](agent_context.md) (Stack constraints heading + banned-deps cross-ref), and [engineering.md](engineering.md) (doc-update policy table description). All now correctly identify CLAUDE.md as a thin entry-point pointer and route stack questions to AGENTS.md §2.6 or Plan.md §5.
- Fixed stale "Stack constraints are in `CLAUDE.md`" pointers in [../.github/copilot-instructions.md](../.github/copilot-instructions.md) and [../.antigravity/instructions.md](../.antigravity/instructions.md). Both now point at [../AGENTS.md](../AGENTS.md) §2.6 for stack/package-manager/banned-deps rules and [Plan.md §5](Plan.md) for stack rationale. The "see CLAUDE.md for the banned list" reference in copilot-instructions.md was also corrected to point at AGENTS.md §2.6.
- Restored the verbatim "Stack — locked in, do not change without explicit approval" app-tier list (Backend / Bridge / Frontend / Tooling) at the top of [../AGENTS.md](../AGENTS.md) §2.6. The earlier trim left only the concern-by-concern Plan.md tables; the original four-bullet, app-tier framing wasn't preserved anywhere despite being the policy-shaped form of the rule. Now §2.6 leads with that list, followed by package managers, banned deps, and the add-a-dep checklist.
- Fixed stale header in [../AGENTS.md](../AGENTS.md) that still said "Stack rules live in CLAUDE.md" after the trim. Now correctly states stack inventory lives in [Plan.md §5](Plan.md) and the rule version lives in AGENTS.md §2.6.
- Trimmed [../CLAUDE.md](../CLAUDE.md) to a thin pointer file: read-order, "where things live" table, what-to-update-when-you-ship checklist. Moved banned dependencies + package-manager rules into [../AGENTS.md](../AGENTS.md) §2.6 ("Dependency & tooling constraints") so they live with the other agent rules. Stack inventory stays in [Plan.md §5](Plan.md); cross-refs updated.
- Trimmed [../CLAUDE.md](../CLAUDE.md) to stack rules only — moved "Source-of-truth bridges" and "Where things go" out (they were arch, not stack) and replaced with a pointer block to [Plan.md](Plan.md), [../AGENTS.md](../AGENTS.md), [agent_context.md](agent_context.md), [progress.md](progress.md), and [engineering.md](engineering.md).
- Established slice-brief authoring workflow in [../AGENTS.md](../AGENTS.md) §3.2 and §5.2: agents *create* `docs/slice/slice{n}.md` when starting a new slice, *edit* it while the slice is active, and treat it as *frozen* once the user signs off. Mirrored a one-liner in [agent_context.md](agent_context.md).
- Renamed `docs/CONTRIBUTING.md` → [engineering.md](engineering.md) since the file documented engineering change-flow, not contribution process. Swept references across [../AGENTS.md](../AGENTS.md), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md), [agent_context.md](agent_context.md), [progress.md](progress.md), [TESTING.md](TESTING.md), [Plan.md](Plan.md).
- Created this file ([Contributions.md](Contributions.md)) and wired it into the always-update list in AGENTS.md, agent_context.md, progress.md, copilot-instructions.md, antigravity instructions.md, and engineering.md.
- Established agent-rules architecture: created [../AGENTS.md](../AGENTS.md) (canonical), [../.github/copilot-instructions.md](../.github/copilot-instructions.md), [../.antigravity/instructions.md](../.antigravity/instructions.md), [agent_context.md](agent_context.md), [progress.md](progress.md). Pointed [../CLAUDE.md](../CLAUDE.md) at AGENTS.md.
- Updated [Plan.md](Plan.md) sandbox model to one persistent Sprite per user holding all of that user's connected repos under `/work/<full_name>/`. Affected §3, §4, §8 (added `sandboxes` collection), §9 (`/api/sandbox/*`), §10 (WS endpoint moved to `/ws/bridge/sandboxes/{sandbox_id}`), §13–§15, §18, §19.
- Moved most documentation into `docs/`. Rewrote internal links in [Plan.md](Plan.md) for the new location.
- Fixed Vite environment loading: [../apps/web/vite.config.ts](../apps/web/vite.config.ts) now sets `envDir: '../..'` so the repo-root `.env` is read (was causing a blank page because [../apps/web/src/lib/api.ts](../apps/web/src/lib/api.ts) threw at module load when `import.meta.env.VITE_ORCHESTRATOR_BASE_URL` was undefined).
