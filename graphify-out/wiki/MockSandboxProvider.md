# MockSandboxProvider

> God node · 42 connections · `python_packages/sandbox_provider/src/sandbox_provider/mock.py`

**Community:** [[Community 2]]

## Connections by Relation

### calls
- [[_setup()]] `INFERRED`
- [[test_reconcile_apt_install_dedup_across_repos()]] `INFERRED`
- [[client()]] `INFERRED`
- [[test_reconcile_clones_pending_repos()]] `INFERRED`
- [[test_reconcile_clone_fails_without_token()]] `INFERRED`
- [[test_reconcile_serializes_concurrent_triggers()]] `INFERRED`
- [[build_sandbox_provider()]] `INFERRED`
- [[test_reset_wipes_workdir_keeps_sprite()]] `INFERRED`
- [[test_reset_falls_back_to_recreate_when_failed()]] `INFERRED`
- [[test_create_after_destroy_with_same_id_succeeds()]] `INFERRED`
- [[test_reconcile_removes_orphan_dirs()]] `INFERRED`
- [[test_reconcile_noop_takes_no_checkpoint()]] `INFERRED`
- [[test_reconcile_skips_when_sandbox_destroyed()]] `INFERRED`
- [[test_destroy_makes_status_raise()]] `INFERRED`
- [[test_destroy_idempotent()]] `INFERRED`
- [[test_wake_forces_running_from_cold()]] `INFERRED`
- [[test_pause_transitions_to_cold()]] `INFERRED`
- [[test_reconcile_skips_unknown_sandbox()]] `INFERRED`
- [[test_create_returns_warm_handle_with_url()]] `INFERRED`
- [[test_pause_idempotent_on_cold()]] `INFERRED`

### contains
- [[mock.py]] `EXTRACTED`

### method
- [[.create()]] `EXTRACTED`
- [[.status()]] `EXTRACTED`
- [[.exec_oneshot()]] `EXTRACTED`
- [[._require()]] `EXTRACTED`
- [[.pause()]] `EXTRACTED`
- [[.fs_list()]] `EXTRACTED`
- [[.destroy()]] `EXTRACTED`
- [[.wake()]] `EXTRACTED`
- [[.restore()]] `EXTRACTED`
- [[._force_cold()]] `EXTRACTED`
- [[.fs_delete()]] `EXTRACTED`
- [[.snapshot()]] `EXTRACTED`
- [[.__init__()]] `EXTRACTED`

### uses
- [[Beanie models, raw collection access, and Mongo lifecycle helpers.]] `INFERRED`
- [[SandboxHandle]] `INFERRED`
- [[SpritesError]] `INFERRED`
- [[SandboxState]] `INFERRED`
- [[ExecResult]] `INFERRED`
- [[FsEntry]] `INFERRED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*