# progress.md

Live state of the project. **Update this file every session that ships code.**

Sibling docs: [agent_context.md](agent_context.md) (quick-start) · [engineering.md](engineering.md) (change flow) · [Plan.md](Plan.md) (full design).

---

## Slice status

| # | Slice | Status | Notes |
|---|---|---|---|
| 0 | Scaffolding | ✅ shipped | Skeleton repo, placeholders, build/dev/test plumbing across both langs |
| 1 | GitHub OAuth + user persistence | ✅ shipped | `User` + `Session` collections, `/login` → `/dashboard` flow, `require_user` dependency. UI redesigned to profile view. |
| 2 | OAuth `repo` scope + repo connection | ✅ code shipped, ⬜ verifying | OAuth scope expanded to include `repo`; access token persisted on `User`; `Repo` collection; list/connect/disconnect endpoints; **401 → clear token + 403 `github_reauth_required`**; UI Reconnect flow. **No GitHub App, no smee, no webhooks** (rejected design). **No clone, no introspection, no sandbox** (slices 3 + 4). |
| 3 | Repo introspection | ⬜ not started | |
| 4 | Sandbox provider (Sprites) — per-user, multi-repo | ⬜ not started | |
| 5 | WebSocket transport | ⬜ not started | |
| 6 | Tasks + Agent SDK invocation | ⬜ not started | |
| 7 | Git ops + PR creation | ⬜ not started | |
| 8 | Event log persistence (S3) | ⬜ not started | |

---

## Active slice — Slice 2 verification

### Punch list

1. ✅ `pnpm typecheck && pnpm lint && pnpm test && pnpm build` all green (21 pytest tests)
2. ✅ `pnpm --filter @vibe-platform/api-types gen:api-types` regenerated against live orchestrator
3. ✅ Sign-in walk verified end-to-end (OAuth scope `read:user user:email repo`, token persisted to `users.github_access_token`)
4. ✅ Browse + connect + disconnect verified manually (with the route-pattern fix moving `repos.tsx` → `repos/index.tsx`)
5. ✅ `/api/repos/available` paginates server-side (`page`, `per_page`); search switched from client-side filter to GitHub `/search/repositories` server-side; `scope_mine` toggle (default true) scopes via `user:`/`org:` qualifiers
6. ✅ Token-revocation walk: revoke OAuth grant on github.com → Reconnect banner appears + `users.github_access_token=null` → Reconnect via in-page CTA → token restored, prior `Repo` rows preserved
7. ✅ Manage-orgs walk: "Manage GitHub org access" panel link → grant a previously-restricted org → org repos appear in `/repos/connect`. (The always-visible "Reconnect GitHub" button in the panel was removed — redundant given that the contextual ReconnectCard appears when actually needed and the panel link covers org-grant.)
8. ⬜ User reviews and approves slice 2; *only then* author `slice3.md`

### Known issues / blockers

- **Dev Mongo has a stale `github_repo_id_1` unique index** from the pre-fix schema — drop it once with `docker exec vibe-mongo mongosh vibe_platform --eval 'db.repos.dropIndex("github_repo_id_1")'` so cross-user repo connects work. Test DB rebuilds indexes per run (see conftest), so tests are unaffected.
- v1.1 followup: encrypt `User.github_access_token` at rest (currently plaintext in Mongo for dev simplicity)
- Org SSO requires per-org "Authorize" click on github.com before personal OAuth tokens can list/clone org repos. Mitigation: "Manage GitHub org access" button in the dashboard panel deep-links to the OAuth-app settings page; no auto-detection yet
- Server-side search via `/search/repositories` doesn't include repos the user has *only* collaborator access to on someone else's personal account (we can't enumerate "who you collaborate with"). The non-search browse path covers them via `/user/repos?affiliation=collaborator`. Acceptable for v1; flag if it bites
- `apps/web/` has no Vitest tests yet (still `--passWithNoTests`); UI verification is manual

---

## Recent changes (newest first)

### 2026-05-01

- **Dashboard redesign** — [../apps/web/src/routes/_authed/dashboard.tsx](../apps/web/src/routes/_authed/dashboard.tsx) is now a 2-column layout: left collapsible profile panel triggered by a GitHub icon (avatar, username, email, member-since, last-signed-in, account fields, Sign out — persisted via localStorage), center area shows the connected repos list with Disconnect actions and a "Browse repositories" CTA, or the Reconnect card when `needs_github_reauth`. Reused existing data via `meQueryOptions` / `connectedReposQueryOptions` / `disconnectRepo`. The standalone `/repos` route now redirects to `/dashboard` (kept `/repos/connect` as the picker page). Adheres to [../AGENTS.md §2.8](../AGENTS.md) light theme (`bg-white/80 backdrop-blur` panel, `bg-black text-white` CTAs, `border-gray-200`). `pnpm --filter @vibe-platform/web typecheck && lint` clean.
- **Plan.md ↔ slice2.md deviation surfaced** — [Plan.md §18](Plan.md) still describes slice 2 as "GitHub App + repo connection" with installations/webhooks/smee. Reality (per [slice/slice2.md](slice/slice2.md) and shipped code) chose OAuth `repo` scope expansion + per-user persisted token + Reconnect flow. Plan.md §8 (data model) and §18 should be updated to match — flagged to user; not yet actioned, awaiting explicit approval.
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
