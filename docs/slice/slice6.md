# Slice 6 — IDE shell: file tree, file editor, terminal, dummy chat panel

The first slice that gives the user a real workspace to *see and touch* their sandbox. Until now the sandbox has been provisioned and repos have been cloned (slice 5b), but the only way to verify any of that is via curl + Mongo. Slice 6 ships a VS Code-style layout where the user can browse the cloned repos, open files, edit them, run shell commands in a terminal, and see a placeholder for chats — proving end-to-end that the Sprites filesystem and exec surfaces work behind orchestrator auth.

This slice ends at "**a signed-in user with a connected repo can browse `/work/<repo>/`, open and edit files (saves persist on the sprite), run `git status` / `ls` / `node --version` in a terminal, and see a 'Chats' panel with a 'New chat' button that does nothing yet — all four panels collapsible.**" It deliberately does **not** include any agent runtime, any `Chat` data model, any bridge daemon — those are slices 7 (image bake) and 8 (agent).

**Do not build features beyond this slice.** No bridge process. No `claude` CLI invocation. No real chat creation. The "New chat" button shows a "Coming in slice 8" toast and does nothing.

---

## What this slice replaces

Two pieces of the earlier slice plan collapse into this slice:

1. **Old slice 8 — interactive coding surface (PTY + file ops via Sprites)**: the orchestrator-side PTY broker and the FS REST wrapper. Those are *the* surface area of slice 6. Per [Plan.md §10.1](../Plan.md), most of this is "already done by Sprites" — slice 6 wraps it with auth and surfaces it as UI.
2. **Old slice 9 — HTTP preview proxy**: already absorbed (Sprites' built-in per-sandbox URL handles it; just surface the link).

The agent panel is **a placeholder** in slice 6. Slice 8 wires it to the bridge.

---

## Calls baked in (push back if any are wrong)

1. **VS Code-like layout, four collapsible regions.** Single page at `/_authed/sandbox` (renamed from / replacing today's dashboard sandbox panel — the dashboard becomes a router landing that redirects to either `/_authed/sandbox` if a sandbox exists or `/_authed/dashboard` if not). Layout:

   ```
   ┌──────────────────────────────────────────────────────┐
   │  Top bar: sandbox status pill, public URL, Reset/Pause │
   ├─────────┬──────────────────────────────┬─────────────┤
   │  File   │                              │  Chats      │
   │  tree   │   File editor (tabs)         │  (dummy)    │
   │  (left, │                              │  (right,    │
   │  collap-│                              │   collap-   │
   │  sible) │                              │   sible)    │
   │         ├──────────────────────────────┤             │
   │         │   Terminal (tabs)            │             │
   │         │   (bottom, collapsible)      │             │
   └─────────┴──────────────────────────────┴─────────────┘
   ```

   Each region collapses via a chevron button on its border. Collapsed widths/heights persist in `localStorage` per user (`octo:layout:left|right|bottom = "collapsed"|<px>`). Default open, sane initial sizes (left 220px, right 300px, bottom 240px).
2. **File tree**: roots at `/work/`. Children are the user's connected repos (`/work/<full_name>/`); each repo expands lazily via `GET /api/sandboxes/{id}/fs?path=...&list=true`. Nodes show file vs. directory, name, size for files. Click on a file → opens in the editor. Right-click → context menu (rename, delete; backed by `PUT/DELETE /api/sandboxes/{id}/fs`). Live-update via `FileEditEvent` on `/ws/web/sandboxes/{id}/fs/watch` (a thin orchestrator wrapper around Sprites' `fs/watch` per [Plan.md §10.2](../Plan.md)). Loading states + error states for "repo not yet cloned" (shows "cloning…" with the slice-5b status).
3. **File editor**: Monaco (already shadcn-friendly via `@monaco-editor/react`). Multi-tab. Open files load via `GET /api/sandboxes/{id}/fs?path=...` returning text + sha (for save-conflict detection). Save via `PUT /api/sandboxes/{id}/fs?path=...` with the new contents + the `If-Match: <sha>` header — orchestrator returns 412 on mismatch and the FE asks the user to reload. Unsaved changes marked with a dot in the tab. Cmd/Ctrl+S saves the active tab. Syntax highlighting via Monaco's built-in language detection; no LSP in v1.
4. **Terminal**: xterm.js. Multi-tab; "+" button opens a new terminal. Each terminal opens a new PTY via `/ws/web/sandboxes/{id}/pty/{terminal_id}` (orchestrator brokers to Sprites Exec with `tty=True` per [Plan.md §10.5](../Plan.md)). Reattach via Sprites' built-in scrollback on FE reconnect — the FE persists `terminal_id` in `sessionStorage` so a tab refresh re-attaches to the same shell. xterm.js handles resize via `ResizePty` orchestrator-side message. Default `cwd=/work`; "+" with Alt-click opens `cwd` of the currently-selected file's repo. Default shell = `bash -l` so nvm/pyenv (slice 7) work out-of-the-box.
5. **Chats panel = dummy**. Header "Chats" + a "+ New chat" button that opens a toast: "Chats arrive in slice 8." The panel renders an empty list (or "No chats yet — file system and terminal work below"). **No `Chat` model. No `/api/chats` endpoint. No bridge calls.** This is intentional: slice 6 ships the layout, slice 8 fills the panel.
6. **Auth and ownership** (no surprises): every request to `/api/sandboxes/{id}/fs*`, `/ws/web/sandboxes/{id}/pty/*`, `/ws/web/sandboxes/{id}/fs/watch` checks session cookie + ownership via slice-1's `require_user`. Mismatch → 403 (REST) or close 4003 (WS). Path-traversal validation is **server-side only** — the orchestrator rejects `..`, absolute paths outside `/work`, symlinks resolving outside `/work`. Trust nothing the FE sends.
7. **FS REST wrapper** (`apps/orchestrator/src/orchestrator/routes/sandbox_fs.py`):
   - `GET /api/sandboxes/{id}/fs?path=...&list=false` → `{type, path, content?, sha?}` (file) or with `list=true` → `[{name, type, size}]` (directory).
   - `PUT /api/sandboxes/{id}/fs?path=...` body `{content}` header `If-Match: <sha>` → 200 with new sha, 412 on mismatch.
   - `DELETE /api/sandboxes/{id}/fs?path=...` → 204.
   - `POST /api/sandboxes/{id}/fs?path=...&op=rename` body `{new_path}` → 200.
   Backed by slice-5b's `provider.fs_read`/`fs_write`/`fs_delete`/`fs_list`/`fs_rename` (the last needs to be added — see #10).
8. **PTY broker** (`apps/orchestrator/src/orchestrator/ws/pty.py`):
   - `/ws/web/sandboxes/{id}/pty/{terminal_id}` — session-cookie auth.
   - On accept: open Sprites Exec WSS via `sprite.command('bash -l', tty=True, cwd=...)`. Pipe bytes both ways. SDK handles stream framing per [python.md → Exec → BINARY PROTOCOL](../sprites/v0.0.1-rc43/python.md).
   - Resize messages: FE sends `{type:"resize", cols, rows}` (JSON in-band); orchestrator forwards to Sprites.
   - Reattach: if `(sandbox_id, terminal_id)` already has a Sprites Exec session ID in Redis hash `pty:{sandbox_id}:{terminal_id} = exec_session_id` (TTL 24h), use Attach instead of starting a new session — Sprites replays scrollback.
9. **FS-watch broker**: a single Sprites `fs/watch` WSS subscription per active sandbox (orchestrator-owned, lazy on first FE subscriber, dropped on last). Coalesce by path at ≤4 Hz (per [Plan.md §10.6](../Plan.md)). Fan out to `/ws/web/sandboxes/{id}/fs/watch` subscribers as `FileEditEvent` JSON frames. Tied into existing slice-5a `seq`-replay where useful (sync `seq` namespace per sandbox).
10. **Provider Protocol widening**: `SandboxProvider.fs_rename(handle, src, dst)` (slice 5b has `fs_delete` but not `fs_rename`). Plus `fs_watch_subscribe(handle) -> AsyncIterator[FsEvent]` (the current `provider.exec_oneshot` doesn't cover this; slice 6 adds it as a streaming Protocol method backed by Sprites' `/v1/sprites/{name}/fs/watch` WSS). Mock provider: in-memory event queue.
11. **Single-sandbox v1 enforcement preserved.** The route is `/_authed/sandbox` (singular). When multi-sandbox-per-user lands (post-v1), this becomes `/_authed/sandboxes/$sandboxId` per [Plan.md §4 forward-compat](../Plan.md). The component layer is parameterized by `sandbox_id` already.
12. **No SSH / no remote VS Code attach.** v1 user only edits via this in-app surface. Open question deferred: should users connect their local VS Code via Sprites' SSH? Marked as a v1.x followup in [Plan.md §21]; slice 6 doesn't ship it.

---

## Context from slice 5b

- Provider Protocol has `exec_oneshot`, `fs_list`, `fs_read`, `fs_write`, `fs_delete`, `snapshot`, `restore`. Slice 6 adds `fs_rename` and `fs_watch_subscribe`.
- Reconciliation places repos at `/work/<full_name>/`. Slice 6 just reads from there.
- Reconciler activity banner exists (configuring_git/installing_packages/cloning/checkpointing/pausing) — surface it on the IDE top bar.
- Sprites' Exec session reattach + scrollback works; slice 6 uses it for terminals.
- Pyright strict + TS strict + `noUncheckedIndexedAccess` are the bar.

---

## What "done" looks like

A signed-in user with at least one connected repo (`clone_status="ready"`) opens `/_authed/sandbox`:

1. Sees the four-panel layout with their sandbox's status + public URL link in the top bar.
2. File tree expands `/work/`; clicks into their repo; sees the actual files from the clone.
3. Clicks `README.md` — Monaco opens with the file contents. Edits a line. Cmd+S saves; the change persists (verified by reopening the file or running `cat README.md` in the terminal).
4. Opens a terminal — sees a working `bash -l` prompt at `/work`. Runs `cd <repo> && git status` — sees the working tree clean.
5. Opens a second terminal tab — independent shell.
6. Refreshes the browser tab — terminals reattach to the same Sprites Exec sessions; scrollback shows what was running.
7. Collapses left + right + bottom panels — the editor expands. Reopens them — back to default.
8. Clicks "+ New chat" in the right panel — sees the "Coming in slice 8" toast.
9. Edits a file via the terminal (`echo X >> README.md` from terminal) — the file tree updates within ≤1s via `fs/watch`; if the file is open in the editor, the editor shows a "Reload" prompt.
10. Two simultaneous tabs on the same sandbox: edits made in one tab show up via `fs/watch` in the other.

`pnpm typecheck && pnpm lint && pnpm test && pnpm build` all green; orchestrator pytest green.

---

## What to build

### 1. Provider widening — `python_packages/sandbox_provider/`

- Add `fs_rename(handle, src, dst) -> None` to the Protocol. SpritesProvider wraps the Sprites SDK's rename/copy method; MockSandboxProvider implements via dict mutation.
- Add `fs_watch_subscribe(handle) -> AsyncIterator[FsEvent]` — yields `{path, kind: "create"|"modify"|"delete"|"rename"}`. SpritesProvider opens the `fs/watch` WSS via `asyncio.to_thread` + an asyncio.Queue. MockSandboxProvider exposes a test hook for emitting events.
- Tests in `python_packages/sandbox_provider/tests/`.

### 2. FS REST routes — `apps/orchestrator/src/orchestrator/routes/sandbox_fs.py`

Per call #7. Pydantic request/response models in `shared_models`. Path-traversal validation via a single `_validate_path(sandbox_id, path)` helper. 412 on `If-Match` mismatch.

### 3. PTY WS broker — `apps/orchestrator/src/orchestrator/ws/pty.py`

Per call #8. Reattach state in Redis hash `pty:{sandbox_id}:{terminal_id}`. Heartbeat reuses slice-5a's machinery.

### 4. FS-watch broker — `apps/orchestrator/src/orchestrator/services/fs_watcher.py` + `ws/fs_watch.py`

Per call #9. Single Sprites subscription per sandbox; coalesce + fan-out via Redis pub/sub on `fswatch:{sandbox_id}` for cross-instance.

### 5. Wire-protocol additions — `python_packages/shared_models/src/shared_models/wire_protocol/`

- Add `FileEditEvent` (already declared in [Plan.md §10.4](../Plan.md) but not yet shipped in `events.py`); slice 6 ships it.
- Add `RequestOpenPty`, `RequestClosePty`, `ResizePty` to commands (already declared; slice 6 ships).
- Regenerate `wire.d.ts` via the existing pipeline.

### 6. Frontend — `apps/web/`

Heaviest part of the slice. New tree:

```
apps/web/src/routes/_authed/sandbox.tsx       # the four-panel page
apps/web/src/components/ide/
  Layout.tsx                                  # collapsible split-pane wrapper
  FileTree.tsx                                # left panel
  FileEditor.tsx                              # center; Monaco wrapper with tab bar
  Terminal.tsx                                # bottom; xterm.js wrapper
  Terminals.tsx                               # bottom-tab manager
  ChatsPanel.tsx                              # right; dummy with "Coming in slice 8" toast
apps/web/src/lib/
  fs.ts                                       # API client for /api/sandboxes/{id}/fs
  pty.ts                                      # WS client for /ws/web/sandboxes/{id}/pty
  fsWatch.ts                                  # WS client for /ws/web/sandboxes/{id}/fs/watch
apps/web/src/hooks/
  useFileTree.ts
  useOpenFile.ts                              # load + save + sha tracking
  useTerminal.ts                              # xterm + WS bytes
  useFsWatch.ts                               # subscription + dispatch
  usePanelLayout.ts                           # localStorage-backed sizes/collapse
```

Layout component: split-pane via `react-resizable-panels` (already shadcn-compatible). Light theme only ([AGENTS.md §2.8](../../AGENTS.md)) — white surfaces, `bg-gray-50` for inactive panels, black accents.

Routing: `/_authed/sandbox` is the sandbox-detail page; the existing `/_authed/dashboard` keeps its repo-management UI but adds an "Open IDE" CTA when a sandbox exists.

### 7. Tests

- Provider tests for `fs_rename` and `fs_watch_subscribe` (mock + sprites against fake SDK fixtures).
- Orchestrator tests:
  - `GET/PUT/DELETE /api/sandboxes/{id}/fs` happy paths + path-traversal rejection + If-Match 412.
  - `/ws/web/sandboxes/{id}/pty/{terminal_id}` handshake + reattach via Redis hash.
  - `/ws/web/sandboxes/{id}/fs/watch` fan-out across two subscribers.
- Frontend: smoke tests via Vitest + @testing-library/react for component rendering. Manual smoke in browser is the real verification (add a checklist).

### 8. Docs

- Update [docs/progress.md](../progress.md): slice 6 row.
- Update [docs/Contributions.md](../Contributions.md): session entry.
- Update [docs/agent_context.md](../agent_context.md): TL;DR + repo-map (`apps/web/src/components/ide/`); gotchas: path-traversal validation is server-side only; mention the layout `localStorage` keys.

---

## Out of scope (explicit)

- Bridge daemon, agent runtime, `Chat` model, MCP, claude-agent-sdk. Slice 8.
- Sprite image bake (Node + CLI + bridge wheel). Slice 7.
- Runtime-version install (nvm install, pyenv install). User can do it manually from the slice-6 terminal once slice 7 ships the managers; the agent does it automatically in slice 8.
- LSP / language services in the editor. Post-v1.
- Local VS Code attach via SSH. Post-v1.
- Multi-sandbox-per-user UI. Post-v1.
- HTTP preview proxy. Already absorbed by Sprites' built-in URL — slice 6 just shows it as a link in the top bar.
- 24h Mongo / S3 archive. Slice 10.

---

## Risks

1. **`fs/watch` storms.** A `pnpm install` or large checkout fires thousands of events. Coalesce-by-path at ≤4 Hz is the brake. Cap the per-sandbox event rate at 100/s; drop excess with a single `BackpressureWarning` per minute. Validate with a stress test (`for i in $(seq 1 10000); do touch /work/repo/f$i; done`).
2. **PTY reattach Redis-hash leak.** If the FE crashes without closing the WS, the `pty:{sandbox_id}:{terminal_id}` Redis entry persists for 24h with the Sprites session still alive. Sprites' own idle timer reaps the session eventually; the orchestrator should also expire entries 30 min after last byte. Add a sweeper job (slice 6 lightweight; full impl in slice 10).
3. **Monaco bundle size.** Monaco is heavy. Lazy-load via dynamic import; don't ship in the main bundle. Verify final bundle stays under reasonable size (<2 MB gzipped for the route).
4. **xterm.js + Sprites binary protocol mismatch.** Sprites ships a custom binary framing (per [python.md → Exec → BINARY PROTOCOL](../sprites/v0.0.1-rc43/python.md)) — three streams over one channel with length-prefixed frames. The orchestrator's PTY broker must demux and re-frame for xterm.js (which expects raw bytes per stream). Implement carefully; integration-test with a real shell command (`echo hello`).
5. **Concurrent edits from multiple tabs.** sha-based If-Match handles save-conflicts correctly, but the editor's "file changed externally" prompt must not trigger on the user's *own* edits in another tab if the sha hasn't been bumped server-side. Stamp each PUT response with the new sha and feed it back to the open editor instance.
6. **`fs/watch` doesn't fire for files modified inside the agent's worktree (slice 8) if the watcher subscribes to `/work` only.** Slice 6 subscribes to `/work` recursively (Sprites supports it); slice 8's worktrees live under `/work/<repo>/.octo-worktrees/` so they're covered.
7. **Path-traversal bugs are security-critical.** Server-side validation is the only safe layer; do not trust the FE. Test extensively: `..`, `..%2F`, encoded variants, symlinks, absolute paths, null bytes. Centralize validation in one helper and unit-test it with 20+ malicious inputs.
8. **Browser tab close during PUT.** If the user closes the tab mid-save, the orchestrator may complete the write (or not — the WSS to Sprites may break). Acceptable: the file's sha is the truth. The next open re-fetches and sees what actually persisted.

---

## Acceptance — copy-paste checklist

- [ ] `pnpm typecheck` clean (web + orchestrator).
- [ ] `pnpm lint` clean.
- [ ] `pnpm test` green; new orchestrator + provider + web tests included.
- [ ] `pnpm --filter @octo-canvas/api-types gen:api-types` regenerates schema with the new FS routes + WS messages; types committed.
- [ ] `pnpm build` green; Monaco bundle lazy-loaded.
- [ ] Manual smoke (real sprite): open IDE page; browse a connected repo; open + edit + save README.md; verify via terminal `cat`. Open two terminals; refresh tab; both reattach with scrollback. Edit a file via terminal; file tree updates ≤1s. Edit a file in two browser tabs simultaneously; sha-conflict surfaces correctly. Click "New chat" → toast.
- [ ] Path-traversal regression suite passes (20+ malicious inputs).
- [ ] Light theme audit ([AGENTS.md §2.8](../../AGENTS.md)) — no `dark:`, no saturated surfaces, no gradients.
- [ ] [docs/progress.md](../progress.md) row updated.
- [ ] [docs/Contributions.md](../Contributions.md) entry added.
- [ ] [docs/agent_context.md](../agent_context.md) TL;DR + gotchas updated.
- [ ] User signs off → this brief is frozen; corrections live in `progress.md`.
