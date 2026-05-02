# Community 13

> 32 nodes

## Key Concepts

- **app.py** (9 connections) — `apps/orchestrator/src/orchestrator/app.py`
- **logger.py** (7 connections) — `apps/orchestrator/src/orchestrator/lib/logger.py`
- **build_sandbox_provider()** (7 connections) — `apps/orchestrator/src/orchestrator/lib/provider_factory.py`
- **RedisClient** (6 connections) — `apps/orchestrator/src/orchestrator/lib/redis_client.py`
- **test_provider_startup.py** (5 connections) — `apps/orchestrator/tests/test_provider_startup.py`
- **_settings_with()** (5 connections) — `apps/orchestrator/tests/test_provider_startup.py`
- **env.py** (5 connections) — `apps/orchestrator/src/orchestrator/lib/env.py`
- **provider_factory.py** (5 connections) — `apps/orchestrator/src/orchestrator/lib/provider_factory.py`
- **redis_client.py** (5 connections) — `apps/orchestrator/src/orchestrator/lib/redis_client.py`
- **Settings** (4 connections) — `apps/orchestrator/src/orchestrator/lib/env.py`
- **main()** (3 connections) — `apps/bridge/src/bridge/__main__.py`
- **configure_logging()** (3 connections) — `apps/orchestrator/src/orchestrator/lib/logger.py`
- **get_logger()** (3 connections) — `apps/orchestrator/src/orchestrator/lib/logger.py`
- **test_sprites_with_empty_token_aborts()** (3 connections) — `apps/orchestrator/tests/test_provider_startup.py`
- **test_sprites_with_token_returns_sprites_provider()** (3 connections) — `apps/orchestrator/tests/test_provider_startup.py`
- **test_mock_returns_mock_provider()** (3 connections) — `apps/orchestrator/tests/test_provider_startup.py`
- **.connect()** (3 connections) — `apps/orchestrator/src/orchestrator/lib/redis_client.py`
- **_safe_url()** (3 connections) — `apps/orchestrator/src/orchestrator/lib/redis_client.py`
- **logger.py** (2 connections) — `apps/bridge/src/bridge/lib/logger.py`
- **Provider selection at startup must be explicit — no silent fallback when SPRITES** (2 connections) — `apps/orchestrator/tests/test_provider_startup.py`
- **.disconnect()** (2 connections) — `apps/orchestrator/src/orchestrator/lib/redis_client.py`
- **.ping()** (2 connections) — `apps/orchestrator/src/orchestrator/lib/redis_client.py`
- **__main__.py** (1 connections) — `apps/bridge/src/bridge/__main__.py`
- **env.py** (1 connections) — `apps/bridge/src/bridge/lib/env.py`
- **BaseSettings** (1 connections)
- *... and 7 more nodes in this community*

## Relationships

- [[Community 0]] (4 shared connections)
- [[Community 4]] (2 shared connections)
- [[Community 2]] (2 shared connections)
- [[Community 3]] (2 shared connections)
- [[Community 15]] (2 shared connections)
- [[Community 11]] (1 shared connections)
- [[Community 8]] (1 shared connections)

## Source Files

- `apps/bridge/src/bridge/__main__.py`
- `apps/bridge/src/bridge/lib/env.py`
- `apps/bridge/src/bridge/lib/logger.py`
- `apps/orchestrator/src/orchestrator/app.py`
- `apps/orchestrator/src/orchestrator/lib/env.py`
- `apps/orchestrator/src/orchestrator/lib/logger.py`
- `apps/orchestrator/src/orchestrator/lib/provider_factory.py`
- `apps/orchestrator/src/orchestrator/lib/redis_client.py`
- `apps/orchestrator/tests/test_provider_startup.py`

## Audit Trail

- EXTRACTED: 83 (83%)
- INFERRED: 17 (17%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [[index]] to navigate.*