# SpritesError

> God node · 33 connections · `python_packages/sandbox_provider/src/sandbox_provider/interface.py`

**Community:** [[Community 8]]

## Connections by Relation

### calls
- [[.create()]] `INFERRED`
- [[_require_name()]] `INFERRED`
- [[._require()]] `INFERRED`
- [[.wake()]] `INFERRED`
- [[.pause()]] `INFERRED`
- [[.create()]] `INFERRED`
- [[.status()]] `INFERRED`
- [[.snapshot()]] `INFERRED`
- [[.restore()]] `INFERRED`
- [[.restore()]] `INFERRED`
- [[test_create_502_on_provider_failure_marks_failed()]] `INFERRED`
- [[test_reset_works_from_failed()]] `INFERRED`
- [[.destroy()]] `INFERRED`
- [[.exec_oneshot()]] `INFERRED`

### contains
- [[interface.py]] `EXTRACTED`

### inherits
- [[Exception]] `EXTRACTED`

### method
- [[.__init__()]] `EXTRACTED`

### rationale_for
- [[Wraps any error returned by the underlying provider. Sanitized — never     inclu]] `EXTRACTED`

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