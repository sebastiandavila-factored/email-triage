# 41. Reporte de voz — Workflow de resumen + guion (pydantic-ai)

**Status:** 📋 proposed
**Estimate:** ~5 hrs
**Depends on:** Plan 37 (`/gmail/sync` + `GmailClient`), Plan 40 (filtros unread/días), Plan 25 (`LLMService`/pydantic-ai por tenant).

## Intent

Construir la feature que el usuario pidió: **buscar los correos con los filtros elegidos →
resumirlos → escribir un guion** para un reporte de voz, con buen copy y estructura profesional.

Arquitectura (decisión firme): **workflow determinista (prompt chaining)**. El pipeline
`buscar → resumir → guionizar` se conoce de antemano; lo profesional es un workflow, no un agente.
Un orquestador dinámico aquí sería sobre-ingeniería (más caro, menos predecible, sin beneficio).

- **`buscar`** no necesita LLM: reutiliza la sync existente (Plan 37/40) que ya devuelve la bandeja
  triada (`InboxItem`).
- **`resumir`** y **`guionizar`** son dos llamadas LLM con salida estructurada (pydantic-ai/Groq).
- **Alcance v1 = solo el guion (texto)**. La síntesis de audio (TTS) es fase futura; `VoiceReport`
  deja `audio_url: None` para enchufarla después sin romper el contrato.

> **Nota de telemetría:** este workflow **no** es el ejemplo del taller de agentes. Emite métricas
> 1/3/5/6 (tokens, latencia LLM, contexto, e2e) por sus dos pasos LLM, pero **no** produce
> *tool-call success rate* ni *loop iterations* (no hay tools ni loop — y está bien que así sea). El
> ejemplo genuinamente agéntico de las 6 métricas vive en un plan aparte (ver Plan 43).

## Prior reading

- [routers/inbox.py](../../email_triage/routers/inbox.py) — la sync de Plan 37/40 que `buscar` reutiliza (bandeja `InboxItem` triada).
- [services/llm.py](../../email_triage/services/llm.py) — patrón `Agent(...)` de pydantic-ai con salida estructurada, `build_groq_model`.
- Anthropic "Building Effective Agents": *prompt chaining* — cuándo un workflow es la elección correcta frente a un agente.

## Scope

**Incluido:**
- `services/voice_report.py` (**nuevo**), un **workflow** determinista:
  - `_summarize(items: list[InboxItem]) -> ReportSummary` — llamada LLM estructurada (temas del día,
    prioridades, conteos por categoría, urgentes).
  - `_write_script(summary: ReportSummary) -> VoiceScript` — llamada LLM estructurada (apertura,
    cuerpo por tema, cierre), copy pulido, tono por-workspace.
  - `run_voice_report(tenant_id, unread_only, days) -> VoiceReport` — encadena `buscar` (reusa sync) →
    `_summarize` → `_write_script`, cada paso en su span Logfire.
- `schemas.py`: `ReportSummary`, `VoiceScript` (secciones tipadas), `VoiceReport`
  (guion + conteos + `trace_id` + `audio_url: str | None = None`).
- `routers/reports.py` (**nuevo**): `POST /reports/voice` (scope `triage:write`) con body
  `SyncRequest` (reusa Plan 40) → `VoiceReport`. Baggage `tenant_id` (patrón Plan 33).
- Tests con `TestModel`/`FunctionModel` (sin Groq, sin red): el workflow encadena, salida
  estructurada válida, aislamiento por tenant, bandeja vacía → guion "sin novedades".

**Fuera de scope:**
- **Síntesis de audio / TTS** (fase futura; `audio_url` queda `None`).
- UI del reporte (botón + preview del guion) → plan de frontend aparte.
- Cualquier loop/agente/tool → **no aplica**; el ejemplo agéntico de telemetría es Plan 43.

## Flujo de `run_voice_report`

```
span "voice_report.run"  (tenant_id en baggage)          ← e2e latency (para Plan 42)
  1. buscar: reusa la sync de Plan 37/40 → list[InboxItem]      (sin LLM)
  2. span "voice_report.summarize": _summarize(items) → ReportSummary   (LLM estructurado)
  3. span "voice_report.script":    _write_script(summary) → VoiceScript (LLM estructurado)
  return VoiceReport(script=..., counts=..., trace_id=..., audio_url=None)
```

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/services/voice_report.py` | **nuevo** — workflow `run_voice_report` + `_summarize` + `_write_script` |
| `email_triage/schemas.py` | `ReportSummary`, `VoiceScript`, `VoiceReport` |
| `email_triage/routers/reports.py` | **nuevo** — `POST /reports/voice` |
| `email_triage/main.py` | `include_router(reports.router)` |
| `tests/test_voice_report.py` | **nuevo** — encadenado, aislamiento, vacío |
| `docs/features/41-*` | doc |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Workflow determinista (prompt chaining) | Orquestador con subagentes | Pipeline conocido de antemano; workflow es lo profesional, predecible y barato |
| `buscar` reutiliza la sync (sin LLM) | Un subagente recolector con tools | La bandeja ya viene triada de Plan 37/40; no hay decisión dinámica que tomar |
| pydantic-ai / Groq (en-stack) | Claude Agent SDK | Ya integrado con Logfire/OTel; sin nueva dep ni API key |
| Salidas estructuradas (`VoiceScript` tipado) | Guion como texto libre | Estructura profesional garantizada; fácil de renderizar y luego locutar |
| `VoiceReport.audio_url = None` en v1 | No dejar campo | Contrato estable para enchufar TTS después |

## Risks / Open questions

- **Calidad del copy:** iterar el prompt del guionista con ejemplos; posible eval offline (infra `evals/`).
- **Bandeja vacía:** el guion debe degradar a "sin correos relevantes hoy", no fallar.
- **Coste/latencia:** solo 2 llamadas LLM; el filtro de Plan 40 acota el volumen de entrada.
- **Aislamiento multi-tenant:** `run_voice_report` recibe `tenant_id` del contexto y usa el servicio del tenant.

## Execution order

1. Schemas `ReportSummary`/`VoiceScript`/`VoiceReport` (30 min).
2. `services/voice_report.py`: `_summarize` + `_write_script` + `run_voice_report` con spans (120 min).
3. `routers/reports.py`: `POST /reports/voice` (30 min).
4. Tests con `TestModel`/`FunctionModel`: encadenado, aislamiento, vacío (90 min).
5. Doc `41-*`; `make check` verde.

## Done when

- [ ] `POST /reports/voice {unread_only, days}` devuelve un `VoiceReport` con guion estructurado
- [ ] El guion tiene apertura/cuerpo por tema/cierre y buen copy (revisión humana)
- [ ] Bandeja vacía → guion "sin novedades" válido, no error
- [ ] `VoiceReport.audio_url` queda `None` (contrato listo para TTS futuro)
- [ ] Ningún test toca Groq/red (pydantic-ai `TestModel`/`FunctionModel`) — `CLAUDE.md`
- [ ] `make check` verde (ruff + pyright 0 + tests)
- [ ] Humano validó el guion sobre una bandeja real
