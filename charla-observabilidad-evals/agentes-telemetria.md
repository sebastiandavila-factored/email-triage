# Telemetría de agentes con OpenTelemetry (taller)

Cómo instrumentamos los **agentes reales** de este repo — el de **diagnóstico** (Plan 43) y el
**copiloto de tuning** (Plan 44) — con las 6 buenas prácticas de OpenTelemetry-for-agents del
artículo de referencia, y cómo verlas en **Logfire**.

Referencia: <https://www.mintmcp.com/blog/opentelemetry-ai-agents>

## Dos capas de telemetría

1. **Traces (automático).** `logfire.instrument_pydantic_ai()` + `instrument_httpx()`
   ([main.py](../email_triage/main.py)) ya emiten, por **cada llamada al modelo**, un span con
   tokens y duración. Sirve para *depurar un run puntual* (ver el árbol de spans).
2. **Métricas (Plan 42).** Para ver **distribuciones y tasas** agregadas (no un run suelto),
   definimos instrumentos OTel en [observability.py](../email_triage/observability.py) y los
   cableamos con un helper único: `instrument_agent_run(...)` en
   [services/agent_telemetry.py](../email_triage/services/agent_telemetry.py), que envuelve cada
   `agent.run(...)`. Los conteos de tool-calls salen de leer el historial de mensajes del run — sin
   tocar cada tool.

Etiquetas de **baja cardinalidad** (regla del repo): `agent` (`diagnosis`|`tuning`), `tool`
(nombres de tools curadas), `outcome` (`ok`|`error`), `model`. Nunca `tenant_id`/ids.

## Mapa: blog → instrumento → cómo verlo en Logfire

| # | Métrica del blog | Instrumento OTel | De dónde sale | Cómo graficarla en Logfire |
|---|---|---|---|---|
| 1 | **Token Usage per Agent Run** | `agent.input_tokens`, `agent.output_tokens` (histograma) `{agent}` | `result.usage` (input/output tokens) | Histograma / p50-p95 de cada métrica, **group by `agent`** |
| 2 | **Tool Call Success Rate** | `agent.tool_calls_total` (counter) `{tool, outcome}` | historial del run (`ToolReturnPart`; `outcome=error` si el resultado empieza con "error" o trae `error`) | `sum by (tool, outcome)`; tasa = `ok / (ok+error)` por `tool` |
| 3 | **LLM Latency Distribution** | `agent.llm.latency_ms` (histograma) `{agent}` | timer alrededor de `agent.run` | Distribución (p50/p95/p99) **group by `agent`** |
| 4 | **Agent Loop Iterations** | `agent.loop_iterations` (histograma) `{agent}` | `usage.requests` (nº de model-requests) | Distribución **group by `agent`**; picos = tarea difícil o thrashing |
| 5 | **Context Window Utilization** | `agent.context_utilization` (histograma, ratio) `{agent, model}` | `input_tokens / MODEL_MAX_CONTEXT` (131 072, llama-3.3-70b) | Ratio 0–1 **group by `agent`, `model`**; alerta si se acerca a 1 |
| 6 | **End-to-End Agent Latency** | `agent.e2e.latency_ms` (histograma) `{agent}` | timer en `diagnose` / `run_tuning` (entry-point) | Distribución **group by `agent`** (SLO del agente) |

> En Logfire: **Dashboards → nueva chart → elegí el nombre de la métrica → Group by** el atributo.
> Para la tasa de éxito de tools, dos series (`outcome=ok` y `outcome=error`) por `tool` y su cociente.

## Qué decisión habilita cada métrica

- **Tokens (#1) + contexto (#5):** si la utilización de contexto sube hacia 1, el agente está por
  quedarse sin ventana → *compactar* historial, *particionar* la tarea o subir de modelo. Los tokens
  por run son tu factura: comparás `diagnosis` vs `tuning`.
- **Tool-call success rate (#2):** una tasa baja en un `tool` concreto (p. ej. muchos `error` en
  `add_counter_example`) apunta a un slug mal resuelto o una tool con mal contrato → arreglar la tool
  o el prompt que la invoca.
- **Loop iterations (#4):** muchas iteraciones = tarea difícil **o** el agente cicla → revisá el
  system prompt o el tope (`usage_limits`). Es la métrica que **solo** un agente real produce (un
  workflow determinista no la tiene).
- **LLM latency (#3) vs e2e (#6):** si la e2e es mucho mayor que la suma de latencias de modelo, el
  costo está en las tools (I/O, evals) → ahí optimizás.

## Dónde está en el código

- Instrumentos: [observability.py](../email_triage/observability.py) (sección "Agent telemetry (Plan 42)").
- Helper de cableado: [services/agent_telemetry.py](../email_triage/services/agent_telemetry.py)
  (`instrument_agent_run`, `record_tool_calls`, `MODEL_MAX_CONTEXT`).
- Cableado en los agentes: `TraceDiagnosisService.diagnose` (Plan 43) y `run_tuning` (Plan 44)
  envuelven su `agent.run` y registran la e2e.
- Tests: [tests/test_agent_telemetry.py](../tests/test_agent_telemetry.py) — un run de diagnóstico
  emite las 6 familias con las etiquetas correctas; y la clasificación `ok`/`error` de tool-calls.

## Para verlo con datos reales

Las métricas viajan a Logfire cuando hay `LOGFIRE_TOKEN` (`send_to_logfire="if-token-present"`).
Generá tráfico nuevo:

1. Corré una triage (`POST /triage`) para tener un `trace_id` con `tenant_id` (Plan 33).
2. `POST /workspaces/{tid}/traces/{trace_id}/diagnose` → dispara el agente de **diagnóstico**.
3. `POST /workspaces/{tid}/tune` con el correo mal clasificado → dispara el **copiloto** (varios
   ciclos → verás `loop_iterations` > 1 y varias `tool_calls_total`).
4. En Logfire, armá las charts de la tabla de arriba.

> Nota: las trazas **viejas** no tienen `tenant_id` (código previo a Plan 33) — el diagnóstico útil
> necesita tráfico nuevo.
