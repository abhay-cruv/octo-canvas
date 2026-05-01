# Graph Report - .  (2026-05-01)

## Corpus Check
- 107 files · ~75,261 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 443 nodes · 633 edges · 89 communities detected
- Extraction: 76% EXTRACTED · 24% INFERRED · 0% AMBIGUOUS · INFERRED: 152 edges (avg confidence: 0.71)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Project Docs & Slice Discipline|Project Docs & Slice Discipline]]
- [[_COMMUNITY_Repo Introspection Tests|Repo Introspection Tests]]
- [[_COMMUNITY_FastAPI App & Health|FastAPI App & Health]]
- [[_COMMUNITY_GitHub OAuth Wrapper|GitHub OAuth Wrapper]]
- [[_COMMUNITY_Mongo Lifecycle & Collections|Mongo Lifecycle & Collections]]
- [[_COMMUNITY_Command Detection|Command Detection]]
- [[_COMMUNITY_Package Manager Detection|Package Manager Detection]]
- [[_COMMUNITY_Repo Models & Sandbox API|Repo Models & Sandbox API]]
- [[_COMMUNITY_Agent Rules & Conventions|Agent Rules & Conventions]]
- [[_COMMUNITY_Auth Session Tests|Auth Session Tests]]
- [[_COMMUNITY_Primary Language Detection|Primary Language Detection]]
- [[_COMMUNITY_Frontend Repo API Client|Frontend Repo API Client]]
- [[_COMMUNITY_Smoke Tests|Smoke Tests]]
- [[_COMMUNITY_Repo Introspection Architecture|Repo Introspection Architecture]]
- [[_COMMUNITY_UserMe API Routes|User/Me API Routes]]
- [[_COMMUNITY_Type Bridges (Pydantic→TS)|Type Bridges (Pydantic→TS)]]
- [[_COMMUNITY_Login Page UI|Login Page UI]]
- [[_COMMUNITY_Repo Map Docs|Repo Map Docs]]
- [[_COMMUNITY_Bridge & Agent Runtime|Bridge & Agent Runtime]]
- [[_COMMUNITY_Frontend Query Hooks|Frontend Query Hooks]]
- [[_COMMUNITY_Bridge Smoke Tests|Bridge Smoke Tests]]
- [[_COMMUNITY_Health Endpoint Test|Health Endpoint Test]]
- [[_COMMUNITY_Risks & Gotchas|Risks & Gotchas]]
- [[_COMMUNITY_Product Description|Product Description]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 88|Community 88]]

## God Nodes (most connected - your core abstractions)
1. `_seed_user_and_session()` - 25 edges
2. `detect_commands()` - 25 edges
3. `detect_package_manager()` - 23 edges
4. `_stub_blobs()` - 21 edges
5. `RepoIntrospection` - 21 edges
6. `_stub_blob()` - 20 edges
7. `Beanie models, raw collection access, and Mongo lifecycle helpers.` - 17 edges
8. `Collections` - 16 edges
9. `Slice 2 — OAuth repo scope + repo connection brief` - 14 edges
10. `Repo` - 13 edges

## Surprising Connections (you probably didn't know these)
- `get_me()` --calls--> `UserResponse`  [INFERRED]
  apps/orchestrator/src/orchestrator/routes/me.py → python_packages/shared_models/src/shared_models/user.py
- `Tech stack lock-in` --semantically_similar_to--> `Dependency & tooling constraints`  [INFERRED] [semantically similar]
  docs/scaffold.md → AGENTS.md
- `_seed_user_and_session()` --calls--> `User`  [INFERRED]
  apps/orchestrator/tests/test_repos.py → python_packages/db/src/db/models/user.py
- `_seed_user_and_session()` --calls--> `Session`  [INFERRED]
  apps/orchestrator/tests/test_repos.py → python_packages/db/src/db/models/session.py
- `test_connect_propagates_reauth_from_introspection()` --calls--> `GithubReauthRequired`  [INFERRED]
  apps/orchestrator/tests/test_repos.py → python_packages/github_integration/src/github_integration/exceptions.py

## Hyperedges (group relationships)
- **** —  [EXTRACTED 1.00]
- **** —  [EXTRACTED 1.00]
- **** —  [EXTRACTED 1.00]

## Communities

### Community 0 - "Project Docs & Slice Discipline"
Cohesion: 0.05
Nodes (51): Sandbox model summary, Frontend theme — light mode only, Mobile-first responsiveness, Slice briefs editable then frozen, Slice discipline, motor → pymongo migration entry, Slice 2 OAuth repo-scope redesign entry, Slice 2 sign-off + collection registry (+43 more)

### Community 1 - "Repo Introspection Tests"
Cohesion: 0.13
Nodes (34): RepoIntrospection, Repo, Settings, _patch_introspection(), _patch_user_client(), Non-401 introspection failures must not block the connection., Two users connecting the same github_repo_id must both succeed.     Previously b, If detection hasn't run, overrides still persist and surface on the     `introsp (+26 more)

### Community 2 - "FastAPI App & Health"
Cohesion: 0.08
Nodes (19): health(), Liveness + Mongo reachability. 503 if Mongo is down so load balancers     drop u, _callback_url(), _cookie_kwargs(), _create_session(), _fetch_github_profile(), github_callback(), github_login() (+11 more)

### Community 3 - "GitHub OAuth Wrapper"
Cohesion: 0.1
Nodes (27): call_with_reauth(), Thin wrapper around githubkit for OAuth-token calls., Run a githubkit coroutine; convert HTTP 401 into GithubReauthRequired., user_client(), Exception, GithubReauthRequired, Raised when a GitHub call returns 401 — the stored OAuth token is no longer vali, fetch_blob_text() (+19 more)

### Community 4 - "Mongo Lifecycle & Collections"
Cohesion: 0.09
Nodes (15): lifespan(), Collections, Single source of truth for Mongo collection names.  Every Beanie `Document.Setti, Canonical collection names. Use these instead of string literals., client(), connect(), _database_name(), disconnect() (+7 more)

### Community 5 - "Command Detection"
Cohesion: 0.16
Nodes (28): detect_commands(), _js_commands(), _PkgJson, _python_test_command(), Detect (test_command, build_command) given the package manager + manifests., Return (test_command, build_command, dev_command) for the detected stack.      `, _stub_blobs(), test_bundler_with_rspec_in_gemfile() (+20 more)

### Community 6 - "Package Manager Detection"
Cohesion: 0.18
Nodes (25): detect_package_manager(), Detect package manager from filenames + (for ambiguous Python) a manifest blob., Filenames that sit at the repo root — package-manager signals only count     at, Return the project's package manager, or None.      `fetch_blob(path)` is the cu, _root_files(), _stub_blob(), test_build_gradle_means_gradle(), test_bun_lock() (+17 more)

### Community 7 - "Repo Models & Sandbox API"
Cohesion: 0.12
Nodes (15): session_info(), BaseModel, AvailableRepo, AvailableReposPage, ConnectedRepo, ConnectRepoRequest, Beanie models, raw collection access, and Mongo lifecycle helpers., Sandbox provider interface. Methods will be added in a later slice. (+7 more)

### Community 8 - "Agent Rules & Conventions"
Cohesion: 0.12
Nodes (24): agent_context.md cold-start primer, Always-update files, Banned dependencies, AGENTS.md canonical agent rules, Dependency & tooling constraints, Deviation protocol, Use graphify-out as your map, Read-before-write order (+16 more)

### Community 9 - "Auth Session Tests"
Cohesion: 0.13
Nodes (10): Document, Session, Settings, _seed_user_and_session(), test_logout_clears_session(), test_me_reports_no_reauth_when_token_set(), test_me_returns_user_with_valid_session(), test_session_returns_user_with_valid_cookie() (+2 more)

### Community 10 - "Primary Language Detection"
Cohesion: 0.23
Nodes (12): detect_primary_language(), _is_vendor(), Pick the primary language by counting recognised file extensions., Pick the language with the most files. Tie → alphabetical.      Vendor-dir files, test_alphabetical_tiebreak(), test_ignores_dist_and_venv(), test_ignores_node_modules(), test_ignores_unknown_extensions() (+4 more)

### Community 11 - "Frontend Repo API Client"
Cohesion: 0.29
Nodes (1): GithubReauthRequiredError

### Community 12 - "Smoke Tests"
Cohesion: 0.29
Nodes (1): test_imports()

### Community 13 - "Repo Introspection Architecture"
Cohesion: 0.33
Nodes (7): commands.py manifest-aware detector, github_source.py adapter (fetch_tree/fetch_blob_text), language.py detect_primary_language, introspect_via_github orchestrator entry, package_manager.py detector, repo_introspection package layout, Routes — connect inline + reintrospect + PATCH

### Community 14 - "User/Me API Routes"
Cohesion: 0.47
Nodes (4): get_user_optional(), require_user(), _resolve_user(), get_me()

### Community 15 - "Type Bridges (Pydantic→TS)"
Cohesion: 0.4
Nodes (5): Mandatory mental model (two invariants), Source-of-truth bridges, Rationale: DB shape ≠ API shape, Type bridges (Pydantic→OpenAPI→TS), Regenerating API types

### Community 16 - "Login Page UI"
Cohesion: 0.67
Nodes (0): 

### Community 17 - "Repo Map Docs"
Cohesion: 0.67
Nodes (3): Repo map, Repo layout, Repo layout summary

### Community 18 - "Bridge & Agent Runtime"
Cohesion: 0.67
Nodes (3): Bridge & agent runtime, Git workflow inside bridge, WebSocket protocol

### Community 19 - "Frontend Query Hooks"
Cohesion: 1.0
Nodes (0): 

### Community 20 - "Bridge Smoke Tests"
Cohesion: 1.0
Nodes (0): 

### Community 21 - "Health Endpoint Test"
Cohesion: 1.0
Nodes (0): 

### Community 22 - "Risks & Gotchas"
Cohesion: 1.0
Nodes (2): Gotchas list, Risks & known gotchas

### Community 23 - "Product Description"
Cohesion: 1.0
Nodes (2): Capabilities at v1, Product description

### Community 24 - "Community 24"
Cohesion: 1.0
Nodes (0): 

### Community 25 - "Community 25"
Cohesion: 1.0
Nodes (0): 

### Community 26 - "Community 26"
Cohesion: 1.0
Nodes (0): 

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (0): 

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (0): 

### Community 29 - "Community 29"
Cohesion: 1.0
Nodes (0): 

### Community 30 - "Community 30"
Cohesion: 1.0
Nodes (0): 

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (0): 

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (0): 

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (0): 

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (0): 

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (0): 

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (0): 

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (0): 

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (0): 

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (0): 

### Community 40 - "Community 40"
Cohesion: 1.0
Nodes (0): 

### Community 41 - "Community 41"
Cohesion: 1.0
Nodes (0): 

### Community 42 - "Community 42"
Cohesion: 1.0
Nodes (0): 

### Community 43 - "Community 43"
Cohesion: 1.0
Nodes (0): 

### Community 44 - "Community 44"
Cohesion: 1.0
Nodes (0): 

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (0): 

### Community 46 - "Community 46"
Cohesion: 1.0
Nodes (0): 

### Community 47 - "Community 47"
Cohesion: 1.0
Nodes (0): 

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (0): 

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (0): 

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (0): 

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (0): 

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (0): 

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Top-level layout

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Scaffold acceptance criteria

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Mental model — where types come from

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Backend change flow (5 steps)

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): Type generation flow

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (1): Frontend change flow (Layers A-E)

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (1): Context from the previous task

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (1): What 'done' looks like (slice 1)

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (1): GitHub OAuth setup (manual user step)

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (1): What to build (16 numbered subsections)

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (1): What's intentionally out of scope

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (1): Slice 1 acceptance criteria

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (1): Slice 1 hard rules — do not violate

### Community 77 - "Community 77"
Cohesion: 1.0
Nodes (1): Slice 1 when-done summary template

### Community 78 - "Community 78"
Cohesion: 1.0
Nodes (1): index.html #root mount + main.tsx entry

### Community 79 - "Community 79"
Cohesion: 1.0
Nodes (1): octo-canvas README

### Community 80 - "Community 80"
Cohesion: 1.0
Nodes (1): Modular and small files rule

### Community 81 - "Community 81"
Cohesion: 1.0
Nodes (1): Reuse before you write

### Community 82 - "Community 82"
Cohesion: 1.0
Nodes (1): Pyright strict + TS strict

### Community 83 - "Community 83"
Cohesion: 1.0
Nodes (1): Don't add what wasn't asked for

### Community 84 - "Community 84"
Cohesion: 1.0
Nodes (1): Verification before done

### Community 85 - "Community 85"
Cohesion: 1.0
Nodes (1): Personas & use cases

### Community 86 - "Community 86"
Cohesion: 1.0
Nodes (1): Observability

### Community 87 - "Community 87"
Cohesion: 1.0
Nodes (1): Slice 3 hard rules

### Community 88 - "Community 88"
Cohesion: 1.0
Nodes (1): Slice 2 hard rules

## Knowledge Gaps
- **91 isolated node(s):** `Liveness + Mongo reachability. 503 if Mongo is down so load balancers     drop u`, `Send the user to the GitHub OAuth-app settings page where they can grant     or`, `Merge user overrides on top of detected values. Non-None override fields     win`, `Run introspection against GitHub and persist on `doc`.      `GithubReauthRequire`, `Replace the user's overrides for this repo (full replacement, not merge).      S` (+86 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Frontend Query Hooks`** (2 nodes): `queries.ts`, `availableReposQueryOptions()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bridge Smoke Tests`** (2 nodes): `test_smoke.py`, `test_bridge_imports()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Health Endpoint Test`** (2 nodes): `test_health.py`, `test_health()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Risks & Gotchas`** (2 nodes): `Gotchas list`, `Risks & known gotchas`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Product Description`** (2 nodes): `Capabilities at v1`, `Product description`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 24`** (1 nodes): `schema.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 25`** (1 nodes): `schema.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (1 nodes): `index.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (1 nodes): `tailwind.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (1 nodes): `vite.config.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (1 nodes): `postcss.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (1 nodes): `main.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (1 nodes): `vite-env.d.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (1 nodes): `routeTree.gen.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (1 nodes): `api.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (1 nodes): `index.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (1 nodes): `__root.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (1 nodes): `_authed.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (1 nodes): `index.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (1 nodes): `connect.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 42`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 46`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (1 nodes): `main.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `Top-level layout`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `Scaffold acceptance criteria`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `Mental model — where types come from`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `Backend change flow (5 steps)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `Type generation flow`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `Frontend change flow (Layers A-E)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `Context from the previous task`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `What 'done' looks like (slice 1)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (1 nodes): `GitHub OAuth setup (manual user step)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `What to build (16 numbered subsections)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (1 nodes): `What's intentionally out of scope`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `Slice 1 acceptance criteria`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `Slice 1 hard rules — do not violate`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 77`** (1 nodes): `Slice 1 when-done summary template`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 78`** (1 nodes): `index.html #root mount + main.tsx entry`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 79`** (1 nodes): `octo-canvas README`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 80`** (1 nodes): `Modular and small files rule`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 81`** (1 nodes): `Reuse before you write`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 82`** (1 nodes): `Pyright strict + TS strict`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 83`** (1 nodes): `Don't add what wasn't asked for`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 84`** (1 nodes): `Verification before done`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 85`** (1 nodes): `Personas & use cases`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 86`** (1 nodes): `Observability`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 87`** (1 nodes): `Slice 3 hard rules`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 88`** (1 nodes): `Slice 2 hard rules`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `introspect_via_github()` connect `GitHub OAuth Wrapper` to `Repo Introspection Tests`, `Primary Language Detection`, `Command Detection`, `Package Manager Detection`?**
  _High betweenness centrality (0.158) - this node is a cross-community bridge._
- **Why does `RepoIntrospection` connect `Repo Introspection Tests` to `GitHub OAuth Wrapper`, `Repo Models & Sandbox API`?**
  _High betweenness centrality (0.118) - this node is a cross-community bridge._
- **Why does `Beanie models, raw collection access, and Mongo lifecycle helpers.` connect `Repo Models & Sandbox API` to `Repo Introspection Tests`, `GitHub OAuth Wrapper`, `Mongo Lifecycle & Collections`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `_seed_user_and_session()` (e.g. with `User` and `Session`) actually correct?**
  _`_seed_user_and_session()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `detect_commands()` (e.g. with `test_returns_triple_none_when_pm_is_none()` and `test_pnpm_with_test_build_dev_scripts()`) actually correct?**
  _`detect_commands()` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `detect_package_manager()` (e.g. with `test_pnpm_lock_wins()` and `test_yarn_lock()`) actually correct?**
  _`detect_package_manager()` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `RepoIntrospection` (e.g. with `Stub `introspect_via_github` imported into the routes module.      Default: retu` and `Non-401 introspection failures must not block the connection.`) actually correct?**
  _`RepoIntrospection` has 19 INFERRED edges - model-reasoned connections that need verification._