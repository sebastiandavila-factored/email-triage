# 43. Agente de diagnóstico de trazas — loop multi-paso + veredicto estructurado

**Status:** 🚧 implemented (pending human review/merge)
**Estimate:** ~5 hrs
**Depends on:** Plan 31 (trace-debug agent + `LogfireQueryApiClient` + aislamiento estructural), Plan 33 (baggage `tenant_id` en spans), Plan 25 (Groq/pydantic-ai).
**Habilita:** Plan 44 (copiloto de tuning consume el diagnóstico), Plan 42 (este agente es el sujeto de las 6 métricas).

## Intent

El agente de Plan 31 (`services/trace_agent.py`) **ya es** un agente pydantic-ai con tools curadas
sobre Logfire y loop ReAct: el modelo decide si llama `get_trace_spans` y/o
`search_recent_org_traces`, y cuántas veces, hasta responder. Hoy se usa como **chat de texto
libre**.

Este plan lo convierte en un **primitivo de diagnóstico reutilizable**: dado un `trace_id`, el
agente investiga y devuelve un **veredicto estructurado** `TraceDiagnosis` (causa raíz + spans de
evidencia + confianza + tipo de fix sugerido + slug objetivo). Dos consumidores:

- **Humano:** owner/admin pide el diagnóstico de una triage (endpoint).
- **Máquina:** el copiloto de tuning (Plan 44) lo llama como sub-paso antes de proponer un cambio.

Genuinamente agéntico (por eso es sujeto de Plan 42): el nº de tool-calls e iteraciones **no se
conoce de antemano** — depende de lo que el agente encuentre en las trazas.

## Prior reading

- [services/trace_agent.py](../../email_triage/services/trace_agent.py) — SQL builders (`trace_spans_sql`, `recent_org_sql`, `ensure_trace_id`, `_safe_tenant`), `TraceDeps`, tools `get_trace_spans`/`search_recent_org_traces`, `build_trace_agent`, `TraceChatService` (con `owns_trace`), `LogfireQueryApiClient`, `build_trace_chat_service`.
- [routers/traces.py](../../email_triage/routers/traces.py) — `_cached_service` (lru_cache), `get_trace_chat_service` (dep → servicio o `None`→503), `TraceChatServiceDep`, `POST /chat`, mapeo `LogfireQueryError`→422/503, `owns_trace`→404.
- [deps.py](../../email_triage/deps.py) — `WorkspaceContext(user_id, tenant_id, role)`, `require_scope`, `TracesReadDep` (`traces:read`).
- [schemas.py](../../email_triage/schemas.py) — `TraceChatRequest/Response`; aquí van `EvidenceSpan`/`TraceDiagnosis`.
- [tests/test_traces_chat.py](../../tests/test_traces_chat.py) — `FakeLogfireClient` (graba SQL, devuelve rows canned), `TestModel` (llama cada tool una vez), aserciones de aislamiento estructural, HTTP con ASGITransport + SQLite seed.
- Plan 33 (nota): los `triage.sync` **viejos** en Logfire no llevan `tenant_id` → el diagnóstico útil requiere **tráfico nuevo**.

---

## Diseño en detalle

### 1. Schemas (`schemas.py`)

```python
class EvidenceSpan(BaseModel):
    """Un span citado como evidencia. El agente lo llena SOLO con datos que las tools
    devolvieron (el system prompt prohíbe inventar)."""
    span_name: str
    level: int | None = None          # nivel Logfire (9=info, 13=warn, 17=error)
    duration_ms: float | None = None
    note: str = Field(default="", max_length=280)  # p.ej. "category=refunds confidence=0.42"


FixKind = Literal["add_counter_example", "tweak_category", "adjust_examples", "none"]


class TraceDiagnosis(BaseModel):
    """Veredicto estructurado de por qué una triage se comportó como lo hizo."""
    root_cause: str = Field(min_length=1, max_length=1_000)
    evidence: list[EvidenceSpan] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_fix_kind: FixKind
    target_slug: str | None = None    # categoría a la que apunta el fix (para Plan 44)
    rationale: str = Field(min_length=1, max_length=1_000)
```

`target_slug` + `suggested_fix_kind` son los hooks que Plan 44 usa para actuar sin re-parsear texto.
`suggested_fix_kind="none"` es una salida válida (la triage estaba bien, o el problema es infra).

### 2. Reutilizar la toolset + extraer `owns_trace` (mínimo refactor de Plan 31)

Las tools y el aislamiento **no cambian**: el agente de diagnóstico usa la **misma**
`FunctionToolset([get_trace_spans, search_recent_org_traces])`. Para no duplicar el guard de
propiedad, se extrae una función libre y `TraceChatService.owns_trace` la delega (cubierto por sus
tests actuales):

```python
async def owns_trace(client: LogfireTraceClient, tenant_id: str, trace_id: str) -> bool:
    """True iff la traza tiene ≥1 span de este tenant (ANDea ambos predicados → sin fuga)."""
    rows = await client.query(trace_spans_sql(tenant_id, trace_id, limit=1))
    return len(rows) > 0
```

### 3. Agente de diagnóstico (`services/trace_agent.py`)

```python
DIAGNOSIS_SYSTEM_PROMPT = (
    "You are a support engineer producing a STRUCTURED diagnosis of ONE email-triage "
    "request from its Logfire traces.\n"
    "- First call the tools to fetch the trace's spans; if a symptom (error, high latency, "
    "low confidence) might be recurring, also look at recent org traces.\n"
    "- Ground EVERY field in returned data; never invent spans, numbers, categories or errors. "
    "Put the concrete spans you relied on in `evidence`.\n"
    "- Set `suggested_fix_kind`: `add_counter_example` when the model picked a category it "
    "shouldn't (a counter-example would help); `tweak_category` when a category's description is "
    "ambiguous; `adjust_examples` when existing few-shots mislead; `none` when config wouldn't "
    "help (correct result, or an infra/LLM outage).\n"
    "- When the fix targets a category, set `target_slug` to that category's slug.\n"
    "- If the tools return nothing, say so via `suggested_fix_kind=none` and low `confidence`."
)

def build_diagnosis_agent(model: Model) -> Agent[TraceDeps, TraceDiagnosis]:
    toolset = FunctionToolset[TraceDeps]([get_trace_spans, search_recent_org_traces])
    return Agent(
        model,
        deps_type=TraceDeps,
        output_type=TraceDiagnosis,          # salida estructurada
        toolsets=[toolset],
        system_prompt=DIAGNOSIS_SYSTEM_PROMPT,
    )
```

### 4. Servicio (`services/trace_agent.py`)

```python
class TraceDiagnosisService:
    def __init__(self, agent: Agent[TraceDeps, TraceDiagnosis], client: LogfireTraceClient):
        self._agent = agent
        self._client = client

    async def owns_trace(self, tenant_id: str, trace_id: str) -> bool:
        return await owns_trace(self._client, tenant_id, trace_id)

    async def diagnose(self, tenant_id: str, trace_id: str) -> TraceDiagnosis:
        deps = TraceDeps(self._client, tenant_id, ensure_trace_id(trace_id))
        try:
            # Seam para Plan 42: este `agent.run` es lo que envuelve `instrument_agent_run`.
            result = await self._agent.run(
                f"Diagnose triage trace {trace_id}.", deps=deps
            )
        except LogfireQueryError:
            raise
        except Exception as exc:  # noqa: BLE001 — modelo/tool/transport → 503 accionable
            raise LogfireQueryError(
                "The diagnosis assistant could not complete; please retry."
            ) from exc
        out = result.output
        out.confidence = max(0.0, min(1.0, out.confidence))  # clamp defensivo
        return out


def build_diagnosis_service(
    *, groq_model: str, groq_api_key: str, read_token: str, base_url: str | None = None
) -> TraceDiagnosisService:
    agent = build_diagnosis_agent(build_groq_model(groq_model, groq_api_key))
    return TraceDiagnosisService(agent, LogfireQueryApiClient(read_token, base_url))
```

### 5. Salida estructurada con Groq — decisión y fallback

**Primario:** un solo agente con `output_type=TraceDiagnosis` (pydantic-ai genera un "final-result
tool"; el modelo llama primero las tools de datos y luego el de salida). llama-3.3-70b soporta
function calling, así que debería andar.

**Riesgo real:** combinar tools de datos + tool de salida estructurada puede ser menos fiable en
Groq (agota reintentos). **Fallbacks, en orden:**
1. `output_type=PromptedOutput(TraceDiagnosis)` — el modelo emite JSON en el texto (mismo patrón que
   `llm.py` usa en streaming); evita el juego con el final-result tool.
2. **Dos fases:** reusar el agente chat (str) para el análisis libre, y un segundo `Agent` **sin
   tools** con `output_type=TraceDiagnosis` que convierte análisis→estructura. Más robusto y da
   telemetría más limpia (dos runs), a costa de una llamada extra.

Se arranca con el primario; si en pruebas reales falla, se baja al fallback 1 y luego al 2.

### 6. Endpoint + wiring (`routers/traces.py`)

Se calca el patrón de `/chat` (lru_cache por config para no filtrar httpx clients):

```python
@lru_cache(maxsize=1)
def _cached_diagnosis_service(groq_model, groq_api_key, read_token, base_url):
    return build_diagnosis_service(groq_model=..., groq_api_key=..., read_token=..., base_url=...)

def get_trace_diagnosis_service(settings: SettingsDep) -> TraceDiagnosisService | None:
    if not settings.logfire_read_token:
        return None
    return _cached_diagnosis_service(settings.groq_model, settings.groq_api_key,
                                     settings.logfire_read_token, settings.logfire_read_base_url)

TraceDiagnosisServiceDep = Annotated[TraceDiagnosisService | None, Depends(get_trace_diagnosis_service)]

@router.post("/{trace_id}/diagnose", response_model=TraceDiagnosis)
async def diagnose_trace(
    trace_id: str, ctx: TracesReadDep, service: TraceDiagnosisServiceDep
) -> TraceDiagnosis:
    if service is None:
        raise HTTPException(503, "Trace diagnosis is not configured")
    tenant_id = str(ctx.tenant_id)
    try:
        owns = await service.owns_trace(tenant_id, trace_id)
    except LogfireQueryError as exc:                     # id inválido → 422, resto → 503
        raise HTTPException(422 if "trace id" in str(exc) else 503, str(exc)) from exc
    if not owns:
        raise HTTPException(404, "Trace not found for this workspace")
    try:
        return await service.diagnose(tenant_id, trace_id)
    except LogfireQueryError as exc:
        raise HTTPException(503, str(exc)) from exc
```

Ruta: `POST /workspaces/{tid}/traces/{trace_id}/diagnose` (no colisiona con `/chat`). `trace_id`
llega por path y `ensure_trace_id` lo valida (32 hex) antes de cualquier query.

### 7. Seam de telemetría (para Plan 42)

`diagnose` aísla el `await agent.run(...)` para que Plan 42 lo envuelva con `instrument_agent_run`
(latencia, `result.usage()` → tokens/contexto, `result` → iteraciones) y cuelgue un span
`trace.diagnose` con `tenant_id` en baggage (patrón Plan 33). **Este plan no agrega instrumentos de
métrica** — solo deja el punto de enganche.

---

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/schemas.py` | `EvidenceSpan`, `TraceDiagnosis`, `FixKind` |
| `email_triage/services/trace_agent.py` | `owns_trace` (free fn) + delegación en `TraceChatService.owns_trace`; `DIAGNOSIS_SYSTEM_PROMPT`; `build_diagnosis_agent`; `TraceDiagnosisService`; `build_diagnosis_service` |
| `email_triage/routers/traces.py` | `_cached_diagnosis_service`, `get_trace_diagnosis_service`, `TraceDiagnosisServiceDep`, `POST /{trace_id}/diagnose` |
| `tests/test_trace_diagnosis.py` | **nuevo** — ver matriz abajo |
| `docs/features/43-*` | doc |

## Matriz de tests (`tests/test_trace_diagnosis.py`, sin red)

| Test | Cómo | Aserta |
|---|---|---|
| Estructura del veredicto | `TraceDiagnosisService(build_diagnosis_agent(TestModel()), FakeLogfireClient())` | devuelve `TraceDiagnosis` válido (pydantic), `confidence∈[0,1]` |
| Aislamiento estructural | ídem, inspeccionar `fake.queries` | **toda** query lleva `attributes->>'tenant_id' = '{tenant}'` |
| Loop multi-paso | `FunctionModel` que llama `get_trace_spans` → según rows llama `search_recent_org_traces` → emite salida | ≥2 tool-calls registrados (señal de iterations para Plan 42) |
| `owns_trace` 404 | `FakeLogfireClient(rows=[])` | `owns_trace` → `False` |
| trace-id inválido | `ensure_trace_id("nope")` / endpoint con `trace_id` no-hex | `LogfireQueryError` / HTTP 422 |
| Endpoint 503 sin token | override `get_trace_diagnosis_service` → `None` | HTTP 503 |
| Endpoint happy-path | override con servicio fake (TestModel), ASGITransport + SQLite seed + JWT `traces:read` | HTTP 200 + payload `TraceDiagnosis` |
| RBAC | miembro sin `traces:read` | HTTP 403 (del `require_scope`) |

Reusa `FakeLogfireClient`, `TestModel`/`FunctionModel`, y el andamiaje HTTP de `test_traces_chat.py`.

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Reusar la toolset curada de Plan 31 | Tools nuevas con SQL libre | Mantiene el aislamiento **estructural** (el modelo nunca ve `arbitrary_query`) |
| Salida `TraceDiagnosis` estructurada | Texto libre (como el chat) | Plan 44 necesita actuar sobre `suggested_fix_kind`/`target_slug`; el texto no es accionable |
| Servicio **separado** `TraceDiagnosisService` | Método `diagnose` en `TraceChatService` | Necesita un agente distinto (output estructurado); separar evita mezclar dos runtimes |
| `owns_trace` como free fn compartida | Duplicar el guard | DRY con un cambio de una línea en Plan 31 (cubierto por sus tests) |
| Read-only (sin escrituras) | Que el mismo agente aplique el fix | Separación de responsabilidades; el diagnóstico es reutilizable y auditable |
| Endpoint humano + servicio interno | Solo servicio interno | Owner/admin pide diagnóstico directo; Plan 44 lo consume |
| `trace_id` por path | En el body (como `/chat`) | Está anclado y es 32-hex; path es más REST y `ensure_trace_id` lo valida |

## Risks / Open questions

- **Fiabilidad de salida estructurada + tools en Groq:** ver §5; primario = un agente, con dos
  fallbacks documentados. Validar en pruebas reales antes de dar por cerrado.
- **Tráfico nuevo:** las trazas viejas no llevan `tenant_id` (Plan 33) → el diagnóstico útil requiere
  triages del código actual; documentarlo en la guía del taller.
- **Zero-arg tools en Groq:** las tools ya llevan `limit` (Plan 31 lo resolvió porque Groq manda
  `null` para tools sin args); mantener ese patrón si se agrega una tool nueva.
- **Calibración de `confidence`:** iterar el prompt con casos conocidos; posible eval offline.
- **Loop desbocado:** el trace es chico y las tools están acotadas (`_MAX_ROWS`, `LIMIT 50`); si hace
  falta, agregar `usage_limits` al `agent.run`.

## Execution order

1. Schemas `EvidenceSpan`/`TraceDiagnosis`/`FixKind` (30 min).
2. `owns_trace` free fn + delegación en `TraceChatService` (15 min).
3. `DIAGNOSIS_SYSTEM_PROMPT` + `build_diagnosis_agent` + `TraceDiagnosisService` + `build_diagnosis_service` (75 min).
4. Router: cache + dep + `POST /{trace_id}/diagnose` con mapeo de errores (45 min).
5. Tests (matriz completa) con `FakeLogfireClient` + `TestModel`/`FunctionModel` (90 min).
6. (si Groq falla en §5) bajar al fallback 1/2 y re-testear (30 min buffer).
7. Doc `43-*`; `make check` verde.

## Done when

- [x] `POST /workspaces/{tid}/traces/{trace_id}/diagnose` devuelve un `TraceDiagnosis` estructurado
- [x] El agente decide dinámicamente qué tools llamar (loop de nº variable; test de ≥2 tool-calls)
- [x] Aislamiento estructural: toda query lleva el predicado `tenant_id` (test)
- [x] `owns_trace` bloquea diagnosticar una traza de otro tenant (404); `traces:read` gatea (403)
- [x] `suggested_fix_kind` + `target_slug` cubren lo que Plan 44 necesita; `none` es válido
- [x] El agente es read-only (no escribe config ni Logfire)
- [x] `diagnose` aísla el `agent.run` como seam para `instrument_agent_run` (Plan 42)
- [x] Ningún test toca Logfire/Groq/red (fake client + `TestModel`/`FunctionModel`) — `CLAUDE.md`
- [x] `make check` verde (ruff + pyright 0 + **247 tests**)
- [ ] Validado con Groq real sobre una traza nueva (§5: salida estructurada + tools; con `TestModel` pasa, falta el modelo real)
