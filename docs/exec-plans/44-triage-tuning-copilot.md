# 44. Copiloto de tuning de triage — orquestador (diagnóstico → propuesta → eval)

**Status:** 📋 proposed
**Estimate:** ~8 hrs
**Depends on:** Plan 43 (diagnóstico de trazas), Plan 26 (few-shot + draft→preview→publish + eval-gate), Plan 27 (semántica de las tools triage-studio), Plan 23/`evals/` (suite de evals), Plan 25 (Groq/pydantic-ai).
**Sujeto principal de:** Plan 42 (aquí se ven las 6 métricas *completas y honestas*).

## Intent

La feature genuinamente **orquestador + subagentes/tools** del taller. Dada una triage que el
owner marca como **mal clasificada**, el copiloto:

1. **Diagnostica** la causa raíz (llama a Plan 43).
2. **Propone un cambio de config** al **borrador** del workspace vía las tools del Studio (Plan
   26/27): agregar un *counter-example* few-shot, ajustar la descripción de una categoría, etc.
3. **Corre evals** (infra `evals/`) sobre el borrador.
4. **Lee el score** y **decide**: si el eval-gate no pasa (o empeora otra cosa), **refina y
   reevalúa** — loop — hasta pasar el gate o agotar el tope.
5. **Se detiene** y presenta una `TuningProposal` (diagnóstico + cambios al borrador + scores
   antes/después). **El publish lo hace el humano** por el flujo existente (Plan 26).

Por qué es *genuinamente agéntico* (y por eso ilumina las 6 métricas de verdad): el nº de ciclos
refinar↔evaluar **es impredecible** y el modelo decide **qué tool llamar y cuántas veces**
(`diagnose`, `add_counter_example`, `tweak_category`, `run_eval`, `preview`). Eso produce
*tool-call success rate* (#2) e *iterations* (#4) reales, además de tokens/latencia/contexto por run.

## Prior reading

- [docs/exec-plans/43-trace-diagnosis-agent.md](43-trace-diagnosis-agent.md) — `TraceDiagnosisService.diagnose` (el sub-paso de diagnóstico).
- [services/prompt_studio.py](../../email_triage/services/prompt_studio.py), [services/triage_config.py](../../email_triage/services/triage_config.py), [db/repos/examples.py](../../email_triage/db/repos/examples.py) — draft de few-shot / template / categorías (Plan 26).
- [mcp_server.py](../../email_triage/mcp_server.py) — semántica de `add_example`/`create_category`/`preview_prompt`/`list_prompt_versions` (Plan 27); aquí se envuelven como tools internas ligadas al tenant.
- [evals/run_evals.py](../../email_triage/../evals/run_evals.py), `Makefile` (`make eval`, `eval-quick`, `eval-regression`) — cómo correr la suite y leer el score.
- Gobernanza (Plan 26): "published wins if present"; el **publish es irreversible** → se mantiene humano.

## Scope

**Incluido:**
- `services/tuning/` (**nuevo**): orquestador `Agent` con tools que envuelven servicios existentes,
  **todas ligadas al `tenant_id` del contexto** (nunca del modelo):
  - `diagnose(trace_id) -> TraceDiagnosis` → Plan 43.
  - `add_counter_example(slug, subject, sender, body)` / `add_example(...)` → borrador (Plan 26).
  - `tweak_category(slug, description)` → borrador de categoría.
  - `preview_prompt() -> str` → XML compilado del borrador.
  - `run_eval(suite="regression"|"quick") -> EvalScore` → corre un subconjunto rápido de la suite.
  - El system prompt guía: diagnosticar → proponer el fix del `suggested_fix_kind` → evaluar →
    iterar hasta pasar el gate o `max_cycles`. `usage_limits` acota el loop.
- `schemas.py`: `TuningProposal` (diagnóstico, lista de cambios al borrador, `score_before`,
  `score_after`, `gate_passed`, `recommendation`, `cycles`).
- `routers/tuning.py` (**nuevo**): `POST /workspaces/{tid}/tune` con `{trace_id}` (scope
  `prompt:publish` o nuevo `prompt:tune`) → corre el orquestador → `TuningProposal`. **No publica.**
- Tests con `TestModel`/`FunctionModel` + fakes (diagnóstico fake, eval runner fake): el orquestador
  itera, llama tools, produce `TuningProposal`, **nunca publica**, respeta aislamiento, y el caso
  "gate no pasa tras `max_cycles`" cierra limpio.

**Fuera de scope:**
- **Publish automático** — jamás; el borrador queda listo y el humano publica por Plan 26 (acción
  irreversible ⇒ humano en el loop).
- UI del copiloto (panel/botón "Sugerir mejora") → plan de frontend aparte.
- Instrumentos de métrica de las 6 KPIs → Plan 42 (este es su sujeto principal).
- Auto-tuning masivo/programado (v2).

## Flujo de `POST /workspaces/{tid}/tune`

```
span "tuning.run"  (tenant_id en baggage)                 ← e2e latency (#6)
  Agent ORQUESTADOR.run("mejorá la config para arreglar la triage {trace_id}")  ← loop (#4, tool-calls #2)
    → diagnose(trace_id)                    (Plan 43: causa raíz + suggested_fix_kind)
    → run_eval(quick)                       (score_before)
    ↺ hasta gate o max_cycles:
        → add_counter_example(...) | tweak_category(...)   (escribe al BORRADOR)
        → preview_prompt()                                 (verifica el XML)
        → run_eval(quick|regression)                       (score_after; decide iterar o parar)
  return TuningProposal(diagnosis, changes, score_before, score_after, gate_passed, cycles)
  # el humano revisa y publica por el flujo de Plan 26
```

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/services/tuning/__init__.py` | **nuevo** — `run_tuning(tenant_id, trace_id) -> TuningProposal` |
| `email_triage/services/tuning/agent.py` | **nuevo** — orquestador + system prompt + `usage_limits` |
| `email_triage/services/tuning/tools.py` | **nuevo** — `diagnose`/`add_counter_example`/`tweak_category`/`preview_prompt`/`run_eval` (envuelven servicios existentes, ligadas al tenant) |
| `email_triage/schemas.py` | `TuningProposal`, `EvalScore` |
| `email_triage/routers/tuning.py` | **nuevo** — `POST /workspaces/{tid}/tune` |
| `email_triage/main.py` | `include_router(tuning.router)` |
| `email_triage/deps.py` | (si aplica) scope `prompt:tune` |
| `tests/test_tuning_copilot.py` | **nuevo** — loop, tools, no-publish, aislamiento, gate-falla |
| `docs/features/44-*` | doc |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Orquestador dinámico (loop) | Workflow determinista | El nº de ciclos refinar↔evaluar es impredecible; **aquí sí** se justifica el agente |
| Delegar el diagnóstico a Plan 43 | Un mega-agente que también lee trazas | Separación de responsabilidades; el diagnóstico es reutilizable y read-only |
| Escrituras solo al **borrador**; publish humano | Auto-publish al pasar el gate | Publish es irreversible; el humano decide (principio de acción irreversible → confirmación) |
| Tools envuelven servicios existentes | Reimplementar la lógica del Studio | Cero duplicación; reusa Plan 26/27; aislamiento por tenant en un solo lugar |
| Eval-gate como condición de parada | "Parar cuando el modelo crea que está bien" | Señal objetiva; evita over-fitting a un caso; usa la suite de regresión |
| `run_eval(quick)` para iterar, `regression` para confirmar | Correr la suite completa cada ciclo | Coste/latencia; el quick guía el loop, el regression valida antes de proponer |

## Risks / Open questions

- **Coste/latencia del loop de evals:** cada ciclo corre evals. Usar `eval-quick` (sin judge) para
  iterar y acotar con `max_cycles`/`usage_limits`; medir con Plan 42 (es el punto del taller).
- **Over-fitting a un caso:** arreglar una triage no debe romper otras → validar contra la suite de
  **regresión** antes de proponer; `TuningProposal.score_before/after` lo hace visible.
- **Seguridad del publish:** nunca auto-publicar; test explícito de que el copiloto solo toca el
  borrador y el endpoint no publica.
- **Aislamiento:** toda tool fija `tenant_id` del contexto; test de que no puede tocar otro workspace.
- **No-determinismo:** el loop es dinámico → tests con `FunctionModel` forzando la secuencia y
  aseverando las tool-calls; fakes para diagnóstico y eval.
- **`prompt:tune` vs `prompt:publish`:** decidir si el tuning necesita scope propio o reusa
  `prompt:publish` (el publish real lo hace el humano igual).

## Execution order

1. Schemas `TuningProposal`/`EvalScore` (30 min).
2. `tools.py`: envolver diagnose/add_counter_example/tweak_category/preview/run_eval, ligadas al tenant (150 min).
3. `agent.py`: orquestador + system prompt + `usage_limits` (90 min).
4. `run_tuning` + `routers/tuning.py` (+ scope) (60 min).
5. Tests con `FunctionModel` + fakes: loop, no-publish, aislamiento, gate-falla (150 min).
6. Doc `44-*`; `make check` verde.

## Done when

- [ ] `POST /workspaces/{tid}/tune {trace_id}` devuelve una `TuningProposal` con diagnóstico + cambios al borrador + scores antes/después
- [ ] El orquestador itera refinar↔evaluar en un nº **variable** de ciclos hasta gate o `max_cycles`
- [ ] Las tools escriben **solo al borrador**; el endpoint **no publica** (test explícito)
- [ ] La validación usa la suite de regresión (no solo el caso puntual)
- [ ] Toda tool fija `tenant_id` del contexto; test de aislamiento verde
- [ ] Ningún test corre evals reales/Groq/red (fakes + `TestModel`/`FunctionModel`) — `CLAUDE.md`
- [ ] `make check` verde (ruff + pyright 0 + tests)
- [ ] Humano validó el flujo end-to-end sobre una triage marcada como errónea
