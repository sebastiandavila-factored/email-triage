# 44. Copiloto de tuning de triage — orquestador (diagnóstico → propuesta → check-set)

**Status:** 🚧 implemented (pending human review/merge)
**Estimate:** ~8 hrs
**Depends on:** Plan 43 (diagnóstico de trazas), Plan 26 (few-shot + draft + `compile_draft`), Plan 25 (`LLMService` dinámico), Plan 21 (RBAC `prompt:publish`).
**Sujeto principal de:** Plan 42 (aquí se ven las 6 métricas completas: tool-calls + iterations reales).

## Intent

La feature genuinamente **orquestador + tools**. Dada una triage que el owner marca como **mal
clasificada**, el copiloto: diagnostica (Plan 43) → propone un cambio al **borrador** (contra-ejemplo
few-shot o ajuste de descripción de categoría) vía los servicios del Studio → **re-clasifica un
check-set** contra el borrador → itera hasta que el correo marcado clasifica bien sin regresiones (o
agota el tope de requests). Devuelve un `TuningProposal`; **el publish lo hace el humano** (Plan 26).

Es genuinamente agéntico (por eso es el sujeto de Plan 42): el nº de ciclos refinar↔chequear **no se
conoce de antemano** y el modelo decide qué tool llamar → *tool-call success rate* (#2) e *iterations*
(#4) reales, además de tokens/latencia/contexto por run.

## Hallazgo que definió el diseño del "eval"

El plan original decía `run_eval(suite="regression")`. Al implementar se vio que **no hay un eval
por-tenant corrible**:
- El `PromptGate` inyectable de `publish` (evalúa el borrador → `accuracy/macro_f1`) **no está
  cableado en producción** (todos usan `PromptStudioService()` sin gate); solo se usa en tests.
- `evals.run(...)` es **CLI + golden dataset + camino legacy** (5 categorías frozen, enum).
- Un tenant del Studio tiene **categorías arbitrarias**; sus únicos datos etiquetados son sus
  few-shots (señal de entrenamiento, no un hold-out).

**Decisión (con el humano):** el loop mide con un **check-set de regresión sobre el borrador** —
re-clasificar con el prompt del borrador (a) el **correo marcado** contra su categoría esperada, y
(b) unos **few-shots positivos hold-out** del tenant como guardia de regresión. Factible con lo que
hay (`compile_draft` + un `LLMService` dinámico), evita over-fit, y es honesto.

## Nota de contrato

La **traza no trae el cuerpo del correo** (privacidad: los spans guardan *chars*, no contenido). Por
eso `/tune` recibe el **email** (subject/sender/body) y su **categoría esperada** en el body, más el
`trace_id` para el diagnóstico. El owner los tiene: viene de una triage que acaba de ver.

## Prior reading

- [docs/exec-plans/43-trace-diagnosis-agent.md](43-trace-diagnosis-agent.md) — `TraceDiagnosisService.diagnose` (sub-paso de diagnóstico) y `build_diagnosis_service`.
- [services/prompt_studio.py](../../email_triage/services/prompt_studio.py) — `add_example(kind="negative", …)`, `compile_draft` (prompt + allowed_slugs), la ausencia de gate en prod.
- [services/triage_config.py](../../email_triage/services/triage_config.py) — `update_category(…, description=…)`; slug inmutable.
- [db/repos/categories.py](../../email_triage/db/repos/categories.py) — `get_by_slug`, `list_for_tenant`; [db/repos/examples.py](../../email_triage/db/repos/examples.py) — `list_for_category`.
- [deps.py](../../email_triage/deps.py) — `_build_service(prompt, allowed_slugs)`: cómo se arma un `LLMService` dinámico desde un prompt compilado (reusado por el clasificador).

## Diseño implementado

- **`services/tuning.py`** (nuevo):
  - **Orquestador** `build_tuning_agent(model) -> Agent[TuningDeps, str]` con tools
    `diagnose`, `add_counter_example`, `tweak_category`, `preview_prompt`, `run_check`; system prompt
    que lo guía (diagnosticar → fix mínimo → chequear → iterar). Output `str` (recomendación); el
    `TuningProposal` lo **arma el harness** desde un `TuningJournal` (cambios/scores/cycles
    autoritativos, no auto-reportados por el modelo). `UsageLimits(request_limit=12)` acota el loop.
  - **Tools** ligadas al `tenant_id` de `TuningDeps` (no del modelo): las escrituras abren sesión del
    factory y van **solo al borrador**; un slug de otro workspace no resuelve (`get_by_slug` → error
    string, sin escritura). `run_check` compila el borrador y clasifica target + hold-out.
  - **Colaboradores inyectables:** `DiagnosisProvider` (Plan 43) y `DraftClassifier` (Protocol).
    Producción: `LLMDraftClassifier` (arma `LLMService` desde el borrador). Tests: fakes.
  - **`TuningRunner`** (agent + diagnosis + classifier) con `run(...)`: carga el hold-out y corre
    `run_tuning`. `build_tuning_runner(...)` cablea la versión de producción.
- **`schemas.py`:** `EvalScore` (`target_fixed`, `target_predicted`, `regressions`, `checked`),
  `TuningProposal` (`diagnosis?`, `changes`, `score_before?`, `score_after?`, `gate_passed`, `cycles`,
  `recommendation`), `TuneRequest` (`trace_id`, `email`, `expected_category`).
- **`routers/tuning.py`:** `POST /workspaces/{tid}/tune` (scope `prompt:publish`), dep
  `get_tuning_runner` (→ `None`/503 si falta el read token de Logfire), mapeo de errores
  422/404/503. **No publica.**
- **`main.py`:** `include_router(tuning.router)`.

## Flujo de `POST /workspaces/{tid}/tune`

```
Agent ORQUESTADOR.run(...)  usage_limits(12)            ← loop (#4, tool-calls #2)
  → diagnose()               (Plan 43: causa raíz + suggested_fix_kind + target_slug)
  ↺ hasta target_fixed ∧ regressions=0, o max requests:
      → add_counter_example(slug, subject, body)  |  tweak_category(slug, description)   [→ BORRADOR]
      → preview_prompt()            (opcional: ver el XML)
      → run_check()                 compile_draft → clasificar target + hold-out → EvalScore
  → recomendación (str)
TuningProposal(diagnosis, changes, score_before, score_after, gate_passed, cycles, recommendation)
# el humano revisa y publica por Plan 26
```

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/services/tuning.py` | **nuevo** — orquestador, tools, journal, `DraftClassifier`, `TuningRunner`, `build_tuning_runner`, `load_holdout` |
| `email_triage/schemas.py` | `EvalScore`, `TuningProposal`, `TuneRequest` |
| `email_triage/routers/tuning.py` | **nuevo** — `POST /workspaces/{tid}/tune` + dep con cache |
| `email_triage/main.py` | `include_router(tuning.router)` |
| `tests/test_tuning_copilot.py` | **nuevo** — 7 tests (ver abajo) |
| `docs/features/44-*` | doc |

## Tests (`tests/test_tuning_copilot.py`, sin red)

`FunctionModel` guiona la secuencia de tools; `FakeDiagnosis`/`FakeClassifier` stubean Groq/Logfire;
las ediciones del borrador corren contra **SQLite sembrado** (tools reales):

- fix del target + edición real del borrador + **nunca publica** (no hay versión activa; hay un
  ejemplo `negative` en `refunds`).
- gate falla cuando el target no queda arreglado.
- **regresión de hold-out** bloquea el gate (target ok pero un few-shot positivo se rompe).
- slug inexistente → tool devuelve error, **sin escritura** ni cambio registrado.
- endpoint: 503 sin token, 403 miembro (`prompt:publish`), 200 owner happy-path.

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Orquestador dinámico (loop) | Workflow determinista | El nº de ciclos refinar↔chequear es impredecible; aquí sí se justifica el agente |
| Check-set (target + hold-out) sobre el borrador | `run_eval` sobre golden dataset / suite | No hay eval por-tenant; el golden es de las 5 frozen. Evita over-fit y es honesto |
| Delegar el diagnóstico a Plan 43 | Un mega-agente que también lee trazas | Separación de responsabilidades; diagnóstico read-only y reutilizable |
| `TuningProposal` armado por el harness (journal) | Que el modelo reporte cambios/scores | Autoritativo y no alucinable; telemetría limpia para Plan 42 |
| Escrituras solo al **borrador**; sin tool de publish | Auto-publish al pasar el gate | Publish es irreversible → humano (principio de acción irreversible) |
| Tools envuelven servicios existentes | Reimplementar la lógica del Studio | Cero duplicación; aislamiento por tenant en un solo lugar |
| Diagnosis + classifier inyectables; edición real vs SQLite | Mockear todo | Tests exigen las tools reales de borrador; solo Groq/Logfire se stubean |
| Reusar `prompt:publish` | Nuevo scope `prompt:tune` | Sin migración; quien publica puede tunear el borrador; el publish real sigue siendo humano |

## Risks / Open questions

- **Coste/latencia del loop:** `run_check` hace 1 + N (hold-out) clasificaciones por ciclo. Acotado
  por `request_limit` y `_HOLDOUT_LIMIT=5`; se mide con Plan 42 (es el punto del taller).
- **Calidad con Groq real:** el orquestador corre con `FunctionModel`/fakes en tests; falta validar
  con Groq real que sigue la guía (diagnosticar → fix mínimo → chequear) y no cicla.
- **Hold-out = few-shots del tenant:** es una guardia de regresión, no un eval formal; documentarlo en
  el taller. Si no hay few-shots positivos, el check-set es solo el target.
- **Diagnóstico sin `owns_trace`:** el copiloto llama `diagnose` directo; el SQL del Plan 43 ya
  inlinea el predicado de tenant, así que una traza de otro org devuelve vacío (sin fuga).

## Done when

- [x] `POST /workspaces/{tid}/tune` devuelve `TuningProposal` (diagnóstico + cambios + scores antes/después)
- [x] El orquestador itera con tool-calls reales; `cycles`/`changes`/scores los registra el harness
- [x] Las tools escriben **solo al borrador**; el endpoint **no publica** (test: sin versión activa)
- [x] Check-set: target contra categoría esperada + hold-out de few-shots como guardia de regresión
- [x] Slug de otro workspace / inexistente → error, sin escritura (aislamiento)
- [x] `prompt:publish` gatea (403 miembro); 503 sin Logfire configurado
- [x] Ningún test toca Groq/Logfire/red (`FunctionModel` + fakes; borrador real vs SQLite) — `CLAUDE.md`
- [x] `make check` verde (ruff + pyright 0 + **254 tests**)
- [ ] Validado con Groq real end-to-end sobre una triage marcada como errónea
