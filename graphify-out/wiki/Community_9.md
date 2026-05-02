# Community 9

> 42 nodes

## Key Concepts

- **test_repos.py** (29 connections) — `apps/orchestrator/tests/test_repos.py`
- **_seed_user_and_session()** (26 connections) — `apps/orchestrator/tests/test_repos.py`
- **RepoIntrospection** (23 connections) — `python_packages/shared_models/src/shared_models/introspection.py`
- **Repo** (17 connections) — `python_packages/db/src/db/models/repo.py`
- **_seed_repo()** (12 connections) — `apps/orchestrator/tests/test_repos.py`
- **_patch_introspection()** (10 connections) — `apps/orchestrator/tests/test_repos.py`
- **introspect_via_github()** (9 connections) — `python_packages/repo_introspection/src/repo_introspection/orchestrate.py`
- **test_connect_allows_same_repo_for_different_users()** (8 connections) — `apps/orchestrator/tests/test_repos.py`
- **_patch_user_client()** (7 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_reintrospect_preserves_overrides()** (7 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_connect_swallows_introspection_failure()** (6 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_connect_propagates_reauth_from_introspection()** (6 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_connect_rejects_duplicate()** (6 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_reintrospect_happy_path()** (6 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_reintrospect_clears_token_on_reauth()** (6 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_connect_happy_path()** (5 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_list_connected_repos_empty_then_seeded()** (4 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_available_returns_paginated_with_is_connected()** (4 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_connect_rejects_id_mismatch()** (4 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_disconnect_removes_repo()** (4 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_disconnect_rejects_other_users_repo()** (4 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_reintrospect_returns_reauth_when_token_missing()** (4 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_reintrospect_404_for_other_users_repo()** (4 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_overrides_set_then_clear()** (4 connections) — `apps/orchestrator/tests/test_repos.py`
- **test_overrides_visible_when_no_detection_yet()** (4 connections) — `apps/orchestrator/tests/test_repos.py`
- *... and 17 more nodes in this community*

## Relationships

- [[Community 2]] (14 shared connections)
- [[Community 6]] (13 shared connections)
- [[Community 10]] (9 shared connections)
- [[Community 11]] (6 shared connections)
- [[Community 4]] (5 shared connections)
- [[Community 19]] (1 shared connections)
- [[Community 16]] (1 shared connections)
- [[Community 18]] (1 shared connections)
- [[Community 20]] (1 shared connections)
- [[Community 14]] (1 shared connections)

## Source Files

- `apps/orchestrator/tests/test_repos.py`
- `python_packages/db/src/db/models/repo.py`
- `python_packages/repo_introspection/src/repo_introspection/orchestrate.py`
- `python_packages/shared_models/src/shared_models/introspection.py`

## Audit Trail

- EXTRACTED: 168 (66%)
- INFERRED: 88 (34%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*