# Testing: tenant_id on every span (baggage)

## Prerequisites

- Suite: `uv run pytest tests/test_tenant_baggage.py` (usa `logfire.testing.capfire`, sin red).

## Test Cases (automáticos)

### TC-01: el root de sync lleva tenant_id
**Action**: `POST /triage`. **Expected**: el span `triage.sync` tiene el atributo `tenant_id`.

### TC-02: el root de stream lleva tenant_id (regresión)
**Action**: `POST /triage/stream`. **Expected**: el span `triage.stream` tiene `tenant_id`
(antes de Plan 33 no lo tenía).

### TC-03: un span hijo hereda tenant_id vía baggage
**Action**: doble de LLM que abre un span hijo (`llm.fake_call`) dentro de `triage()`.
**Expected**: el span hijo tiene `tenant_id` y su valor coincide con el del root `triage.sync`.

> Nota: sin DB, `tenant_id` resuelve al string `"None"`; el test verifica la **presencia** del
> atributo (el cableado), no un valor de tenant concreto.

## Manual end-to-end (con Logfire real)

1. Con una workspace real logueada y `LOGFIRE_TOKEN` (escritura) activo, correr un `POST
   /triage` (sync).
2. En Logfire, abrir ese trace: el span raíz **y** los hijos (llamada al modelo / httpx) deben
   mostrar `tenant_id = <uuid de la org>`.
3. Consultar `SELECT span_name, attributes->>'tenant_id' FROM records WHERE trace_id = '<id>'`
   → todas las filas con el mismo `tenant_id`.

## Gates

`uv run ruff format && uv run ruff check && uv run pyright && uv run pytest` — verde.
