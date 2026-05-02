# Community 4

> 61 nodes

## Key Concepts

- **Collections** (25 connections) — `python_packages/db/src/db/collections.py`
- **mongo.py** (15 connections) — `python_packages/db/src/db/mongo.py`
- **User** (11 connections) — `python_packages/db/src/db/models/user.py`
- **test_auth.py** (10 connections) — `apps/orchestrator/tests/test_auth.py`
- **Mongo** (10 connections) — `python_packages/db/src/db/mongo.py`
- **Session** (9 connections) — `python_packages/db/src/db/models/session.py`
- **_seed_user_and_session()** (8 connections) — `apps/orchestrator/tests/test_auth.py`
- **Document** (6 connections)
- **Liveness + Mongo reachability. 503 if Mongo is down so load balancers     drop u** (4 connections) — `apps/orchestrator/src/orchestrator/app.py`
- **.connect()** (4 connections) — `python_packages/db/src/db/mongo.py`
- **.ping()** (4 connections) — `python_packages/db/src/db/mongo.py`
- **task.py** (4 connections) — `python_packages/db/src/db/models/task.py`
- **agent_event.py** (4 connections) — `python_packages/db/src/db/models/agent_event.py`
- **AgentEvent** (4 connections) — `python_packages/db/src/db/models/agent_event.py`
- **test_logout_clears_session()** (3 connections) — `apps/orchestrator/tests/test_auth.py`
- **health()** (3 connections) — `apps/orchestrator/src/orchestrator/app.py`
- **user.py** (3 connections) — `python_packages/db/src/db/models/user.py`
- **session.py** (3 connections) — `python_packages/db/src/db/models/session.py`
- **sandbox.py** (3 connections) — `python_packages/db/src/db/models/sandbox.py`
- **Settings** (3 connections) — `python_packages/db/src/db/models/agent_event.py`
- **test_session_returns_user_with_valid_cookie()** (2 connections) — `apps/orchestrator/tests/test_auth.py`
- **test_me_returns_user_with_valid_session()** (2 connections) — `apps/orchestrator/tests/test_auth.py`
- **test_me_reports_no_reauth_when_token_set()** (2 connections) — `apps/orchestrator/tests/test_auth.py`
- **_database_name()** (2 connections) — `python_packages/db/src/db/mongo.py`
- **.collection()** (2 connections) — `python_packages/db/src/db/mongo.py`
- *... and 36 more nodes in this community*

## Relationships

- [[Community 0]] (12 shared connections)
- [[Community 6]] (9 shared connections)
- [[Community 9]] (5 shared connections)
- [[Community 2]] (3 shared connections)
- [[Community 13]] (2 shared connections)
- [[Community 3]] (2 shared connections)
- [[Community 10]] (2 shared connections)
- [[Community 12]] (2 shared connections)
- [[Community 15]] (2 shared connections)

## Source Files

- `apps/orchestrator/src/orchestrator/app.py`
- `apps/orchestrator/tests/test_auth.py`
- `python_packages/db/src/db/collections.py`
- `python_packages/db/src/db/models/agent_event.py`
- `python_packages/db/src/db/models/sandbox.py`
- `python_packages/db/src/db/models/session.py`
- `python_packages/db/src/db/models/task.py`
- `python_packages/db/src/db/models/user.py`
- `python_packages/db/src/db/mongo.py`

## Audit Trail

- EXTRACTED: 127 (65%)
- INFERRED: 68 (35%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*