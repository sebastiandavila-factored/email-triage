# 31. Trace-Debug Chat — Backend (agente sobre el MCP de Logfire) + RBAC

**Status:** 🚧 implemented (pending human review/merge). Dep bump to MCP 2026-07-28 deferred as follow-up (see risks).
**Estimate:** ~6 hrs
**Depends on:** Plan 12 (observabilidad Logfire, spans con `tenant_id`), Plan 21 (RBAC + `require_scope`), Plan 25 (`/triage` dynamic), Plan 27 (patrón MCP).
**Relacionado:** Plan 32 (UI del panel de chat), Plan 33 (propagar `tenant_id` a `/stream` y spans hijos).

## Intent

Dar a **owner y admin** una forma de **debuguear una triage concreta** preguntando en lenguaje
natural, sin salir del producto ni tener cuenta en Logfire. Un **agente backend** (pydantic-ai)
con acceso al **MCP remoto de Logfire** responde como un "customer service técnico", razonando
sobre los traces de *ese* momento (esa triage + ese draft).

La telemetría ya existe: los spans de `/triage` etiquetan `tenant_id`
(`routers/triage.py:63`). Este plan añade la **superficie de consulta** (endpoint + agente) y su
**aislamiento multi-tenant**. Materializa observabilidad accionable + diseño de tools/MCP (dominio 4
de la certificación) sobre datos reales de producción.

## Prior reading

- Changelog **MCP 2026-07-28**: https://modelcontextprotocol.io/specification/2026-07-28/changelog
  (protocolo *stateless*, headers `Mcp-Method`/`Mcp-Name`, **Sampling/Roots/Logging deprecados**).
- **Logfire MCP** (remoto): `https://logfire-us.pydantic.dev/mcp` (US) — auth por **read token**
  con scope `project:read` como Bearer; tool `arbitrary_query` (SQL sobre records OTel).
- pydantic-ai MCP client: `pydantic_ai.mcp.MCPServerStreamableHTTP` (hook `process_tool_call`),
  `pydantic_ai.toolsets.filtered` (ocultar tools), `services/groq.py:build_groq_model`.
- RBAC existente: `auth/scopes.py` (`ROLE_SCOPES`), `deps.py:require_scope` + `WorkspaceContext`.

## Seguridad — el punto crítico

**El read token / MCP de Logfire es a nivel de proyecto**: quien lo tenga ve los traces de *todos*
los tenants. Por eso:

1. El token vive **solo en el backend** (env), nunca llega al cliente.
2. El aislamiento por organización lo garantiza **nuestro código, no el LLM**: `arbitrary_query`
   queda **oculto al modelo**; exponemos tools propias que construyen el SQL con
   `WHERE attributes->>'tenant_id' = :tenant_id [AND trace_id = :trace_id]` como *bound params*.
   El modelo solo aporta parámetros no inyectables (nivel, límite, nombre de span) → el aislamiento
   es **estructural**: el modelo no puede expresar una query sin el filtro de tenant.
3. **Guard de pertenencia:** el `tenant_id` se deriva del rol/sesión (`WorkspaceContext`), nunca del
   body. Antes de responder se verifica que el `trace_id` pedido pertenece a ese tenant; si no,
   se rehúsa (evita que un owner pase un `trace_id` ajeno).

## Scope

**Incluido:**
- Nuevo scope `traces:read` (owner + admin) en `auth/scopes.py`; `TracesReadDep` en `deps.py`.
- Config: `logfire_read_token` (`project:read`) + `logfire_mcp_url` (default US) en `config.py` /
  `.env.example`. Sin token → endpoint responde 503 "trace debugging no configurado".
- `email_triage/services/trace_agent.py` (**nuevo**): agente pydantic-ai + `MCPServerStreamableHTTP`
  (Logfire) con `arbitrary_query` filtrado y tools curadas tenant/trace-bound (tabla abajo).
- `email_triage/routers/traces.py` (**nuevo**): `POST /workspaces/{tid}/traces/chat` (SSE), gateado
  por `TracesReadDep`; registrado en `main.py`.
- `trace_id` en la respuesta de `/triage` (`schemas.py` + `routers/triage.py`) para anclar el chat.
- Bump de deps `pydantic-ai-slim` + `mcp` a versiones que hablen MCP 2026-07-28.
- Tests sin red (agente/Logfire mockeados).

**Fuera de scope:**
- UI del panel (→ Plan 32).
- Etiquetar `tenant_id` en `/triage/stream` y spans hijos vía baggage (→ Plan 33).
- Extensiones MCP Tasks / MCP Apps / MRTR (consultas rápidas, UI propia).
- Dashboards/alerts de Logfire vía MCP (solo lectura de traces para el chat).

## Tools expuestas al agente

| Tool | Args del modelo | SQL (tenant/trace fijados por el server) |
|---|---|---|
| `get_trace_summary` | — | spans del `trace_id` actual: nombre, nivel, duración, atributos triage |
| `list_trace_exceptions` | — | excepciones/errores (`level in ('error','warning')`) del `trace_id` |
| `search_org_traces` | span_name?, level?, limit≤50 | spans recientes del **tenant** (nunca de otro) |

`arbitrary_query` del MCP de Logfire **no** se expone al modelo; estas tools lo invocan por dentro
(vía `process_tool_call`) con el `WHERE tenant_id`/`trace_id` inyectado por el servidor.

## Concrete changes

| Archivo | Cambio |
|---|---|
| `pyproject.toml` / `uv.lock` | subir `pydantic-ai-slim` (1.104.0) + `mcp` (2.0.0) a MCP 2026-07-28 |
| `email_triage/auth/scopes.py` | `TRACES_READ = "traces:read"`; añadir a `owner` y `admin` |
| `email_triage/deps.py` | `TracesReadDep = Annotated[WorkspaceContext, Depends(require_scope("traces:read"))]` |
| `email_triage/config.py` | `logfire_read_token: str \| None`, `logfire_mcp_url: str` |
| `.env.example` | `LOGFIRE_READ_TOKEN=`, `LOGFIRE_MCP_URL=` |
| `email_triage/schemas.py` | `trace_id: str \| None = None` en `TriageResponse` / `DynamicTriageResponse` |
| `email_triage/routers/triage.py` | setear `trace_id = format(span.get_span_context().trace_id, "032x")` en el output |
| `email_triage/services/trace_agent.py` | **nuevo** — agente + MCP Logfire + tools tenant-bound + guard |
| `email_triage/routers/traces.py` | **nuevo** — `POST /workspaces/{tid}/traces/chat` (SSE) |
| `email_triage/main.py` | `include_router(traces.router)` |
| `tests/test_traces_chat.py` | **nuevo** — RBAC + aislamiento + guard de pertenencia (sin red) |
| `docs/features/31-*`, `docs/testing/31-*` | docs |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| `arbitrary_query` oculto + tools curadas tenant-bound | Dar SQL libre al modelo con el filtro por prompt | El LLM podría omitir el filtro → fuga cross-tenant; aislamiento debe ser estructural |
| Read token solo en backend | Entregar token/MCP al cliente | El token es project-wide (ve todos los tenants) |
| `tenant_id` desde `WorkspaceContext` (sesión) | `tenant_id` del body | El body es no confiable; el rol valida la org |
| Agente llama al LLM directo (Groq) | Sampling del MCP | Sampling está **deprecado** en MCP 2026-07-28; el spec recomienda LLM provider directo |
| Reusar `build_groq_model` + patrón SSE de `/stream` | Infra nueva | Consistencia; menos superficie |
| Agente inyectable por `Depends` | Instanciar dentro del handler | Testeable con `app.dependency_overrides` (sin red), igual que `get_llm_service` |

## Risks / Open questions

- **Versión de deps para MCP 2026-07-28:** verificar antes de codear que existe release de
  `pydantic-ai-slim`/`mcp` que negocia 2026-07-28 con el MCP remoto de Logfire (stateless, sin
  `Mcp-Session-Id`, headers `Mcp-Method`/`Mcp-Name`). Si no, degradar a la revisión que ambos
  soporten y dejar el bump como follow-up.
- **Streaming vs no-streaming:** recomiendo SSE (coherente con `/stream`); no-streaming es v1 más
  simple. Decidir al implementar el router.
- **Modelo del agente:** `llama-3.3-70b-versatile` (tool-calling en Groq) o uno más fuerte para
  razonar sobre traces. Empezar con el existente.
- **Latencia/costo:** cada mensaje del chat dispara tool-calls a Logfire; acotar `limit`, cachear el
  `get_trace_summary` del trace anclado dentro de la conversación.
- **Read token ausente en prod:** degradación explícita (503 con mensaje), nunca inventar el secreto
  (`CLAUDE.md`).

## Execution order

1. Bump deps + verificar conexión `MCPServerStreamableHTTP` → MCP Logfire (30 min).
2. Scope `traces:read` + `TracesReadDep` + config/env (30 min).
3. `trace_id` en respuesta de `/triage` + test (20 min).
4. `trace_agent.py`: MCP filtrado + tools tenant-bound + guard de pertenencia (120 min).
5. `routers/traces.py` (SSE) + registro en `main.py` (60 min).
6. Tests (RBAC 403/200, aislamiento, guard) + docs `31-*` (90 min).
7. `make check` verde.

## Done when

- [x] `POST /triage` devuelve `trace_id` no vacío
- [x] `POST /workspaces/{tid}/traces/chat`: owner/admin 200, member 403, `trace_id` ajeno → rehúsa
- [x] Test asegura que **toda** consulta a Logfire llevó el predicado `tenant_id` (aislamiento)
- [~] Deps negocian MCP 2026-07-28 contra el MCP remoto de Logfire → **follow-up documentado**
      (jerarquía `MCPServerStreamableHTTP` deprecada y en 2025-11-25; aislada en `LogfireMCPClient`;
      backward-compat del MCP remoto cubre el interín)
- [x] `make check` verde (ruff + pyright 0 + 193 tests); `docs/features/31-*` y `docs/testing/31-*`
- [ ] Humano validó con la guía de testing

> **Ajuste durante ejecución (adaptador de Logfire):** el cliente MCP de pydantic-ai
> (`pydantic_ai.mcp`, 1.104) **no importa** contra el `mcp>=2.0` que el proyecto fija para su
> propio servidor F4 — importa el módulo removido `mcp.shared.session`. Bajar `mcp` rompería F4.
> Como el acceso a Logfire está aislado tras `LogfireTraceClient`, la impl de producción pasó de
> `LogfireMCPClient` (MCP `arbitrary_query`) a **`LogfireQueryApiClient`** sobre
> `logfire.experimental.query_client.AsyncLogfireQueryClient` — la **misma** Query API de Logfire
> que el MCP envuelve, pero con el cliente oficial (alineado en versión, `base_url` derivada del
> read token). Volver al MCP es un cambio de una sola clase cuando las versiones alineen. Smoke
> test real: token OK (`sebastian-davila/email-triage`), las columnas del SQL existen en `records`.
