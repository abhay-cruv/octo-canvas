# CLAUDE.md

Entry point for Claude Code sessions in this repository. The actual rules live elsewhere — this file just tells you where.

## Read in this order

1. [docs/agent_context.md](docs/agent_context.md) — **cold-start primer; read in full first.** Repo map, mental model, gotchas, common commands — designed so every later doc is cheaper to skim. If you only have budget for one doc, it's this one. You are also expected to **update it** when the repo's shape shifts (new pkg/boundary/gotcha/command). See [AGENTS.md §1.1–§1.2](AGENTS.md).
2. [AGENTS.md](AGENTS.md) — canonical agent rules: modular code, reuse-before-write, strictness, dependency constraints, doc-update policy, slice discipline
3. [docs/progress.md](docs/progress.md) — active project state and current punch list
4. [docs/Contributions.md](docs/Contributions.md) — recent activity log; a glance reveals current focus and team cadence
5. The active slice brief in [docs/slice/](docs/slice/) — the contract for whatever you're working on
6. [docs/Plan.md](docs/Plan.md) — only when your task touches design boundaries (sandbox model, type bridges, data model, API surface, etc.)

## Where things live

| Topic | Source of truth |
| --- | --- |
| Stack choices, dependency inventory, tech-stack rationale | [docs/Plan.md §5](docs/Plan.md) |
| Banned dependencies + package-manager rules | [AGENTS.md §2.6](AGENTS.md) |
| Strictness (Pyright strict, TS strict) | [AGENTS.md §2.4](AGENTS.md) |
| Repo layout + workspace membership | [docs/Plan.md §6](docs/Plan.md) |
| Type bridges (Pydantic → OpenAPI → TS) | [docs/Plan.md §7](docs/Plan.md) |
| Where reusable code lives (`python_packages/` vs `packages/` vs app `src/`) | [AGENTS.md §2.2](AGENTS.md) |
| Use graphify-out as your map (efficiently, verify findings) | [AGENTS.md §2.7](AGENTS.md) |
| Frontend theme rules (light mode only, light/transparent surfaces, black accents) | [AGENTS.md §2.8](AGENTS.md) |
| Engineering change-flow recipes | [docs/engineering.md](docs/engineering.md) |
| Test strategy | [docs/TESTING.md](docs/TESTING.md) |

## What to update when you ship

- Always: [docs/Contributions.md](docs/Contributions.md), [docs/progress.md](docs/progress.md)
- When you set a new convention: [docs/engineering.md](docs/engineering.md)
- When the repo's "shape" changes (new pkg, app, boundary, type bridge, gotcha, common command, or stack invariant): [docs/agent_context.md](docs/agent_context.md) — keep it current so the next cold-start agent loads accurate context. Details in [AGENTS.md §1.1–§1.2](AGENTS.md).
- Active slice brief at [docs/slice/slice{n}.md](docs/slice/) while it's in flight (frozen once user signs off)
- Never (without explicit user direction): [docs/Plan.md](docs/Plan.md), this file, [README.md](README.md), [docs/scaffold.md](docs/scaffold.md), frozen slice briefs
