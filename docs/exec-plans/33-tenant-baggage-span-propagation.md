# 33. Propagar `tenant_id` a `/triage/stream` y a los spans hijos (OTel baggage)

**Status:** 🚧 implemented (pending human review/merge)
**Estimate:** ~2 hrs
**Depends on:** Plan 12 (observabilidad Logfire).
**Relacionado:** Plan 31 (el trace-debug chat consulta por `tenant_id`; este plan amplía su cobertura).

## Intent

Hoy solo el span raíz de `/triage` **sync** etiqueta `tenant_id` (`routers/triage.py:63`). El span
de `/triage/stream` **no** lo etiqueta, y los **spans hijos** (pydantic-ai, httpx) tampoco lo
heredan —los atributos OTel no se propagan solos a los hijos—. Resultado: consultas filtradas por
`tenant_id` (p.ej. el agente del Plan 31, o cualquier dashboard por org) **pierden** los traces de
streaming y el detalle de las llamadas LLM/HTTP.

Este plan hace que **todo span de una request** lleve `tenant_id`, propagándolo por **OTel baggage**
en lugar de setearlo span por span.

## Prior reading

- `email_triage/routers/triage.py` — span sync (`:61`, setea `tenant_id`) vs span stream (`:102`,
  no lo setea).
- `email_triage/middleware.py` — dónde se resuelve el request/trace context.
- Logfire baggage: `logfire.set_baggage(...)` como context manager que adjunta atributos a los spans
  creados dentro de su alcance.
- MCP 2026-07-28 documenta propagación de contexto OTel (`traceparent`/`tracestate`/`baggage`) en
  `_meta` — consistente con este enfoque.

## Scope

**Incluido:**
- Setear `tenant_id` (y opcionalmente `endpoint`) como **baggage** al entrar en el path autenticado
  de `/triage` y `/triage/stream`, de modo que el span raíz **y todos los hijos** (pydantic-ai,
  httpx) lo lleven como atributo.
- Cubrir explícitamente el span de `/triage/stream`, que hoy no lo tiene.
- Verificar en un test/inspección que un span hijo (p.ej. la llamada del modelo) expone `tenant_id`.

**Fuera de scope:**
- Cambiar el esquema de métricas (`observability.py`) — las labels de baja cardinalidad siguen igual;
  `tenant_id` va en **spans/atributos**, no en métricas (cardinalidad alta).
- Backfill de traces históricos.

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/routers/triage.py` | envolver ambos handlers con `logfire.set_baggage(tenant_id=...)`; el span stream deja de quedar sin `tenant_id` |
| (opcional) `email_triage/middleware.py` | punto único para setear el baggage si el tenant se resuelve ahí |
| `tests/test_observability_tenant.py` | **nuevo/extend** — un span hijo lleva `tenant_id` |
| `docs/features/33-*`, `docs/testing/33-*` | docs |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| OTel **baggage** | `set_attribute("tenant_id", ...)` span por span | Baggage propaga a hijos (pydantic-ai/httpx) sin tocar cada span |
| `tenant_id` en spans, no en métricas | Añadirlo como label de métrica | Alta cardinalidad rompería las métricas (regla de `observability.py`) |
| Cubrir sync + stream | Solo stream | Uniformidad: toda consulta por org ve ambos endpoints |

## Risks / Open questions

- **Scrubbing/sampling:** confirmar que el baggage no queda scrubbeado y que el tail-sampler
  (`main.py:_tail_sampler`) no descarta spans que luego se quieren debuggear.
- **Cardinalidad:** `tenant_id` en atributos de span es correcto; **no** debe llegar a labels de
  métricas.
- **PII:** `tenant_id` es un UUID interno, no dato personal — ok para telemetría.

## Done when

- [x] El span de `/triage/stream` lleva `tenant_id`
- [x] Un span hijo (llamada LLM/httpx) expone `tenant_id` heredado por baggage
- [x] `make check` verde (ruff + pyright 0 + 196 tests); `docs/features/33-*` y `docs/testing/33-*`
- [ ] Humano validó con la guía de testing
