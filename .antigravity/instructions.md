# Antigravity instructions

**Cold-start primer:** read [`docs/agent_context.md`](../docs/agent_context.md) **first, in full** — repo map, mental model, gotchas, common commands. It's optimized so every later doc is cheaper to skim. You are also expected to **update it** when the repo's shape shifts (new pkg/boundary/gotcha/command); see [`AGENTS.md` §1.1–§1.2](../AGENTS.md).

After the primer, the canonical agent rules for this repo live in [`AGENTS.md`](../AGENTS.md) — including §2.6 for the locked-in stack, package managers, and banned dependencies. Active project state is in [`docs/progress.md`](../docs/progress.md). Architecture and stack rationale (concern × choice × why) live in [`docs/Plan.md`](../docs/Plan.md) §5.

## Quick rules (full set in AGENTS.md)

- **Reuse before writing.** Search the repo for existing code before adding new code. Never duplicate.
- **Modular files.** One responsibility per file; soft caps 250–300 lines.
- **Strict typing.** Pyright strict, TS `strict: true` + `noUncheckedIndexedAccess`. No `any` outside generated code.
- **Pydantic is wire-shape source of truth.** Never hand-edit generated TS types.
- **Update `docs/progress.md`, `docs/Contributions.md`, and `docs/engineering.md`.** Do not edit `docs/Plan.md`, `CLAUDE.md`, `README.md`, or frozen slice briefs unless explicitly asked.
- **Deviation protocol.** If your work contradicts `docs/Plan.md` or the active slice brief, *stop and ask the user* whether the plan should be updated — never silently edit arch docs to match code you've already written. See [`AGENTS.md`](../AGENTS.md) §3.5.
- **Use graphify-out first.** For relationship / architecture / "where does X live" questions, check [`graphify-out/GRAPH_REPORT.md`](../graphify-out/GRAPH_REPORT.md) or run `/graphify query "<q>"` before grepping the whole repo. If `graphify` isn't installed, *ask the user before installing* — never silently. Other useful commands: `/graphify add <url>` (ingest paper/tweet/blog), `/graphify --wiki`, `/graphify --mcp`, `graphify hook install`. Treat findings as hypotheses — verify by reading the actual file. Never load `graph.json` directly. See [`AGENTS.md`](../AGENTS.md) §2.7.
- **Frontend = light theme only.** White / light surfaces, `bg-white/80 backdrop-blur` overlays, black text and CTAs (`bg-black text-white`), `border-gray-200`. No `dark:` variants, no saturated colors on backgrounds, no gradients, no custom hex codes. See [`AGENTS.md`](../AGENTS.md) §2.8.
- **Verify before done:** `pnpm typecheck && pnpm lint && pnpm test`.
