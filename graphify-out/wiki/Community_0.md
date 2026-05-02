# Community 0

> 94 nodes

## Key Concepts

- **TaskFanout** (28 connections) — `apps/orchestrator/src/orchestrator/ws/task_fanout.py`
- **DebugEvent** (17 connections) — `python_packages/shared_models/src/shared_models/wire_protocol/events.py`
- **Subscription** (16 connections) — `apps/orchestrator/src/orchestrator/ws/task_fanout.py`
- **append_event()** (15 connections) — `apps/orchestrator/src/orchestrator/services/event_store.py`
- **test_ws_web.py** (14 connections) — `apps/orchestrator/tests/test_ws_web.py`
- **Task** (12 connections) — `python_packages/db/src/db/models/task.py`
- **test_append_event_round_trip_via_fanout()** (11 connections) — `apps/orchestrator/tests/test_task_fanout.py`
- **.subscribe()** (11 connections) — `apps/orchestrator/src/orchestrator/ws/task_fanout.py`
- **_seed_user_session()** (10 connections) — `apps/orchestrator/tests/test_ws_web.py`
- **ws_server()** (10 connections) — `apps/orchestrator/tests/test_ws_web.py`
- **lifespan()** (10 connections) — `apps/orchestrator/src/orchestrator/app.py`
- **create_task()** (10 connections) — `apps/orchestrator/src/orchestrator/routes/internal.py`
- **_run_session()** (10 connections) — `apps/orchestrator/src/orchestrator/ws/web.py`
- **.start()** (10 connections) — `apps/orchestrator/src/orchestrator/ws/task_fanout.py`
- **.aclose()** (10 connections) — `python_packages/sandbox_provider/src/sandbox_provider/sprites.py`
- **test_subscriber_receives_published_event()** (9 connections) — `apps/orchestrator/tests/test_task_fanout.py`
- **test_cross_instance_fanout()** (9 connections) — `apps/orchestrator/tests/test_task_fanout.py`
- **test_backpressure_records_dropped_seq()** (9 connections) — `apps/orchestrator/tests/test_task_fanout.py`
- **web.py** (9 connections) — `apps/orchestrator/src/orchestrator/ws/web.py`
- **.stop()** (9 connections) — `apps/orchestrator/src/orchestrator/ws/task_fanout.py`
- **_connect()** (8 connections) — `apps/orchestrator/tests/test_ws_web.py`
- **test_event_store.py** (8 connections) — `apps/orchestrator/tests/test_event_store.py`
- **_make_task()** (8 connections) — `apps/orchestrator/tests/test_event_store.py`
- **test_unsubscribe_removes_channel_when_last_drops()** (8 connections) — `apps/orchestrator/tests/test_task_fanout.py`
- **event_store.py** (8 connections) — `apps/orchestrator/src/orchestrator/services/event_store.py`
- *... and 69 more nodes in this community*

## Relationships

- [[Community 4]] (12 shared connections)
- [[Community 10]] (6 shared connections)
- [[Community 2]] (5 shared connections)
- [[Community 3]] (5 shared connections)
- [[Community 13]] (4 shared connections)
- [[Community 15]] (4 shared connections)
- [[Community 11]] (2 shared connections)
- [[Community 12]] (1 shared connections)
- [[Community 8]] (1 shared connections)
- [[Community 6]] (1 shared connections)

## Source Files

- `apps/orchestrator/src/orchestrator/app.py`
- `apps/orchestrator/src/orchestrator/routes/internal.py`
- `apps/orchestrator/src/orchestrator/services/event_store.py`
- `apps/orchestrator/src/orchestrator/ws/task_fanout.py`
- `apps/orchestrator/src/orchestrator/ws/web.py`
- `apps/orchestrator/tests/conftest.py`
- `apps/orchestrator/tests/test_event_store.py`
- `apps/orchestrator/tests/test_task_fanout.py`
- `apps/orchestrator/tests/test_ws_web.py`
- `python_packages/db/src/db/models/task.py`
- `python_packages/db/src/db/mongo.py`
- `python_packages/sandbox_provider/src/sandbox_provider/sprites.py`
- `python_packages/sandbox_provider/tests/test_sprites.py`
- `python_packages/shared_models/src/shared_models/wire_protocol/events.py`

## Audit Trail

- EXTRACTED: 254 (50%)
- INFERRED: 251 (50%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*