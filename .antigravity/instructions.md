# Antigravity instructions

The canonical agent rules for this repo live in [`AGENTS.md`](../AGENTS.md). Read it first — including §2.6 for the locked-in stack, package managers, and banned dependencies.

The active slice and project state are in [`docs/progress.md`](../docs/progress.md) and [`docs/agent_context.md`](../docs/agent_context.md). Architecture and stack rationale (concern × choice × why) live in [`docs/Plan.md`](../docs/Plan.md) §5.

## Quick rules (full set in AGENTS.md)

- **Reuse before writing.** Search the repo for existing code before adding new code. Never duplicate.
- **Modular files.** One responsibility per file; soft caps 250–300 lines.
- **Strict typing.** Pyright strict, TS `strict: true` + `noUncheckedIndexedAccess`. No `any` outside generated code.
- **Pydantic is wire-shape source of truth.** Never hand-edit generated TS types.
- **Update `docs/progress.md`, `docs/Contributions.md`, and `docs/engineering.md`.** Do not edit `docs/Plan.md`, `CLAUDE.md`, `README.md`, or frozen slice briefs unless explicitly asked.
- **Deviation protocol.** If your work contradicts `docs/Plan.md` or the active slice brief, *stop and ask the user* whether the plan should be updated — never silently edit arch docs to match code you've already written. See [`AGENTS.md`](../AGENTS.md) §3.5.
- **Verify before done:** `pnpm typecheck && pnpm lint && pnpm test`.
