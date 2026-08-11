# 42. Telemetría de agentes (OTel) — 6 métricas para el taller

**Status:** 📋 proposed
**Estimate:** ~6 hrs
**Depends on:** Plan 43 (agente de diagnóstico) y Plan 44 (copiloto de tuning) — los agentes que se instrumentan; Plan 12/23 (Logfire/OTel ya en el repo).
**Objetivo docente:** dar un taller sobre telemetría de agentes usando este repo.

## Intent

Instrumentar los **agentes genuinos** del repo — Plan 43 (diagnóstico de trazas) y Plan 44
(copiloto de tuning) — con las **buenas prácticas de OpenTelemetry para agentes** del artículo de
referencia, dejarlas **bien integradas y mapeadas** para exponerlas en un taller. Solo estos
agentes (con tools + loop dinámico) dan las 6 métricas *completas*; el workflow de reporte de voz
(Plan 41) aporta las 4 que aplican (1/3/5/6), sin tool-calls ni iterations. Las seis métricas:

1. **Token Usage per Agent Run** — tokens de entrada y salida por operación/subagente.
2. **Tool Call Success Rate** — % de invocaciones de tool exitosas.
3. **LLM Latency Distribution** — tiempo de request → respuesta del LLM.
4. **Agent Loop Iterations** — ciclos ReAct antes de completar la tarea.
5. **Context Window Utilization** — % del contexto disponible consumido.
6. **End-to-End Agent Latency** — tiempo total de request → respuesta final.

Referencia: <https://www.mintmcp.com/blog/opentelemetry-ai-agents>.

El repo ya tiene dos capas ganadas: (a) **traces automáticos** — `instrument_pydantic_ai()` +
`instrument_httpx()` ya emiten, por cada llamada al modelo, **tokens de entrada/salida y duración**
como atributos de span; (b) **métricas de app** en `observability.py`, hoy solo cableadas en
`/triage`. Lo que falta es un **agente con tools + loop** (lo traen Plan 43/44) y los **instrumentos
de métrica agregables** para ver las 6 KPIs como distribuciones/tasas y no solo como traces sueltos.
Este plan **agrega los instrumentos que faltan**, los **cablea** en los agentes de Plan 43/44 (y en
el workflow de Plan 41 para las 4 que aplican), y produce el **material del taller** (mapeo métrica →
span/atributo → query de Logfire).

## Prior reading

- [observability.py](../../email_triage/observability.py) — catálogo actual de counters/histogramas.
- [routers/triage.py](../../email_triage/routers/triage.py) — `LLM_LATENCY_MS` **sí** se emite aquí (`triage.py:79`, `/triage sync`, etiquetado por endpoint); este plan lo **extiende** al path del agente (por-subagente), no lo resucita.
- [services/llm.py](../../email_triage/services/llm.py) — patrón `Agent` de pydantic-ai; `result.usage()` (request/response tokens) es de dónde salen los tokens.
- [services/trace_agent.py](../../email_triage/services/trace_agent.py) (Plan 43) y `services/tuning/` (Plan 44) — los agentes con tools + loop donde cuelgan las 6 métricas.
- [charla-observabilidad-evals/](../../charla-observabilidad-evals/) — material de charla existente; aquí se agrega la sección de agentes.
- pydantic-ai: `RunResult.usage()` (`request_tokens`, `response_tokens`, `total_tokens`, `requests`), `RunResult.all_messages()` para contar pasos del loop.

## Scope

**Incluido — instrumentos nuevos en `observability.py`:**

| # | Métrica del blog | Instrumento OTel | Atributos (baja cardinalidad) |
|---|---|---|---|
| 1 | Token Usage per Agent Run | `AGENT_INPUT_TOKENS`, `AGENT_OUTPUT_TOKENS` (Histogram) | `agent` (diagnosis/tuning) |
| 2 | Tool Call Success Rate | `TOOL_CALLS_TOTAL` (Counter) | `tool` (get_trace_spans/diagnose/run_eval/…), `outcome` (ok/error) |
| 3 | LLM Latency Distribution | `AGENT_LLM_LATENCY_MS` (Histogram) | `agent` |
| 4 | Agent Loop Iterations | `AGENT_LOOP_ITERATIONS` (Histogram) | `agent` |
| 5 | Context Window Utilization | `CONTEXT_UTILIZATION` (Histogram, ratio) | `agent`, `model` |
| 6 | End-to-End Agent Latency | `AGENT_E2E_LATENCY_MS` (Histogram) | `agent` |

**Cableado (en Plan 43/44):**
- Un helper `instrument_agent_run(agent_name, model, run_coro)` que envuelve `agent.run(...)`:
  mide latencia, lee `result.usage()` → tokens 1 y 3, calcula `input_tokens / model_max_context`
  → métrica 5, cuenta `result.requests`/pasos → métrica 4, y setea los mismos valores como
  atributos del span del agente.
- Las tools de **Plan 43** (`get_trace_spans`, `search_recent_org_traces`) y las de **Plan 44**
  (`diagnose`, `add_counter_example`, `tweak_category`, `preview_prompt`, `run_eval`) registran
  `TOOL_CALLS_TOTAL{tool, outcome}` (try/except) → métrica 2. El copiloto (Plan 44) es donde más
  brilla: el loop refinar↔evaluar genera muchas tool-calls e iteraciones.
- `diagnose_trace` (Plan 43) y `run_tuning` (Plan 44) miden `AGENT_E2E_LATENCY_MS` alrededor del
  run → métrica 6.
- Constante `MODEL_MAX_CONTEXT` (p.ej. llama-3.3-70b ≈ 128k) para el ratio de la métrica 5.

**Material del taller (`charla-observabilidad-evals/`):**
- `agentes-telemetria.md`: cada métrica → qué es → dónde se emite (span/atributo) → **query de
  Logfire** para graficarla → qué decisión de diseño habilita (p.ej. utilización de contexto alta
  ⇒ compactar/particionar).
- Tabla de mapeo directa a las 6 del blog, citando las buenas prácticas de baja cardinalidad ya
  vigentes en `observability.py`.

**Tests:**
- Con `TestModel`/`FunctionModel` (sin Groq): que un run del agente **emita** los 6 instrumentos
  con los atributos esperados (usar un `InMemoryMetricReader`/exporter de OTel para aserciones),
  y que una tool que lanza excepción registre `outcome=error`.

**Fuera de scope:**
- Dashboards/paneles como código en Logfire (se documentan las queries; crear el panel es manual).
- Instrumentar el path de `/triage` existente con las 6 (este plan se centra en los agentes de Plan
  43/44; las métricas 1/3/5/6 son extensibles a `/triage` y al workflow de Plan 41 en un follow-up).
- Alertas/SLOs sobre estas métricas (v2).

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Métricas OTel explícitas + atributo `agent` | Confiar solo en los spans auto de pydantic-ai | El blog pide *métricas* agregables (distribuciones, tasas); los spans solos no dan histogramas listos |
| Atributos de baja cardinalidad (`agent`, `tool`, `outcome`, `model`) | Incluir `message_id`/tenant en labels | Regla ya vigente en `observability.py`: nada de alta cardinalidad en labels |
| Utilización de contexto = `input_tokens / MODEL_MAX_CONTEXT` | Tokenizador propio | `usage()` ya da los tokens reales; una constante por modelo basta para el ratio |
| Loop iterations desde `result.requests`/pasos de pydantic-ai | Contador manual dentro del loop | Menos código, misma señal; pydantic-ai ya expone los pasos del run |
| Helper `instrument_agent_run` reutilizable | Instrumentar inline en cada agente | Un solo lugar para las métricas 1/3/4/5; consistencia y menos error |
| `AGENT_LLM_LATENCY_MS{agent}` nuevo para el path del agente | Reusar `LLM_LATENCY_MS{endpoint}` de `/triage` | Semántica distinta (por-subagente vs por-endpoint); no mezclar dimensiones en un mismo histograma |

## Mapeo blog → repo (resumen del taller)

```
Token Usage per Agent Run    → AGENT_INPUT/OUTPUT_TOKENS{agent}      ← result.usage()
Tool Call Success Rate       → TOOL_CALLS_TOTAL{tool,outcome}        ← try/except en tools.py
LLM Latency Distribution     → AGENT_LLM_LATENCY_MS{agent}           ← timer alrededor de agent.run
Agent Loop Iterations        → AGENT_LOOP_ITERATIONS{agent}          ← result.requests / pasos
Context Window Utilization   → CONTEXT_UTILIZATION{agent,model}      ← input_tokens / MODEL_MAX_CONTEXT
End-to-End Agent Latency     → AGENT_E2E_LATENCY_MS{agent}           ← timer en run_tuning / diagnose_trace
```

## Risks / Open questions

- **`usage()` con Groq/pydantic-ai:** confirmar que el provider reporta `request_tokens`/
  `response_tokens` de forma fiable; si algún campo viene `None`, degradar (no romper el run).
- **Context window real:** `MODEL_MAX_CONTEXT` es por-modelo y hardcodeado; si se cambia de modelo
  hay que actualizarlo. Documentarlo como constante única.
- **Doble conteo tokens:** pydantic-ai + logfire ya pueden emitir usage en spans; asegurarse de no
  contar dos veces la misma llamada (métrica se emite una vez por `agent.run`).
- **Cardinalidad:** mantener `agent`/`tool`/`outcome`/`model` acotados; jamás meter tenant/ids.
- **Aserción de métricas en test:** usar el `MetricReader` en memoria de OTel; verificar que Logfire
  no intercepte el pipeline de métricas en el entorno de test.

## Execution order

1. Instrumentos nuevos en `observability.py` (6 métricas) (45 min).
2. Helper `instrument_agent_run` + `MODEL_MAX_CONTEXT` (60 min).
3. Cablear en Plan 43/44: `agent.run` (1/3/4/5), tools (2), e2e (6) (90 min).
4. Tests con exporter OTel en memoria (emisión + `outcome=error`) (90 min).
5. Material del taller `agentes-telemetria.md` + tabla de mapeo + queries Logfire (75 min).
6. Doc `42-*`; `make check` verde.

## Done when

- [ ] Un run de `/workspaces/{tid}/tune` (Plan 44) emite las 6 métricas con los atributos de la tabla
- [ ] `TOOL_CALLS_TOTAL` distingue `ok`/`error` (permite calcular la tasa de éxito)
- [ ] `AGENT_LOOP_ITERATIONS` refleja los pasos reales del loop del copiloto/diagnóstico
- [ ] `CONTEXT_UTILIZATION` = input_tokens / contexto del modelo, como ratio 0–1
- [ ] `AGENT_E2E_LATENCY_MS` cubre el run del orquestador completo; `AGENT_LLM_LATENCY_MS` por subagente
- [ ] Las 6 KPIs se ven en Logfire como **métricas** (distribución/tasa), no solo como traces sueltos
- [ ] `charla-observabilidad-evals/agentes-telemetria.md` mapea las 6 del blog a span/atributo/query
- [ ] Tests aseveran emisión de métricas sin tocar Groq/red — `CLAUDE.md`
- [ ] `make check` verde (ruff + pyright 0 + tests)
- [ ] Ensayo del taller: las 6 métricas se ven en Logfire tras un run real
