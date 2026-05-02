# SandboxManager

> God node · 35 connections · `apps/orchestrator/src/orchestrator/services/sandbox_manager.py`

**Community:** [[Community 3]]

## Connections by Relation

### calls
- [[lifespan()]] `INFERRED`
- [[client()]] `INFERRED`
- [[test_reset_wipes_workdir_keeps_sprite()]] `INFERRED`
- [[test_reset_falls_back_to_recreate_when_failed()]] `INFERRED`

### contains
- [[sandbox_manager.py]] `EXTRACTED`

### method
- [[.reset()]] `EXTRACTED`
- [[._reset_via_recreate()]] `EXTRACTED`
- [[._provision()]] `EXTRACTED`
- [[._mark_failed()]] `EXTRACTED`
- [[.refresh_status()]] `EXTRACTED`
- [[.wake()]] `EXTRACTED`
- [[.get_or_create()]] `EXTRACTED`
- [[.pause()]] `EXTRACTED`
- [[.destroy()]] `EXTRACTED`
- [[._redis_write()]] `EXTRACTED`
- [[._redis_clear()]] `EXTRACTED`
- [[.__init__()]] `EXTRACTED`
- [[.list_for_user()]] `EXTRACTED`

### uses
- [[Sandbox wire-shape models — shared between orchestrator and (eventually) bridge.]] `INFERRED`
- [[If a transition flipped status to `failed`, surface 502 to the     caller. The d]] `INFERRED`
- [[Cancel every background task whose name starts with `<prefix>-<id>`.     Used to]] `INFERRED`
- [[Schedule a reconciliation pass without awaiting it. The HTTP     response return]] `INFERRED`
- [[Return the user's existing non-destroyed sandbox or provision a fresh     one. I]] `INFERRED`
- [[Force the sandbox to release compute. Kills active exec sessions     so Sprites']] `INFERRED`
- [[Re-sync the sandbox's live status once after pause so the Mongo     doc converge]] `INFERRED`
- [[Resync live status from the provider (cold/warm/running). Useful on     page foc]] `INFERRED`
- [[Liveness + Mongo reachability. 503 if Mongo is down so load balancers     drop u]] `INFERRED`
- [[Real Redis on the test DB (db 15). Flushes before AND after the test     so any]] `INFERRED`
- [[Reset on a healthy sandbox now wipes `/work` instead of     destroying+recreatin]] `INFERRED`
- [[Healthy reset wipes `/work` via `rm -rf /work && mkdir -p /work`     through exe]] `INFERRED`
- [[For every (from_status, action) pair, assert the correct outcome     (transition]] `INFERRED`
- [[FastAPI dependencies that resolve request-scoped collaborators (provider, manage]] `INFERRED`
- [[SandboxManager.reset — checkpoint fast path vs slow fallback.]] `INFERRED`
- [[Healthy Reset wipes `/work` via fs_delete; sprite identity     (`provider_handle]] `INFERRED`
- [[Failed sandboxes have a broken sprite — wiping `/work` won't     fix them, so re]] `INFERRED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*