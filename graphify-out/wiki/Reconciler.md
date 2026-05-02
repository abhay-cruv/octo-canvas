# Reconciler

> God node · 34 connections · `apps/orchestrator/src/orchestrator/services/reconciliation.py`

**Community:** [[Community 2]]

## Connections by Relation

### calls
- [[lifespan()]] `INFERRED`
- [[test_reconcile_apt_install_dedup_across_repos()]] `INFERRED`
- [[client()]] `INFERRED`
- [[test_reconcile_clones_pending_repos()]] `INFERRED`
- [[test_reconcile_clone_fails_without_token()]] `INFERRED`
- [[test_reconcile_serializes_concurrent_triggers()]] `INFERRED`
- [[test_reconcile_removes_orphan_dirs()]] `INFERRED`
- [[test_reconcile_noop_takes_no_checkpoint()]] `INFERRED`
- [[test_reconcile_skips_when_sandbox_destroyed()]] `INFERRED`
- [[test_reconcile_skips_unknown_sandbox()]] `INFERRED`

### contains
- [[reconciliation.py]] `EXTRACTED`

### method
- [[._run()]] `EXTRACTED`
- [[.reconcile()]] `EXTRACTED`
- [[._ensure_git_setup()]] `EXTRACTED`
- [[._clone_one()]] `EXTRACTED`
- [[.__init__()]] `EXTRACTED`

### rationale_for
- [[One per-orchestrator-process. Holds a `SandboxProvider` reference;     routes pu]] `EXTRACTED`

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
- [[Reconciliation service — slice 5b.]] `INFERRED`
- [[FastAPI dependencies that resolve request-scoped collaborators (provider, manage]] `INFERRED`
- [[Merge user overrides on top of detected values. Non-None override fields     win]] `INFERRED`
- [[Run introspection against GitHub and persist on `doc`.      `GithubReauthRequire]] `INFERRED`
- [[Schedule reconciliation in the background. Mirrors the helper in     `routes.san]] `INFERRED`
- [[Manual retry for a `failed` clone. Flips status back to `pending`     and kicks]] `INFERRED`
- [[Replace the user's overrides for this repo (full replacement, not merge).      S]] `INFERRED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*