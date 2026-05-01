# CLAUDE.md

Guidance for Claude Code sessions working in this repository.

## Stack — locked in, do not change without explicit approval

- Backend: Python 3.12+, FastAPI, Beanie (Pydantic + Motor), Authlib, httpx, githubkit, structlog, pydantic-settings.
- Bridge: Python 3.12+, `claude-agent-sdk`, `websockets`, GitPython.
- Frontend: TypeScript 5.x (`strict: true`, `noUncheckedIndexedAccess: true`), Vite SPA, React 18, TanStack Router (file-based), TanStack Query, `openapi-fetch`, Tailwind CSS, shadcn/ui.
- Tooling: Turborepo runs commands across pnpm and uv workspaces.

Do **not** introduce: Hono, Express, tRPC, Drizzle, Bun, Next.js, Prisma, Clerk, Better Auth, Poetry, conda, rye, npm, yarn, mypy, black, isort, flake8.

## Package managers

- Python: `uv` only. Run scripts via `uv run <command>`. Never `pip install` directly.
- TypeScript: `pnpm` only. Never `npm` or `yarn`.
- Cross-language: Turborepo. Use `pnpm <task>` from the root for everything.

## Source-of-truth bridges

- Pydantic models in `python_packages/shared_models/` are the single source of truth for FastAPI request/response schemas **and** WebSocket message schemas.
- `packages/api-types/` consumes FastAPI's `/openapi.json` (via `openapi-typescript`) and exposes typed `paths`/`components`/`operations` to the web app via `openapi-fetch`.
- The web app talks to the orchestrator via HTTP (typed) and WebSocket (typed).

## Strictness

- TypeScript: `strict: true`, `noUncheckedIndexedAccess: true`. No `any` except in generated code.
- Python: Pyright in strict mode. No untyped functions.
- Run `pnpm typecheck && pnpm lint` before considering work done.

## Workspace members

- Python uv workspace members: `apps/orchestrator`, `apps/bridge`, `python_packages/*`.
- pnpm workspace members: `apps/*`, `packages/*`, `python_packages/*` (the Python packages have empty Turbo-glue `package.json` files so Turbo can discover them).

## Where things go

- Reusable Python that is imported by both apps → `python_packages/`.
- Reusable TS that is imported by the web app → `packages/`.
- Anything specific to a single app → that app's `src/`.
