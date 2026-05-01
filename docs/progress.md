# progress.md

Live state of the project. **Update this file every session that ships code.**

Sibling docs: [agent_context.md](agent_context.md) (quick-start) · [engineering.md](engineering.md) (change flow) · [Plan.md](Plan.md) (full design).

---

## Slice status

| # | Slice | Status | Notes |
|---|---|---|---|
| 0 | Scaffolding | ✅ shipped | Skeleton repo, placeholders, build/dev/test plumbing across both langs |
| 1 | GitHub OAuth + user persistence | ✅ shipped | `User` + `Session` collections, `/login` → `/dashboard` flow, `require_user` dependency. UI redesigned to profile view. |
| 2 | OAuth `repo` scope + repo connection | ✅ shipped | OAuth scope expanded to include `repo`; access token persisted on `User`; `Repo` collection; list/connect/disconnect endpoints; **401 → clear token + 403 `github_reauth_required`**; UI Reconnect flow. **No GitHub App, no smee, no webhooks** (rejected design). **No clone, no introspection, no sandbox** (slices 3 + 4). [slice2.md](slice/slice2.md) is now frozen — corrections live below. |
| 3 | Repo introspection | ✅ shipped | GitHub Trees + Contents detection, no clone. Five fields incl. `dev_command`. Per-field user overrides via `PATCH /api/repos/{id}/introspection`. [slice3.md](slice/slice3.md) is now frozen — corrections live below. |
| 4 | Sandbox provisioning (the box exists) | 🟡 active — brief drafted, awaiting sign-off | Brief at [slice4.md](slice/slice4.md). Six open decisions resolved inline (lazy doc creation, no salt, 20 GB cap, mock provider when key empty, etc.) — push back on any. |
| 5a | WebSocket transport — control + events | ⬜ not started | Plan.md §10 rewritten with multi-WS architecture, disconnect handling, sticky routing. |
| 5b | Reconciliation + clone | ⬜ not started | `EnsureRepoCloned` / `RemoveRepo` directives; clone reconciliation on `ClientHello`. |
| 6 | Tasks + Agent SDK invocation | ⬜ not started | |
| 7 | Git ops + PR creation | ⬜ not started | |
| 8 | Interactive coding surface — PTY + file ops | ⬜ not started | New slice. PTY WS per terminal (binary, on-demand); file ops via REST. |
| 9 | HTTP preview proxy | ⬜ not started | New slice. `https://sandbox-{id}.preview.<domain>` forwards to dev server in Sprite. |
| 10 | Event log persistence (S3) | ⬜ not started | Was slice 8 in the previous plan. |

---

## Active slice — none

Slice 3 signed off **2026-05-01**. [slice3.md](slice/slice3.md) is frozen. Corrections / followups live in this file from now on.

Next: slice 4 (sandbox provider — Sprites, per-user, multi-repo). **Brief must be authored before any code** ([AGENTS.md §3.2](../AGENTS.md), [CLAUDE.md](../CLAUDE.md)).

### Slice-3 corrections (post-freeze)

- **CORS allowlist must include PATCH (and PUT)** — initial slice 3 ship missed this; the new `PATCH /api/repos/{id}/introspection` failed CORS preflight on the web client. Fixed in [../apps/orchestrator/src/orchestrator/app.py](../apps/orchestrator/src/orchestrator/app.py) `allow_methods` list. Lesson: when adding a new HTTP verb to any route, check `app.add_middleware(CORSMiddleware, ...)` first.

### Open followups (not blockers; flag at slice-4 kickoff)

- **v1.1 introspection followups**: framework detection (React/Vue/Django/Flask), monorepo workspace splits, periodic re-introspection refresh, "force-clear detected → null" toggle (current `IntrospectionOverrides` design can't actively suppress a non-null detected value), Trees-API truncation handling for repos >100k entries / >7MB.
- **Dev Mongo has a stale `github_repo_id_1` unique index** from the pre-fix schema — drop it once with `docker exec vibe-mongo mongosh vibe_platform --eval 'db.repos.dropIndex("github_repo_id_1")'` so cross-user repo connects work. Test DB rebuilds indexes per run (see conftest), so tests are unaffected.
- v1.1 followup: encrypt `User.github_access_token` at rest (currently plaintext in Mongo for dev simplicity).
- Org SSO requires per-org "Authorize" click on github.com before personal OAuth tokens can list/clone org repos. Mitigation: "Manage GitHub org access" button in the dashboard panel deep-links to the OAuth-app settings page; no auto-detection yet.
- Server-side search via `/search/repositories` doesn't include repos the user has *only* collaborator access to on someone else's personal account (we can't enumerate "who you collaborate with"). The non-search browse path covers them via `/user/repos?affiliation=collaborator`. Acceptable for v1; flag if it bites.
- `apps/web/` has no Vitest tests yet (still `--passWithNoTests`); UI verification is manual.

### Slice-2 corrections (post-freeze)

*None yet — record any here as discovered.*

---

## Recent changes (newest first)

### 2026-05-01 (Plan.md rewrite — transport architecture + slice resplit)

- **Plan.md §10 fully rewritten** — single-endpoint WS protocol replaced with the multi-WS architecture: WS for both legs (web↔orchestrator and orchestrator↔bridge), four logical channels split across separate WS connections (control+events, PTY, file ops, HTTP preview). gRPC explicitly considered and rejected with the reasoning recorded inline. New §10.8 Reliability subsection covers disconnects in detail: 30s/90s heartbeat with `Ping`/`Pong` nonces; `seq`-replay via `Resume{after_seq}` against Mongo; idempotent directives with `directive_id` + 100-entry dedup window on the bridge; bridge reconnect loop with exponential backoff `1, 2, 4, 8, 16, 30` (±25% jitter), web with `0.5, 1, 2, 4, 8, 16, 30` (±25%); explicit backpressure caps (≤1000 events per (run, web subscriber); ≤5 MB pending bridge-side; PTY drops frames; file-watch coalesces by path at ≤4 Hz); fail-fast on auth, fail-soft on schema mismatch. New §10.9 Horizontal scale: sticky-by-sandbox routing via Fly `fly-replay`, Redis pub/sub on `sandbox:{id}` as the slow-path fallback, per-instance soft cap of 5000 WS with hot-shedding via `orchestrator_capacity` Redis hash. New §10.10 explicit non-goals (no FE↔bridge direct, no muxing all four channels, no SSE fallback, no protocol versioning beyond Pydantic schema evolution).
- **§18 slice plan resplit**: slice 4 narrowed to *provisioning only* (Sprite spawn/destroy/hibernate via REST + idle-hibernation; no WS, no clone, no reconciliation). Old slice 5 expanded into 5a (control+events WS, bridge runtime, sticky routing) + 5b (clone + reconciliation + disk-cap eviction). New slice 8 = interactive coding surface (PTY WS per terminal + file ops REST + live diff stream). New slice 9 = HTTP preview proxy. Old slice 8 (event-log S3) renumbered to slice 10. Slices 6 (tasks + Agent SDK) and 7 (git ops + PR creation) keep their numbers and scope.
- **§19 risks** gained 8 new entries (#16–23) tied to the new transport design: WS-not-gRPC lock-in, multi-connection per concern rule, application-level heartbeat, idempotent directives, sticky-by-sandbox routing as load-bearing, explicit backpressure policy, jittered reconnect backoff, per-instance capacity cap with hot-shedding. Existing #10 (bridge token) and #15 (`/work` quota) retagged from slice 5/4 to slice 5a/5b respectively.
- **§20 status snapshot** updated for the new slice numbering; flagged the rewrite date.
- This is the first edit to Plan.md since slice 0 — done with explicit user direction per [AGENTS.md §3.3](../AGENTS.md). Authoring of the slice 4 brief is the next step; six open decisions still need user input before that brief can be written (Sprites SDK pin, Fly region, naming-collision strategy, `/work` disk cap value, Redis schema confirmation, eager-vs-lazy sandbox doc creation).

### 2026-05-01 (slice 3 — repo introspection, code shipped + scope amendment)

- **Scope amendment (in-flight)**: added `dev_command` field + per-field user overrides. `Repo` doc now stores `introspection_detected` and `introspection_overrides` separately; the wire shape `ConnectedRepo` exposes both raw fields plus an `introspection` field carrying the merged-effective values. New `PATCH /api/repos/{repo_id}/introspection` endpoint (full replacement of overrides; send `{}` to clear). Re-introspect preserves overrides — only `detected` refreshes. Five new override-endpoint tests + dev_command coverage in `test_commands.py`. Brief updated in-flight (allowed per [AGENTS.md §3.2](../AGENTS.md)) — see [slice3.md §0](slice/slice3.md). Total tests now: orchestrator 35, introspection 50.
- UI: pills row gained a fifth (`dev_command`) entry; overridden fields render as a black-filled pill with a `•` glyph. New "Edit fields" button per row toggles an inline panel with five text inputs (placeholder = detected value, helper text "Detected: …" below the input), Clear all / Cancel / Save buttons. Save calls `PATCH`; query invalidates on success. Disabled while saving.

### 2026-05-01 (slice 3 — repo introspection, code shipped)

- **Slice 3 brief authored** at [slice/slice3.md](slice/slice3.md) — GitHub-API-only detection (Trees + Contents), no clone. Adapter pattern in [../python_packages/repo_introspection/src/repo_introspection/github_source.py](../python_packages/repo_introspection/src/repo_introspection/github_source.py) so slice 4 can swap to a filesystem source.
- **`shared_models.RepoIntrospection`** added at [../python_packages/shared_models/src/shared_models/introspection.py](../python_packages/shared_models/src/shared_models/introspection.py) — embedded on `Repo` and surfaced on `ConnectedRepo`. `PackageManager` literal extended to include `bun`, `maven`, `gradle`, `other` (user-edited during draft).
- **`repo_introspection` package** filled in: `language.py` (extension-counting with vendor-dir filter), `package_manager.py` (lockfile-priority + `pyproject.toml` blob disambiguation for uv/poetry), `commands.py` (per-pm test/build with `package.json scripts` parsing for JS, `[tool.pytest]` signal for pip), `orchestrate.py` (single `introspect_via_github` entry point).
- **Routes** ([../apps/orchestrator/src/orchestrator/routes/repos.py](../apps/orchestrator/src/orchestrator/routes/repos.py)): `_introspect_into` runs inline on connect (best-effort — non-401 failures logged + swallowed, 401 propagates as `github_reauth_required`); new `POST /api/repos/{repo_id}/reintrospect` endpoint with the same reauth discipline.
- **Web UI** ([../apps/web/src/routes/_authed/dashboard.tsx](../apps/web/src/routes/_authed/dashboard.tsx)): four-pill row per connected repo (`primary_language`, `package_manager`, `test_command`, `build_command`; `null` renders as muted `—`); per-row "Re-introspect" / "Detect repo info" button; dim during pending mutation. `apps/web/src/lib/repos.ts` gains `reintrospectRepo` with the same 403-reauth pattern.
- **Tests**: 46 unit tests in [../python_packages/repo_introspection/tests/](../python_packages/repo_introspection/tests/) (language, package_manager, commands — pure functions, no network); 8 new integration tests in [../apps/orchestrator/tests/test_repos.py](../apps/orchestrator/tests/test_repos.py) covering connect-with-introspection, swallow-non-401-failure, propagate-reauth, and the four reintrospect cases. Total orchestrator tests: 29 passed.
- **API types regenerated** — [../packages/api-types/generated/schema.d.ts](../packages/api-types/generated/schema.d.ts) now exposes `RepoIntrospection`, `ConnectedRepo.introspection`, and the reintrospect path. Verification: dumped `app.openapi()` → `/tmp/openapi.json` → `openapi-typescript` (running orchestrator not required).
- **Verification**: `pnpm typecheck && pnpm lint && pnpm test && pnpm build` all green. Pyright strict + TS strict zero errors.

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
