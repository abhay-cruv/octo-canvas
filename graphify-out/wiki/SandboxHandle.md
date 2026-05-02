# SandboxHandle

> God node · 34 connections · `python_packages/sandbox_provider/src/sandbox_provider/interface.py`

**Community:** [[Community 8]]

## Connections by Relation

### calls
- [[.create()]] `INFERRED`
- [[_handle_of()]] `INFERRED`
- [[test_pause_kills_each_session_via_kill_endpoint()]] `INFERRED`
- [[test_pause_404_on_kill_is_swallowed()]] `INFERRED`
- [[test_wake_forces_running()]] `INFERRED`
- [[test_refresh_resyncs_status()]] `INFERRED`
- [[test_status_maps_sprite_states()]] `INFERRED`
- [[test_wake_issues_no_op_command_and_returns_state()]] `INFERRED`
- [[test_pause_with_no_sessions_just_refreshes_status()]] `INFERRED`
- [[_handle_of()]] `INFERRED`
- [[test_destroy_idempotent()]] `INFERRED`
- [[test_destroy_404_is_idempotent()]] `INFERRED`
- [[test_status_404_raises_non_retriable()]] `INFERRED`
- [[test_handle_for_wrong_provider_raises()]] `INFERRED`
- [[test_pause_not_found_raises()]] `INFERRED`
- [[test_status_for_wrong_provider_raises()]] `INFERRED`
- [[_to_handle()]] `INFERRED`

### contains
- [[interface.py]] `EXTRACTED`

### rationale_for
- [[Provider-opaque sandbox identity. Persisted on `Sandbox.provider_handle`     in]] `EXTRACTED`

### uses
- [[MockSandboxProvider]] `INFERRED`
- [[Beanie models, raw collection access, and Mongo lifecycle helpers.]] `INFERRED`
- [[SpritesProvider]] `INFERRED`
- [[_SpriteRecord]] `INFERRED`
- [[SpritesProvider — `sprites-py` SDK behind the SandboxProvider Protocol.  The SDK]] `INFERRED`
- [[Wraps `sprites-py.SpritesClient`. The SDK is sync; we offload to a     thread so]] `INFERRED`
- [[Force a `cold` sprite to `warm`/`running` by issuing a no-op exec.         Sprit]] `INFERRED`
- [[Force the sprite to release compute by killing all active exec         sessions;]] `INFERRED`
- [[List directory contents via raw HTTP — rc37 SDK doesn't expose         `list_fil]] `INFERRED`
- [[Take a checkpoint via the SDK. `create_checkpoint` returns a         streaming `]] `INFERRED`
- [[Coerce SDK byte-or-str output to text. The Exec result fields are     bytes; the]] `INFERRED`
- [[Strip any token-shaped substring before persisting/logging an error.]] `INFERRED`
- [[5xx-shaped errors get retried by the orchestrator's caller; 4xx don't.     The S]] `INFERRED`
- [[In-memory `SandboxProvider` for local dev + tests.  Models Sprites' semantics: -]] `INFERRED`
- [[Simulate Sprites' idle-hibernation transition for tests.]] `INFERRED`

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*