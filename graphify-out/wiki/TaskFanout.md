# TaskFanout

> God node · 28 connections · `apps/orchestrator/src/orchestrator/ws/task_fanout.py`

**Community:** [[Community 0]]

## Connections by Relation

### calls
- [[test_append_event_round_trip_via_fanout()]] `INFERRED`
- [[ws_server()]] `INFERRED`
- [[lifespan()]] `INFERRED`
- [[test_subscriber_receives_published_event()]] `INFERRED`
- [[test_cross_instance_fanout()]] `INFERRED`
- [[test_backpressure_records_dropped_seq()]] `INFERRED`
- [[test_unsubscribe_removes_channel_when_last_drops()]] `INFERRED`

### contains
- [[task_fanout.py]] `EXTRACTED`

### method
- [[.subscribe()]] `EXTRACTED`
- [[.start()]] `EXTRACTED`
- [[.stop()]] `EXTRACTED`
- [[._reader_loop()]] `EXTRACTED`
- [[.unsubscribe()]] `EXTRACTED`
- [[._dispatch()]] `EXTRACTED`
- [[.__init__()]] `EXTRACTED`

### rationale_for
- [[Per-instance Redis pub/sub multiplex. Owns one PubSub.      Thread-safety: singl]] `EXTRACTED`

### uses
- [[Liveness + Mongo reachability. 503 if Mongo is down so load balancers     drop u]] `INFERRED`
- [[_HeartbeatTimeoutError]] `INFERRED`
- [[TaskFanout: cross-instance fanout via real Redis pub/sub.]] `INFERRED`
- [[Two TaskFanout instances against the same Redis: instance A publishes,     insta]] `INFERRED`
- [[Queue full → fanout drops + advances `last_dropped_seq` so the WS     layer can]] `INFERRED`
- [[End-to-end: `append_event` publishes → fanout dispatches → subscriber     receiv]] `INFERRED`
- [[WebSocket handler for `/ws/web/tasks/{task_id}` — slice 5a.  Auth via session co]] `INFERRED`
- [[Cookie-based auth on the WS handshake. Returns None on any failure     (caller c]] `INFERRED`
- [[Drive replay → live mode under heartbeat + backpressure rules.]] `INFERRED`
- [[WS handler /ws/web/tasks/{task_id} — auth + replay + happy path.  Drives a real]] `INFERRED`
- [[Spin up a real uvicorn on the SAME event loop as the test, so Beanie's     loop-]] `INFERRED`
- [[Connect, expect server-initiated close, return the close code.]] `INFERRED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*