# 41. Reporte de voz — Workflow de resumen + guion (pydantic-ai)

**Status:** 🚧 implemented (pending human review/merge)
**Estimate:** ~4 hrs
**Depends on:** Plan 38 (forma de `InboxItem`), Plan 25 (Groq/pydantic-ai). Instrumentable por Plan 42.
**Relacionado:** UI → Plan 46 F1.

## Intent

Feature que pidió el usuario: **resumir** los correos triados y escribir un **guion** para un reporte
de voz, con buen copy y estructura profesional. Arquitectura firme: **workflow determinista** (prompt
chaining `resumir → guionizar`); no es un agente (pipeline conocido). v1 = **solo el guion (texto)**;
TTS queda para después (`VoiceReport.audio_url = None`).

**Cambio de diseño (vs el boceto):** el endpoint recibe los **`items` que el cliente ya tiene** en
pantalla (de un sync previo), en vez de re-sincronizar Gmail. Así el workflow queda **desacoplado de
Gmail** (sin refactor de Plan 37, sin re-triage, sin coste extra) y reporta exactamente lo que el
usuario ve.

## Prior reading

- [schemas.py](../../email_triage/schemas.py) — `InboxItem` (`sender`, `subject`, `category`, `confidence`, `draft_reply`, `trace_id`); aquí van los nuevos schemas.
- [services/llm.py](../../email_triage/services/llm.py) — patrón `Agent(model, output_type=…)` + `build_groq_model`.
- [services/tuning.py](../../email_triage/services/tuning.py) / [services/trace_agent.py](../../email_triage/services/trace_agent.py) — patrón Runner + factory + dep con `lru_cache` (a calcar).
- [services/agent_telemetry.py](../../email_triage/services/agent_telemetry.py) — `instrument_agent_run` (Plan 42) para emitir tokens/latencia de los 2 pasos LLM.

## Diseño en detalle

### 1. Schemas (`schemas.py`)

```python
class ReportSummary(BaseModel):           # salida del agente resumidor
    headline: str = Field(min_length=1, max_length=300)
    themes: list[str] = Field(max_length=8)
    urgent: list[str] = Field(max_length=8)   # remitentes/asuntos que piden atención

class VoiceScriptSection(BaseModel):
    heading: str
    body: str

class VoiceScript(BaseModel):              # salida del agente guionista
    opening: str
    sections: list[VoiceScriptSection] = Field(max_length=10)
    closing: str

class CategoryCount(BaseModel):
    category: str
    count: int

class VoiceReport(BaseModel):
    script: VoiceScript
    headline: str
    by_category: list[CategoryCount]       # ← calculado por el harness (no el LLM)
    total: int                             # ← calculado por el harness
    audio_url: str | None = None           # contrato listo para TTS futuro

class VoiceReportRequest(BaseModel):
    items: list[InboxItem] = Field(max_length=100)
```

> `by_category`/`total` los computa el **harness** (Counter sobre los items) → exactos, no
> alucinables. El LLM solo escribe prosa (`headline`, `themes`, `urgent`, y el guion). Mismo patrón
> "harness autoritativo" que Plan 44.
>
> **Nota structured-output:** se evita `dict[str,int]` a propósito (`additionalProperties` no lo
> soporta strict); por eso `by_category` es `list[CategoryCount]`.

### 2. Servicio (`services/voice_report.py`)

```python
SUMMARY_SYSTEM_PROMPT = ("You summarize a support inbox for a spoken daily briefing. From the "
    "triaged items, produce a crisp headline, the key themes, and which senders/subjects need "
    "attention. Ground every claim in the items; don't invent counts.")

SCRIPT_SYSTEM_PROMPT = ("You are a scriptwriter for a professional voice briefing. Turn the summary "
    "into a short, well-structured script: a warm opening, one section per theme with concrete "
    "copy, and a closing with the single most important next action. Natural, spoken tone.")

def build_summary_agent(model: Model) -> Agent[None, ReportSummary]:
    return Agent(model, output_type=ReportSummary, system_prompt=SUMMARY_SYSTEM_PROMPT)

def build_script_agent(model: Model) -> Agent[None, VoiceScript]:
    return Agent(model, output_type=VoiceScript, system_prompt=SCRIPT_SYSTEM_PROMPT)

def _render_items(items: list[InboxItem]) -> str: ...   # compact text: "- [refunds 0.92] Maya: Where is my order?"
def _render_summary(s: ReportSummary) -> str: ...

async def run_voice_report(
    *, summary_agent: Agent[None, ReportSummary], script_agent: Agent[None, VoiceScript],
    items: list[InboxItem],
) -> VoiceReport:
    counts = Counter(i.category for i in items)
    by_category = [CategoryCount(category=c, count=n) for c, n in counts.items()]
    if not items:                                   # degrade sin LLM
        script = VoiceScript(opening="No hay correos relevantes hoy.", sections=[],
                             closing="Sin novedades. Buen día.")
        return VoiceReport(script=script, headline="Sin correos hoy", by_category=[], total=0)
    summary = (await instrument_agent_run("voice_summary", summary_agent.run(_render_items(items)))).output
    script = (await instrument_agent_run("voice_script", script_agent.run(_render_summary(summary)))).output
    return VoiceReport(script=script, headline=summary.headline, by_category=by_category, total=len(items))
```

- **Runner + factory** (calcando 44): `VoiceReportRunner(summary_agent, script_agent)` con
  `.run(items)`; `build_voice_report_runner(groq_model, groq_api_key)`.
- **Instrumentación (Plan 42):** los 2 `agent.run` van envueltos → emiten tokens/latencia/contexto
  (métricas 1/3/5) etiquetadas `agent="voice_summary"|"voice_script"`. Sin tool-calls/iterations (es
  un workflow) — y está bien.

### 3. Endpoint (`routers/reports.py`)

```python
router = APIRouter(tags=["reports"])

def get_voice_report_runner(settings: SettingsDep) -> VoiceReportRunner:
    return _cached_runner(settings.groq_model, settings.groq_api_key)   # groq siempre configurado → sin 503

@router.post("/reports/voice", response_model=VoiceReport)
async def voice_report(body: VoiceReportRequest, ctx: WriteTriageDep, runner: ...) -> VoiceReport:
    return await runner.run(body.items)
```

Scope `triage:write` (cualquier miembro; `WriteTriageDep`). No necesita Logfire (no hay diagnóstico).
`main.py`: `include_router(reports.router)`.

### 4. Structured-output con Groq

Mismo riesgo que Plan 43 §5 (salida estructurada en Groq). Primario: `output_type=ReportSummary/
VoiceScript`. Fallback documentado: `PromptedOutput`. Sin tools, así que es más simple que el
diagnóstico.

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/schemas.py` | `ReportSummary`, `VoiceScriptSection`, `VoiceScript`, `CategoryCount`, `VoiceReport`, `VoiceReportRequest` |
| `email_triage/services/voice_report.py` | **nuevo** — agentes + `run_voice_report` + Runner + factory |
| `email_triage/routers/reports.py` | **nuevo** — `POST /reports/voice` |
| `email_triage/main.py` | `include_router(reports.router)` |
| `tests/test_voice_report.py` | **nuevo** — ver matriz |
| `docs/features/41-*` | doc |

## Matriz de tests (sin red)

| Test | Cómo | Aserta |
|---|---|---|
| Guion estructurado | `VoiceReportRunner(build_summary_agent(TestModel()), build_script_agent(TestModel()))` + items canned | `VoiceReport` válido; `total`/`by_category` exactos (Counter) |
| Bandeja vacía | `items=[]` | script "sin novedades", `total=0`, **sin** llamar al LLM |
| by_category autoritativo | items con categorías repetidas | conteos = Counter real, no del modelo |
| Endpoint happy | override runner (TestModel) + `WriteTriageDep` + JWT `triage:write` | 200 + payload `VoiceReport` |
| RBAC | sin `triage:write` | 403 |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Workflow determinista (2 pasos) | Orquestador con tools | Pipeline conocido; workflow es lo profesional |
| El cliente pasa los `items` | Re-sincronizar Gmail en el endpoint | Desacopla de Gmail; sin refactor de Plan 37, sin re-triage/coste; reporta lo que el usuario ve |
| `by_category`/`total` por el harness | Que el LLM cuente | Exacto, no alucinable (patrón Plan 44) |
| `list[CategoryCount]` | `dict[str,int]` | strict structured-output no soporta `additionalProperties` |
| Instrumentar los 2 `agent.run` | No instrumentar | El workflow aporta 4 de las 6 métricas al taller (1/3/5/6) gratis |
| `VoiceReport.audio_url=None` | No dejar campo | Contrato estable para enchufar TTS |

## Risks / Open questions

- **Structured-output en Groq:** ver §4; fallback `PromptedOutput` documentado.
- **Calidad del copy:** iterar los prompts; posible eval offline (infra `evals/`).
- **Tono por-workspace:** v1 usa tono fijo; usar el `tone` del prompt studio queda como follow-up.
- **Items sin body:** `InboxItem` no trae cuerpo (efímero); el resumen usa subject/sender/category/
  draft — suficiente para un briefing. Documentarlo.

## Execution order

1. Schemas (30 min).
2. `services/voice_report.py`: agentes + `run_voice_report` + Runner/factory + instrumentación (90 min).
3. `routers/reports.py` + `main.py` (30 min).
4. Tests (matriz) con `TestModel` (75 min).
5. Doc `41-*`; `make check` verde.

## Done when

- [x] `POST /reports/voice {items}` devuelve un `VoiceReport` con guion estructurado
- [x] `total`/`by_category` los calcula el harness (exactos), no el LLM
- [x] Bandeja vacía → guion "sin novedades" sin llamar al LLM
- [x] `VoiceReport.audio_url` queda `None`
- [x] Los 2 `agent.run` emiten métricas (Plan 42) etiquetadas `voice_summary`/`voice_script`
- [x] Ningún test toca Groq/red (`TestModel`) — `CLAUDE.md`
- [x] `make check` verde (ruff + pyright 0 + **260 tests**)
- [ ] Validado con Groq real (calidad del guion) — humano
