# Guía de estudio — Observabilidad y Evals con Pydantic AI + Logfire

> Plan de lectura y práctica para preparar la charla, anclado en tu proyecto `email-triage`.
> Fuentes oficiales: documentación de **Pydantic Logfire** y **Pydantic Evals**, más el artículo de Anthropic *“Demystifying evals for AI agents”* (Jan 2026).
> Convención: prosa en español, términos y código en inglés (spans, traces, evals, graders, etc.).

---

## 0. Cómo usar esta guía

Son **5 bloques de estudio** (~2–3 h cada uno) pensados para una semana. Cada bloque tiene: *qué leer*, *qué mirar en tu repo*, *qué practicar* y *preguntas de control* que probablemente te haga la audiencia.

El hilo conductor es simple: tu proyecto ya tiene **observabilidad (OTEL/Logfire)** y un **harness de evals casero** muy decente. La charla y este estudio buscan cerrar dos brechas concretas:

1. **Prompt versioning** — hoy tu `SYSTEM_PROMPT` vive hardcodeado en `services/llm.py`. Logfire **Prompt Management** te deja versionarlo, promoverlo y hacer rollback sin redeploy.
2. **Evals best practices** — hoy tenés métricas calculadas a mano (`evals/metrics.py`). El framework **Pydantic Evals** + las prácticas de Anthropic te dan estructura (Dataset/Case/Experiment/Evaluator), evaluación online, span-based y un vocabulario común para defender decisiones.

No se trata de tirar lo que tenés, sino de mapearlo al estado del arte.

---

## 1. Mapa mental: qué tenés vs. qué propone el estado del arte

Antes de leer nada, fijá el punto de partida. Esta tabla es el corazón de la charla.

| Concepto (Anthropic / Pydantic) | En la teoría | En tu `email-triage` hoy | Brecha a cubrir |
|---|---|---|---|
| **Task / Case** | un test con input y criterio de éxito | cada línea de `evals/dataset.jsonl` (`EvalCase`) | migrar a `pydantic_evals.Case` |
| **Dataset / Eval suite** | colección de cases | `dataset.jsonl` + `_load_dataset()` | usar `pydantic_evals.Dataset` (serializable a YAML/JSON) |
| **Experiment** | correr la suite y obtener report | `run()` en `run_evals.py` | usar `Dataset.evaluate()` |
| **Code-based grader** | match exacto, regex, checks deterministas | `is_correct` (igualdad de categoría), métricas en `metrics.py` | envolver en `Evaluator` custom |
| **Model-based grader (LLM judge)** | rúbrica con LLM | `evals/judge.py` (`JudgeAgent`, 5 dimensiones) | comparar con `LLMJudge` built-in de Pydantic Evals |
| **Human grader** | SME review, calibración | — (no existe aún) | proponer spot-check + calibración |
| **Calibration / ECE** | qué tan confiable es la confidence | `_compute_ece()` + reliability diagram | ya lo tenés — punto fuerte de la charla |
| **Transcript / trace** | registro completo del trial | spans de Logfire (`eval.run`, `eval.case`) | leer transcripts (paso 6 de Anthropic) |
| **Eval harness** | infra que corre todo | `run_evals.py` (semaphore, gather, report) | comparar con el harness del framework |
| **Online / production monitoring** | evaluar en prod sin dataset | métricas en `observability.py` | agregar online evals (`@evaluate`, `OnlineEvaluation`) |
| **Prompt versioning** | versionar y promover prompts | `SYSTEM_PROMPT` hardcodeado | Logfire Prompt Management (`logfire.var`) |
| **Capability vs regression evals** | hill-climbing vs. anti-backslide | una sola suite mezclada | separar en dos suites |
| **pass@k / pass^k** | no-determinismo, consistencia | corrida única por case | multi-run (`temperature=0.2` no es determinista) |

Guardá esta tabla: es tu slide de “estado actual” y tu checklist de roadmap.

---

## 2. Bloque 1 — Fundamentos de evals (el “por qué”)

**Objetivo:** poder explicar en 5 minutos qué es un eval, por qué importa, y qué tipos de graders existen. Es la base conceptual de toda la charla.

### Leer
- Anthropic, *Demystifying evals for AI agents* — secciones **Introduction**, **The structure of an evaluation**, **Why build evaluations?**, **Types of graders**.
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Pydantic Evals — **Overview** (modelo de datos Dataset → Case → Experiment → Evaluator).
  https://ai.pydantic.dev/evals/
- Pydantic Evals — **Core Concepts**.
  https://ai.pydantic.dev/evals/core-concepts/

### Conceptos clave a dominar
- **Vocabulario de Anthropic:** *task/problem/test case*, *trial*, *grader* (con sus *assertions/checks*), *transcript/trace*, *outcome*, *eval harness*, *agent harness/scaffold*, *eval suite*. Definirlos bien evita confusión durante la charla.
- **Tres familias de graders** y sus trade-offs:
  - *Code-based*: rápidos, baratos, objetivos, reproducibles; pero frágiles ante variaciones válidas.
  - *Model-based (LLM-as-judge)*: flexibles, capturan matices; pero no deterministas, más caros, **necesitan calibración con humanos**.
  - *Human*: gold standard; pero lentos y caros — se usan para calibrar a los model-based.
- **La analogía con unit testing** (del overview de Pydantic): Cases+Evaluators = tests, Dataset = test suite, Experiment = correr `pytest`. La diferencia: los sistemas de IA son probabilísticos, así que el score suele ser cualitativo, no pass/fail binario.

### Mirar en tu repo
- `evals/run_evals.py` → identificá dónde está cada pieza del vocabulario (tu `run()` es el *harness*, `_run_case()` ejecuta un *trial*, `EvalResult` es el resultado del *case*).
- `evals/judge.py` → es un *model-based grader* con rúbrica de 5 dimensiones (relevance, language_match, tone, correctness, overall).
- `evals/metrics.py` → son *code-based graders* + agregación (accuracy, macro-F1, ECE).

### Preguntas de control
- ¿Cuál es la diferencia entre *transcript* y *outcome*? (En email-triage el outcome es la categoría + draft; el transcript es el span tree en Logfire.)
- ¿Por qué tu `JudgeAgent` necesitaría calibración humana antes de confiar en él?

---

## 3. Bloque 2 — Observabilidad OTEL con Logfire (tu terreno conocido)

**Objetivo:** poder explicar tu instrumentación actual y conectar observabilidad con evals (production monitoring es una capa del “queso suizo”).

### Leer
- Logfire — **AI & LLM Observability** y **Core Concepts**.
  https://pydantic.dev/docs/logfire/get-started/ai-observability/ · https://pydantic.dev/docs/logfire/get-started/concepts/
- Logfire — integración **Pydantic AI**.
  https://pydantic.dev/docs/logfire/integrations/llms/pydanticai/
- Logfire — **Sampling Strategies** y **Scrub Sensitive Data** (ya los usás).
  https://pydantic.dev/docs/logfire/instrument/sampling/ · https://pydantic.dev/docs/logfire/instrument/scrubbing/

### Mirar en tu repo (esto ya es material de slides)
- `email_triage/main.py`:
  - `logfire.configure(send_to_logfire="if-token-present", environment=..., ...)` con `SamplingOptions` (tail sampling), `ScrubbingOptions`.
  - `instrument_pydantic_ai()`, `instrument_pydantic()`, `instrument_system_metrics()`, `instrument_httpx()`, `instrument_fastapi(app)`.
- `email_triage/observability.py`: catálogo de métricas — `metric_counter` (REQUESTS_TOTAL, ERRORS_TOTAL, LLM_ERRORS_TOTAL, AUTH_FAILURES_TOTAL, RATE_LIMIT_HITS_TOTAL), `metric_histogram` (STREAM_TTFT_MS, LLM_LATENCY_MS, CONFIDENCE, REQUEST_BODY_CHARS, RESPONSE_DRAFT_CHARS), `metric_up_down_counter` (LLM_IN_FLIGHT).
- `email_triage/routers/triage.py`: `logfire.span("triage.sync")`, `logfire.span("triage.stream")`.

### Idea puente para la charla
La observabilidad y los evals **comparten la misma señal**: spans de OpenTelemetry. Pydantic Evals graba traces OTEL del proceso de evaluación, y los *span-based evaluators* leen el mismo span tree que ves en producción. Esto significa que **tus assertions de eval pueden alinearse con tu telemetría de prod** — un argumento central del artículo de Anthropic sobre por qué evaluar el *cómo* y no solo el *qué*.

### Preguntas de control
- ¿Qué es *tail sampling* y por qué lo elegiste sobre head sampling? (Mirá `TailSamplingSpanInfo` en tu `main.py`.)
- ¿Qué métricas de `observability.py` servirían como *tracked_metrics* en un eval (latencia, tokens, confidence)?

---

## 4. Bloque 3 — Prompt versioning con Logfire Prompt Management

**Objetivo:** reemplazar tu `SYSTEM_PROMPT` hardcodeado por un prompt versionado, promovible y con rollback. Es uno de los dos pedidos centrales.

### Leer (en orden)
1. **Overview** — qué resuelve Prompt Management.
   https://pydantic.dev/docs/logfire/prompt-management/
2. **Core Concepts** — *prompt* (name + slug + template + settings) vs *version* (snapshot inmutable v1, v2, …).
   https://pydantic.dev/docs/logfire/prompt-management/concepts/
3. **Writing Templates** y **Template Reference** — variables `{{var}}`, Handlebars.
   https://pydantic.dev/docs/logfire/prompt-management/templates/ · https://pydantic.dev/docs/logfire/prompt-management/template-reference/
4. **Test Prompts (scenarios)** — probar versiones contra inputs representativos antes de promover.
   https://pydantic.dev/docs/logfire/prompt-management/scenarios/
5. **Use Prompts in Your Application** — el flujo de producción con el SDK.
   https://pydantic.dev/docs/logfire/prompt-management/application/
6. **Managed Variables** (Overview + A/B Testing) — labels y promoción.
   https://pydantic.dev/docs/logfire/manage/managed-variables/ · https://pydantic.dev/docs/logfire/manage/managed-variables/ab-testing/

### Modelo mental
- Un **prompt** tiene name (`Email Triage System`) y slug (`email-triage-system`).
- Una **version** es un snapshot inmutable del template (v1, v2, …) con autor y timestamp. **Solo congela el texto del template**, no los settings (model, tools) — esos se resuelven en runtime.
- **Save ≠ Promote.** Guardás una versión en la página *Prompts*; promovés moviendo un **label** (ej. `production`) en la página *Managed Variables*. Esto te deja iterar drafts sin tocar lo que producción importa.
- La app consume el prompt **por label**, no por número de versión.

### El patrón de código (flujo de producción)
El SDK expone el prompt como una *managed variable* con el patrón de nombre `prompt__<slug_con_underscores>`:

```python
import logfire

# slug 'email-triage-system' -> name 'prompt__email_triage_system'
prompt_var = logfire.var(name='prompt__email_triage_system', default='')
with prompt_var.get(label='production') as resolved:
    template = resolved.value
# luego renderizás el template con las variables de runtime
```

Para templates con variables planas alcanza una sustitución simple; para dotted paths o block helpers usás un renderer compatible con Handlebars (ver Template Reference).

### Práctica aplicada a email-triage
Refactor mental (o real, en una branch) de `services/llm.py`:
1. Subí tu `SYSTEM_PROMPT` actual a Logfire como prompt `email-triage-system`, version v1, label `production`.
2. En `LLMService.__init__` (o mejor, en una dependencia inyectable, según vuestro patrón DI del `CLAUDE.md`), fetchear el template con `logfire.var(...).get(label='production')` en vez de la constante `SYSTEM_PROMPT`.
3. Considerá el caching/lifecycle: no querés un fetch remoto por request en el critical path. Pensá en cache + refresh, o fetch en el lifespan (coherente con tu nota de “shared httpx client via lifespan, Day 6”).
4. **Importante (gobernanza):** tu `CLAUDE.md` dice que cambiar categorías exige tocar `schemas.py`, `SYSTEM_PROMPT` y `docs/features/`. Si el prompt pasa a Logfire, definí dónde vive ahora la *fuente de verdad* y cómo se mantiene la consistencia con `Category`.

### Preguntas de control
- ¿Cómo hacés rollback de un prompt malo en producción sin redeploy? (Mover el label a la versión anterior.)
- ¿Qué riesgo introduce fetchear el prompt remoto en el critical path y cómo lo mitigás? (Latencia/disponibilidad → cache, `default=`, fetch en lifespan.)
- ¿Versionado en Logfire vs. versionado en git del prompt? Trade-offs de cada uno (auditoría, redeploy, quién edita).

---

## 5. Bloque 4 — Evals best practices con Pydantic Evals

**Objetivo:** conectar el roadmap de 8 pasos de Anthropic con la API concreta de Pydantic Evals, usando tu dataset real.

### Leer
- Anthropic — **Going from zero to one: a roadmap** (los 8 pasos), **non-determinism (pass@k / pass^k)**, **How evals fit with other methods** (Swiss cheese), **Appendix: Eval frameworks**.
- Pydantic Evals — **Evaluators Overview**, **Built-in**, **LLM Judge**, **Custom**, **Span-Based**.
  https://ai.pydantic.dev/evals/evaluators/overview/ · …/built-in/ · …/llm-judge/ · …/custom/ · …/evaluators/span-based/
- Pydantic Evals — **How-To: Logfire Integration**, **Dataset Management**, **Multi-Run**, **Metrics & Attributes**.
  https://ai.pydantic.dev/evals/how-to/logfire-integration/ · …/dataset-management/ · …/multi-run/ · …/metrics-attributes/
- Logfire — **Evals: Datasets & Experiments** (vista web).
  https://pydantic.dev/docs/logfire/evaluate/evals/

### El roadmap de Anthropic, traducido a tu proyecto

| Paso | Anthropic dice | En email-triage |
|---|---|---|
| 0 | Empezá con 20–50 tasks de fallas reales | ¿cuántos cases tiene tu `dataset.jsonl`? ¿salen de fallas reales o son sintéticos? |
| 1 | Partí de lo que ya testeás a mano | convertí bugs de triage mal clasificado en cases |
| 2 | Tasks no ambiguos + reference solution | cada case ya tiene `expected_category`; agregá un draft de referencia |
| 3 | **Balanced sets** (evitá class imbalance) | ¿están balanceadas tus 5 categorías? Mirá el `support` por categoría en tu report |
| 4 | Harness robusto + entorno estable | tu `run()` con semaphore=5; aislamiento entre cases |
| 5 | Graders pensados; partial credit; LLM judge calibrado; dar salida “Unknown” | tu judge da 1–5 por dimensión (ya es partial credit); falta la opción “Unknown” para evitar hallucinations |
| 6 | **Leé los transcripts** | abrí los spans `eval.case` en Logfire y leé los misclassified |
| 7 | Cuidado con saturación | si accuracy ≈100%, el eval ya no da señal — subí dificultad |
| 8 | Suite viva, contribución abierta | que product/soporte agreguen cases vía PR |

### La API mínima que tenés que poder mostrar en vivo

```python
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, IsInstance

# 1) Un Case = un test
case = Case(
    name='refund_es_01',
    inputs={'subject': '¿Puedo devolver mi pedido?', 'body': '...'},
    expected_output='refunds',
    metadata={'difficulty': 'easy', 'lang': 'es'},
)

# 2) Un Evaluator custom (code-based: exact match de categoría)
class CategoryMatch(Evaluator[dict, str]):
    def evaluate(self, ctx: EvaluatorContext[dict, str]) -> float:
        return 1.0 if ctx.output == ctx.expected_output else 0.0

# 3) Un Dataset = la suite
dataset = Dataset(
    name='email-triage',
    cases=[case],
    evaluators=[IsInstance(type_name='str'), CategoryMatch()],
)

# 4) Un Experiment = correr la suite contra tu task
async def task(inputs: dict) -> str:
    resp = await llm.triage(TriageRequest(**inputs))
    return resp.category.value

report = dataset.evaluate_sync(task)
report.print(include_input=True, include_output=True)
```

**LLM judge built-in** (comparalo con tu `JudgeAgent` casero):

```python
from pydantic_evals.evaluators import LLMJudge

dataset.add_evaluator(
    LLMJudge(rubric='El reply es educado, en el mismo idioma y no inventa datos del pedido.')
)
```

**Span-based** (evaluar el *cómo*, no solo el output — alinea eval con telemetría de prod):

```python
import logfire
from pydantic_evals.evaluators import HasMatchingSpan

logfire.configure(send_to_logfire='if-token-present')
dataset.add_evaluator(
    HasMatchingSpan(query={'name_contains': 'triage'}, evaluation_name='llamo_al_llm')
)
# en evaluators custom: ctx.span_tree
```

### No-determinismo: pass@k vs pass^k (tu `temperature=0.2` no es 0)
- **pass@k**: probabilidad de al menos 1 éxito en k intentos → sube con k. Útil cuando “con que aciertes una vez, alcanza”.
- **pass^k**: probabilidad de que **los k** intentos pasen → baja con k. Útil para agentes *customer-facing* donde se espera consistencia. Ej.: 75% por trial, 3 trials → 0.75³ ≈ 42%.
- En email-triage, como respondés a clientes, **pass^k es el más honesto**: ¿clasifica bien el mismo email las 5 veces? Usá *multi-run* para medirlo.

### Práctica
- Convertí 5 líneas de `dataset.jsonl` a `Case` y corré un `Dataset.evaluate_sync` mínimo enviando traces a Logfire.
- Reimplementá `is_correct` como un `Evaluator` y reproducí tu accuracy.
- Agregá un `LLMJudge` built-in y compará su veredicto con tu `JudgeAgent` (¿coinciden? esto es *calibración entre graders*).

### Preguntas de control
- ¿Por qué Anthropic recomienda graders deterministas siempre que se pueda y LLM solo donde haga falta?
- ¿Qué es saturación de un eval y por qué un eval al 100% es un problema?
- ¿Por qué tu ECE (calibración) es un eval valioso que mucha gente no hace?

---

## 6. Bloque 5 — Online evaluation y el panorama completo

**Objetivo:** cerrar con producción: evaluar tráfico real, y entender que los evals son **una capa** de un sistema holístico.

### Leer
- Pydantic Evals — **Online Evaluation** (decorator `@evaluate`, `OnlineEvaluation` capability, `sample_rate`, sinks, `run_evaluators`, re-run desde datos almacenados).
  https://ai.pydantic.dev/evals/online-evaluation/
- Logfire — **Evals: Live Monitoring**.
  https://pydantic.dev/docs/logfire/evaluate/live-evals/
- Anthropic — tabla **overview of approaches** (automated evals, production monitoring, A/B testing, user feedback, manual transcript review, human studies) + modelo **Swiss cheese**.

### Conceptos clave
- **Offline** (`Dataset.evaluate`) corre contra un banco estático de cases, ideal para CI/CD y model upgrades. **Online** evalúa output real en producción, en background, con muestreo.
- Patrón online con Pydantic AI: agregás la capability al agente y los evaluators se despachan async tras cada run, emitiendo eventos OTel:

```python
from pydantic_evals.online_capability import OnlineEvaluation
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

class OutputNotEmpty(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return bool(ctx.output)

agent = Agent(model, name='triage', capabilities=[OnlineEvaluation(evaluators=[OutputNotEmpty()])])
```

- **`sample_rate`** y **`max_concurrency`** protegen el critical path: los evaluators caros se muestrean y, si se satura, se **dropean** (no se encolan). Clave para no degradar latencia de `/triage`.
- **Re-run desde datos almacenados** (`run_evaluators`, `EvaluatorContextSource`): podés correr **rúbricas nuevas sobre traces históricos** sin reejecutar el modelo. Potentísimo para “qué hubiera pasado con esta rúbrica nueva”.
- **Swiss cheese model:** ninguna capa atrapa todo. Automated evals (rápido, pre-launch/CI) + production monitoring (ground truth, reactivo) + A/B testing + user feedback (tu botón thumbs-down) + transcript review + human studies. Lo que se escapa de una capa lo atrapa otra.

### Aplicado a email-triage
- Tu agente ya emite spans y métricas. Agregar `OnlineEvaluation` con un par de checks baratos (output no vacío, idioma coincide, confidence en rango) te da *online evals* con bajo costo.
- Tu botón de feedback (thumbs-down, si lo agregás en el frontend) sería la capa *user feedback*.
- Conectá `confidence` (ya la histograma-eás) con un alert en Logfire cuando caiga sistemáticamente.

### Preguntas de control
- ¿Cuándo offline y cuándo online? ¿Por qué no alcanza solo uno?
- ¿Cómo evitás que un LLM judge online te mate la latencia de producción? (`sample_rate` + `max_concurrency` + drop.)
- ¿Qué ventaja te da re-evaluar traces históricos con una rúbrica nueva?

---

## 7. Checklist de roadmap para email-triage (lo que proponés al final de la charla)

Ordenado por relación impacto/esfuerzo:

1. **[Alto / Bajo]** Subir `SYSTEM_PROMPT` a Logfire Prompt Management (v1, label `production`) y consumirlo con `logfire.var`. Habilita rollback sin redeploy.
2. **[Alto / Medio]** Migrar `evals/` a `pydantic_evals.Dataset/Case/Evaluator`, conservando tus métricas (accuracy, macro-F1, ECE) como evaluators custom. Ganás la vista web de evals en Logfire.
3. **[Medio / Bajo]** Separar la suite en **capability** (casos difíciles, pass rate bajo) y **regression** (casos resueltos, ~100%).
4. **[Medio / Medio]** Agregar **multi-run** y reportar **pass^k** (consistencia), no solo accuracy de una corrida.
5. **[Medio / Bajo]** Dar al judge la salida **“Unknown”** para reducir hallucinations y calibrarlo contra una muestra de revisión humana.
6. **[Alto / Medio]** Agregar **online evals** (`OnlineEvaluation`) con checks baratos + `sample_rate`, integrando con tus métricas.
7. **[Bajo / Bajo]** Balancear el dataset por categoría (mirá `support` en el report) y documentar el origen de cada case (falla real vs sintético).

---

## 8. Glosario rápido (para no dudar en vivo)

- **Trace / span tree:** árbol de spans OTel de una ejecución. Tu `triage.sync` es un span raíz; las llamadas al LLM y httpx cuelgan de él.
- **Grader / evaluator:** lógica que puntúa una parte del transcript o del outcome.
- **Assertion / check:** una afirmación booleana dentro de un grader.
- **Capability eval:** “¿qué sabe hacer?” — pass rate bajo al inicio, hill-climbing.
- **Regression eval:** “¿sigue haciendo lo que hacía?” — ~100%, anti-backslide.
- **pass@k / pass^k:** al-menos-uno vs. todos-los-k éxitos.
- **ECE (Expected Calibration Error):** gap entre confidence declarada y accuracy real (lo calculás en `metrics.py`).
- **Prompt version:** snapshot inmutable del template (v1, v2…). **Label:** puntero movible (`production`) hacia una versión.
- **Online eval:** evaluación de output real en producción, async y muestreada.

---

## Fuentes

- [Demystifying evals for AI agents — Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Pydantic Evals — Overview](https://ai.pydantic.dev/evals/)
- [Pydantic Evals — Logfire Integration](https://ai.pydantic.dev/evals/how-to/logfire-integration/)
- [Pydantic Evals — Online Evaluation](https://ai.pydantic.dev/evals/online-evaluation/)
- [Logfire — Prompt Management (Overview)](https://pydantic.dev/docs/logfire/prompt-management/)
- [Logfire — Prompt Management (Core Concepts)](https://pydantic.dev/docs/logfire/prompt-management/concepts/)
- [Logfire — Use Prompts in Your Application](https://pydantic.dev/docs/logfire/prompt-management/application/)
- [Logfire — Managed Variables](https://pydantic.dev/docs/logfire/manage/managed-variables/)
- [Logfire — Evals: Datasets & Experiments](https://pydantic.dev/docs/logfire/evaluate/evals/)
- [Pydantic AI — Logfire integration](https://pydantic.dev/docs/logfire/integrations/llms/pydanticai/)
