# Graph Report - .  (2026-05-01)

## Corpus Check
- Corpus is ~14,650 words - fits in a single context window. You may not need a graph.

## Summary
- 217 nodes · 200 edges · 64 communities detected
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 18 edges (avg confidence: 0.77)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Web App Routing & Data|Web App Routing & Data]]
- [[_COMMUNITY_Auth Tests & Session Models|Auth Tests & Session Models]]
- [[_COMMUNITY_Pydantic-to-TS Type Bridge|Pydantic-to-TS Type Bridge]]
- [[_COMMUNITY_Stack Decisions & GitHub OAuth|Stack Decisions & GitHub OAuth]]
- [[_COMMUNITY_Orchestrator Bootstrap & Logging|Orchestrator Bootstrap & Logging]]
- [[_COMMUNITY_GitHub OAuth Flow|GitHub OAuth Flow]]
- [[_COMMUNITY_Sandbox Provider Skeleton|Sandbox Provider Skeleton]]
- [[_COMMUNITY_Strictness & Backend Stack|Strictness & Backend Stack]]
- [[_COMMUNITY_User Auth Dependencies|User Auth Dependencies]]
- [[_COMMUNITY_Smoke Tests|Smoke Tests]]
- [[_COMMUNITY_UserResponse Model Split|User/Response Model Split]]
- [[_COMMUNITY_MongoDB & Beanie Layer|MongoDB & Beanie Layer]]
- [[_COMMUNITY_Mongo Lifecycle|Mongo Lifecycle]]
- [[_COMMUNITY_Turbo Pipeline Tasks|Turbo Pipeline Tasks]]
- [[_COMMUNITY_Login Page|Login Page]]
- [[_COMMUNITY_Dashboard Page|Dashboard Page]]
- [[_COMMUNITY_Bridge Smoke Test|Bridge Smoke Test]]
- [[_COMMUNITY_Pytest Client Fixture|Pytest Client Fixture]]
- [[_COMMUNITY_Health Endpoint Test|Health Endpoint Test]]
- [[_COMMUNITY_Test Infra & Troubleshooting|Test Infra & Troubleshooting]]
- [[_COMMUNITY_response_model Convention|response_model Convention]]
- [[_COMMUNITY_packages index|packages index]]
- [[_COMMUNITY_Tailwind config|Tailwind config]]
- [[_COMMUNITY_Vite config|Vite config]]
- [[_COMMUNITY_PostCSS config|PostCSS config]]
- [[_COMMUNITY_Web entry main.tsx|Web entry main.tsx]]
- [[_COMMUNITY_Vite env types|Vite env types]]
- [[_COMMUNITY_TanStack queries|TanStack queries]]
- [[_COMMUNITY_Web api client|Web api client]]
- [[_COMMUNITY_Web index route|Web index route]]
- [[_COMMUNITY_Web root layout|Web root layout]]
- [[_COMMUNITY_Authed layout|Authed layout]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Bridge main entry|Bridge main entry]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Module __init__.py|Module: __init__.py]]
- [[_COMMUNITY_Vibe mode (deferred)|Vibe mode (deferred)]]
- [[_COMMUNITY_Redis (future)|Redis (future)]]
- [[_COMMUNITY_sandbox_provider package|sandbox_provider package]]
- [[_COMMUNITY_github_integration package|github_integration package]]
- [[_COMMUNITY_repo_introspection package|repo_introspection package]]
- [[_COMMUNITY_agent_config package|agent_config package]]
- [[_COMMUNITY_tsconfig package|tsconfig package]]

## God Nodes (most connected - your core abstractions)
1. `Python backend stack` - 11 edges
2. `TypeScript frontend stack` - 9 edges
3. `Beanie models and Mongo connection helpers.` - 8 edges
4. `Slice 1: GitHub OAuth sign-in` - 8 edges
5. `_seed_user_and_session()` - 6 edges
6. `github_callback()` - 6 edges
7. `test_imports()` - 6 edges
8. `One-direction type flow (Pydantic to TS)` - 6 edges
9. `UserResponse` - 5 edges
10. `python_packages/db` - 5 edges

## Surprising Connections (you probably didn't know these)
- `Rationale: Pyright over mypy` --semantically_similar_to--> `Strict typing policy`  [INFERRED] [semantically similar]
  scaffold.md → CLAUDE.md
- `GitHub OAuth setup (local dev)` --semantically_similar_to--> `Layer 3 full UI flow with GitHub`  [INFERRED] [semantically similar]
  README.md → TESTING.md
- `Source-of-truth bridges (Pydantic to TS)` --semantically_similar_to--> `One-direction type flow (Pydantic to TS)`  [INFERRED] [semantically similar]
  CLAUDE.md → CONTRIBUTING.md
- `_upsert_user()` --calls--> `User`  [INFERRED]
  apps/orchestrator/src/orchestrator/routes/auth.py → python_packages/db/src/db/models/user.py
- `_create_session()` --calls--> `Session`  [INFERRED]
  apps/orchestrator/src/orchestrator/routes/auth.py → python_packages/db/src/db/models/session.py

## Hyperedges (group relationships)
- **Pydantic to OpenAPI to TS type pipeline** — scaffold_shared_models_pkg, scaffold_orchestrator_app, scaffold_openapi_typescript, scaffold_api_types_pkg, scaffold_web_app [EXTRACTED 1.00]
- **GitHub OAuth sign-in flow** — slice1_login_route, testing_oauth_login_endpoint, testing_oauth_callback_endpoint, slice1_session_collection, slice1_dashboard_route [EXTRACTED 1.00]
- **Three-layer test strategy** — testing_layer1_automated, testing_layer2_probe, testing_layer3_full_ui_flow [EXTRACTED 1.00]

## Communities

### Community 0 - "Web App Routing & Data"
Cohesion: 0.11
Nodes (20): Package manager rules (uv-only / pnpm-only), openapi-fetch typed api client, _authed pathless layout for protected routes, TanStack Query options factories, Rationale: file-based routes, index.html #root mount + main.tsx entry, Bilingual monorepo scaffolding, openapi-fetch (+12 more)

### Community 1 - "Auth Tests & Session Models"
Cohesion: 0.13
Nodes (9): Document, Session, Settings, _seed_user_and_session(), test_logout_clears_session(), test_me_returns_user_with_valid_session(), test_session_returns_user_with_valid_cookie(), Settings (+1 more)

### Community 2 - "Pydantic-to-TS Type Bridge"
Cohesion: 0.15
Nodes (17): Source-of-truth bridges (Pydantic to TS), Rationale: Pydantic as wire-shape source of truth, One-direction type flow (Pydantic to TS), pnpm gen:api-types regeneration, packages/api-types, apps/bridge, FastAPI, openapi-typescript codegen (+9 more)

### Community 3 - "Stack Decisions & GitHub OAuth"
Cohesion: 0.12
Nodes (16): Stack lock-in (no Hono/Express/tRPC/etc), Rationale: opaque session ID in cookie, GitHub OAuth setup (local dev), Prerequisites (Node20, pnpm9, Python3.12, uv, Docker), vibe-platform project, Authlib, claude-agent-sdk (Python), Dev mode (v1 scope) (+8 more)

### Community 4 - "Orchestrator Bootstrap & Logging"
Cohesion: 0.18
Nodes (5): BaseSettings, Settings, configure_logging(), get_logger(), main()

### Community 5 - "GitHub OAuth Flow"
Cohesion: 0.29
Nodes (9): _callback_url(), _cookie_kwargs(), _create_session(), _fetch_github_profile(), github_callback(), github_login(), logout(), _make_oauth_client() (+1 more)

### Community 6 - "Sandbox Provider Skeleton"
Cohesion: 0.17
Nodes (5): Beanie models and Mongo connection helpers., Sandbox provider interface. Methods will be added in a later slice., # TODO: define create, resume, hibernate, destroy, exec methods in the sandbox s, SandboxProvider, Protocol

### Community 7 - "Strictness & Backend Stack"
Cohesion: 0.18
Nodes (12): Strict typing policy, Rationale: strict TS + strict Pyright, githubkit, Pydantic v2, Pyright (strict), Python backend stack, Rationale: all-Python backend, Rationale: githubkit over PyGithub (+4 more)

### Community 8 - "User Auth Dependencies"
Cohesion: 0.24
Nodes (7): get_user_optional(), require_user(), _resolve_user(), session_info(), BaseModel, get_me(), UserResponse

### Community 9 - "Smoke Tests"
Cohesion: 0.29
Nodes (1): test_imports()

### Community 10 - "User/Response Model Split"
Cohesion: 0.33
Nodes (6): DB shape separate from API shape, Rationale: single require_user auth path, Rationale: User vs UserResponse split, require_user FastAPI dependency, User Beanie document, UserResponse Pydantic model

### Community 11 - "MongoDB & Beanie Layer"
Cohesion: 0.47
Nodes (6): Beanie ODM, python_packages/db, MongoDB, Rationale: Beanie over raw Motor, db.connect() Mongo+Beanie initialization, Slice 1: user persistence in MongoDB

### Community 12 - "Mongo Lifecycle"
Cohesion: 0.6
Nodes (4): lifespan(), connect(), _database_name(), disconnect()

### Community 13 - "Turbo Pipeline Tasks"
Cohesion: 0.4
Nodes (5): Layer 1 automated checks, pnpm build, pnpm lint, pnpm test, pnpm typecheck

### Community 14 - "Login Page"
Cohesion: 1.0
Nodes (0): 

### Community 15 - "Dashboard Page"
Cohesion: 1.0
Nodes (0): 

### Community 16 - "Bridge Smoke Test"
Cohesion: 1.0
Nodes (0): 

### Community 17 - "Pytest Client Fixture"
Cohesion: 1.0
Nodes (0): 

### Community 18 - "Health Endpoint Test"
Cohesion: 1.0
Nodes (0): 

### Community 19 - "Test Infra & Troubleshooting"
Cohesion: 1.0
Nodes (2): client fixture (httpx AsyncClient + ASGITransport), Troubleshooting matrix

### Community 20 - "response_model Convention"
Cohesion: 1.0
Nodes (2): Rationale: response_model always set, Always set response_model convention

### Community 21 - "packages index"
Cohesion: 1.0
Nodes (0): 

### Community 22 - "Tailwind config"
Cohesion: 1.0
Nodes (0): 

### Community 23 - "Vite config"
Cohesion: 1.0
Nodes (0): 

### Community 24 - "PostCSS config"
Cohesion: 1.0
Nodes (0): 

### Community 25 - "Web entry main.tsx"
Cohesion: 1.0
Nodes (0): 

### Community 26 - "Vite env types"
Cohesion: 1.0
Nodes (0): 

### Community 27 - "TanStack queries"
Cohesion: 1.0
Nodes (0): 

### Community 28 - "Web api client"
Cohesion: 1.0
Nodes (0): 

### Community 29 - "Web index route"
Cohesion: 1.0
Nodes (0): 

### Community 30 - "Web root layout"
Cohesion: 1.0
Nodes (0): 

### Community 31 - "Authed layout"
Cohesion: 1.0
Nodes (0): 

### Community 32 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 33 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 34 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 35 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 36 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 37 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 38 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 39 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 40 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 41 - "Bridge main entry"
Cohesion: 1.0
Nodes (0): 

### Community 42 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 43 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 44 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 45 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 46 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 47 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 48 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 49 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Module: __init__.py"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Vibe mode (deferred)"
Cohesion: 1.0
Nodes (1): Vibe mode (deferred)

### Community 58 - "Redis (future)"
Cohesion: 1.0
Nodes (1): Redis

### Community 59 - "sandbox_provider package"
Cohesion: 1.0
Nodes (1): python_packages/sandbox_provider

### Community 60 - "github_integration package"
Cohesion: 1.0
Nodes (1): python_packages/github_integration

### Community 61 - "repo_introspection package"
Cohesion: 1.0
Nodes (1): python_packages/repo_introspection

### Community 62 - "agent_config package"
Cohesion: 1.0
Nodes (1): python_packages/agent_config

### Community 63 - "tsconfig package"
Cohesion: 1.0
Nodes (1): packages/tsconfig

## Knowledge Gaps
- **50 isolated node(s):** `Sandbox provider interface. Methods will be added in a later slice.`, `# TODO: define create, resume, hibernate, destroy, exec methods in the sandbox s`, `Settings`, `Settings`, `Vibe mode (deferred)` (+45 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Login Page`** (2 nodes): `login.tsx`, `LoginPage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Dashboard Page`** (2 nodes): `dashboard.tsx`, `DashboardPage()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bridge Smoke Test`** (2 nodes): `test_smoke.py`, `test_bridge_imports()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Pytest Client Fixture`** (2 nodes): `conftest.py`, `client()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Health Endpoint Test`** (2 nodes): `test_health.py`, `test_health()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Test Infra & Troubleshooting`** (2 nodes): `client fixture (httpx AsyncClient + ASGITransport)`, `Troubleshooting matrix`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `response_model Convention`** (2 nodes): `Rationale: response_model always set`, `Always set response_model convention`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `packages index`** (1 nodes): `index.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Tailwind config`** (1 nodes): `tailwind.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Vite config`** (1 nodes): `vite.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `PostCSS config`** (1 nodes): `postcss.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Web entry main.tsx`** (1 nodes): `main.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Vite env types`** (1 nodes): `vite-env.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `TanStack queries`** (1 nodes): `queries.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Web api client`** (1 nodes): `api.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Web index route`** (1 nodes): `index.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Web root layout`** (1 nodes): `__root.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Authed layout`** (1 nodes): `_authed.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bridge main entry`** (1 nodes): `main.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Module: __init__.py`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Vibe mode (deferred)`** (1 nodes): `Vibe mode (deferred)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Redis (future)`** (1 nodes): `Redis`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `sandbox_provider package`** (1 nodes): `python_packages/sandbox_provider`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `github_integration package`** (1 nodes): `python_packages/github_integration`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `repo_introspection package`** (1 nodes): `python_packages/repo_introspection`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `agent_config package`** (1 nodes): `python_packages/agent_config`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `tsconfig package`** (1 nodes): `packages/tsconfig`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Python backend stack` connect `Strictness & Backend Stack` to `Web App Routing & Data`, `Stack Decisions & GitHub OAuth`, `Pydantic-to-TS Type Bridge`, `MongoDB & Beanie Layer`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Why does `TypeScript frontend stack` connect `Web App Routing & Data` to `Stack Decisions & GitHub OAuth`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Why does `UserResponse` connect `User Auth Dependencies` to `Sandbox Provider Skeleton`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Beanie models and Mongo connection helpers.` (e.g. with `UserResponse` and `SandboxProvider`) actually correct?**
  _`Beanie models and Mongo connection helpers.` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `_seed_user_and_session()` (e.g. with `User` and `Session`) actually correct?**
  _`_seed_user_and_session()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Sandbox provider interface. Methods will be added in a later slice.`, `# TODO: define create, resume, hibernate, destroy, exec methods in the sandbox s`, `Settings` to the rest of the system?**
  _50 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Web App Routing & Data` be split into smaller, more focused modules?**
  _Cohesion score 0.11 - nodes in this community are weakly interconnected._