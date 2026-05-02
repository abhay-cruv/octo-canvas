# Community 17

> 23 nodes

## Key Concepts

- **SandboxProvider** (14 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **.create()** (2 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **.status()** (2 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **.destroy()** (2 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **.wake()** (2 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **.pause()** (2 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **.exec_oneshot()** (2 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **.fs_list()** (2 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **.fs_delete()** (2 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **.snapshot()** (2 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **.restore()** (2 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **Protocol** (1 connections)
- **Sandbox provisioning operations — slice 4 surface.      `name` is the impl's dis** (1 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **Provision a new sandbox. `sandbox_id` is the Mongo `Sandbox._id`         (string** (1 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **Live status from the provider. Raises `SpritesError` if the         sandbox no l** (1 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **Tear down the sandbox AND its filesystem. Idempotent: a 404 from         the pro** (1 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **Force a `cold` sandbox to `warm`/`running`. Sprites auto-wakes on         any ex** (1 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **Force the sandbox to release compute (target `cold`).          Sprites has no ex** (1 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **Run `argv` inside the sandbox to completion. Captures stdout and         stderr.** (1 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **List entries in `path`. Raises `SpritesError(retriable=False)` if         the pa** (1 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **Delete `path`. `recursive=True` for directories. Idempotent: a         404 from** (1 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **Create a point-in-time checkpoint of the sandbox's filesystem.         Returns t** (1 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`
- **Roll the sandbox back to a previous checkpoint. Used by Reset to         avoid t** (1 connections) — `python_packages/sandbox_provider/src/sandbox_provider/interface.py`

## Relationships

- [[Community 10]] (1 shared connections)
- [[Community 8]] (1 shared connections)

## Source Files

- `python_packages/sandbox_provider/src/sandbox_provider/interface.py`

## Audit Trail

- EXTRACTED: 45 (98%)
- INFERRED: 1 (2%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*