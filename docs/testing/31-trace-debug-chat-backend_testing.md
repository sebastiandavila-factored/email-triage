# Testing: Trace-Debug Chat — Backend

## Prerequisites

- Suite automática: `uv run pytest tests/test_traces_chat.py` (sin DB real ni red: SQLite
  en archivo + `TestModel` de pydantic-ai + cliente Logfire fake).
- Manual end-to-end: backend con `DATABASE_URL`, `LOGFIRE_READ_TOKEN` (scope `project:read`)
  y telemetría fluyendo a Logfire; una cuenta `owner`/`admin` y una `member`.

## Test Cases (automáticos)

Aislamiento de SQL (`services/trace_agent.py`, funciones puras):

### TC-01: la SQL siempre lleva el filtro de tenant
**Action**: `trace_spans_sql(tenant, trace)` y `recent_org_sql(tenant, limit=999)`.
**Expected**: ambas contienen `attributes->>'tenant_id' = '<tenant>'`; la de spans además
`trace_id = '<trace>'`; el `limit` se clampa a 50.

### TC-02: validación anti-inyección
**Action**: `ensure_trace_id("not-a-trace")`, `trace_spans_sql(tenant, "xyz")`,
`trace_spans_sql("'; DROP TABLE records; --", trace)`.
**Expected**: `LogfireQueryError` en los tres (trace no-hex / tenant no-UUID).

Guardrail del agente (agente sobre `TestModel` + cliente fake):

### TC-03: el agente solo consulta su tenant
**Action**: `TraceChatService(agent, fake).chat(tenant, trace, "why slow?", [])`.
**Expected**: responde `str`; **todas** las queries que recibió el fake contienen el
predicado del tenant (aislamiento estructural — el modelo no puede omitirlo).

### TC-04: ownership guard sin filas
**Action**: `owns_trace(tenant, trace)` con el fake devolviendo `[]`.
**Expected**: `False` (→ el endpoint responde 404).

Endpoint RBAC (ASGITransport + SQLite sembrado con owner/admin/member/outsider):

### TC-05: sin auth
**Action**: `POST /workspaces/{tid}/traces/chat` sin token. **Expected**: 401.

### TC-06: member sin scope
**Action**: `POST` como `member`. **Expected**: 403, detalle incluye `traces:read`.

### TC-07: outsider (IDOR)
**Action**: `POST` como usuario no-miembro del workspace. **Expected**: 403.

### TC-08: feature no configurada
**Action**: `POST` como `owner` sin `LOGFIRE_READ_TOKEN`. **Expected**: 503.

### TC-09: owner y admin obtienen respuesta
**Action**: `POST` como `owner` y como `admin` (servicio fake). **Expected**: 200, `reply`
con el contenido esperado; el servicio recibió el `tenant_id` de la membership (no del body).

### TC-10: trace ajeno / inexistente
**Action**: `POST` como `owner`, `owns_trace` → `False`. **Expected**: 404.

### TC-11: trace_id mal formado
**Action**: `POST` con `trace_id` no-hex; `owns_trace` lanza `LogfireQueryError("invalid
trace id …")`. **Expected**: 422.

### TC-12: las tools tienen parámetro (quirk de Groq)
**Action**: introspección de `get_trace_spans` / `search_recent_org_traces`.
**Expected**: ambas tienen ≥1 parámetro además de `ctx`. Groq manda `null` (no `{}`) a una tool
sin parámetros → falla la validación de schema y agota reintentos; un parámetro lo evita.

### TC-13: fallo del agente → error manejado
**Action**: agente cuyo `run` lanza. **Expected**: `chat()` lo traduce a `LogfireQueryError`
(→ el endpoint responde 503, nunca un 500 crudo).

## Manual end-to-end

1. Correr una triage: `POST /triage` (con API key) → la respuesta trae `trace_id` no vacío.
2. Con `LOGFIRE_READ_TOKEN` seteado, `POST /workspaces/{tid}/traces/chat` como owner con ese
   `trace_id` y `message: "¿por qué esta triage fue lenta y qué categoría salió?"`.
   **Expected**: respuesta razonada a partir de los spans reales.
3. Repetir como `member` → 403. Con un `trace_id` de otro workspace → 404.
4. Verificar (logs/Logfire) que **toda** consulta emitida llevó el filtro `tenant_id`.

## Gates

`uv run ruff format && uv run ruff check && uv run pyright && uv run pytest` — verde
(ruff ok, pyright 0, 193 tests).
