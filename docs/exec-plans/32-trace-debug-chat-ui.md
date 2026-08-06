# 32. Trace-Debug Chat — UI (panel "Ver traces" en el Dashboard)

**Status:** 🚧 implemented (pending human review/merge)
**Estimate:** ~3 hrs
**Depends on:** Plan 31 (endpoint `/workspaces/{tid}/traces/chat` + `trace_id` en la respuesta de `/triage`).
**Relacionado:** Plan 28 (patrón de UI role-gated con `can()`), Plan 22 (RBAC en el frontend).

## Intent

Añadir en el **Dashboard**, junto a la card de resultado de una triage, un botón **"Ver traces"**
(oculto por defecto, solo owner/admin) que abre un **panel de chat** anclado al `trace_id` de esa
triage. El usuario pregunta en lenguaje natural y ve la respuesta del agente backend (Plan 31),
como un soporte técnico que razona sobre ese trace. Frontend-only.

## Prior reading

- `frontend/src/pages/Dashboard.tsx` — form de triage + card de resultado (`:136`), estado `result`.
- `frontend/src/rbac.ts` — `FRONT_ROLE_SCOPES` + helper `can(role, scope)` (espejo del backend).
- `frontend/src/api.ts` — cliente HTTP, tipo `TriageResponse`, uso de `token`/`apiKey`.
- Plan 28 (`/studio`) — cómo se gatea la UI por rol con `can()`.

## Scope

**Incluido:**
- `rbac.ts`: añadir `'traces:read'` a `owner` y `admin` en `FRONT_ROLE_SCOPES` (espejo de Plan 31;
  solo para mostrar/ocultar — la seguridad se re-valida en el backend).
- `api.ts`: añadir `trace_id?: string` al tipo `TriageResponse`; método
  `traceChat(token, tid, trace_id, message, history)` consumiendo el endpoint SSE.
- `frontend/src/components/TraceChat.tsx` (**nuevo**): hilo de chat (mensajes usuario/agente, input,
  estado de carga/streaming), historial en estado local, anclado a un `trace_id`.
- `Dashboard.tsx`: en la card de resultado, botón **"Ver traces"** visible solo si
  `can(user?.role, 'traces:read')` y `result.trace_id` presente; togglea el panel `TraceChat`
  (oculto por defecto) al lado/debajo del resultado.

**Fuera de scope:**
- Endpoint/agente/RBAC backend (→ Plan 31).
- Visualización rica del span-tree (waterfall/timeline); v1 es chat en texto.
- Persistir el historial del chat entre sesiones (se mantiene en memoria del componente).

## Concrete changes

| Archivo | Cambio |
|---|---|
| `frontend/src/rbac.ts` | `'traces:read'` en `owner` y `admin` |
| `frontend/src/api.ts` | `trace_id?` en `TriageResponse`; método `traceChat(...)` (SSE) |
| `frontend/src/components/TraceChat.tsx` | **nuevo** — panel de chat anclado a `trace_id` |
| `frontend/src/pages/Dashboard.tsx` | botón "Ver traces" (role-gated) + toggle del panel |
| `docs/features/32-*`, `docs/testing/32-*` | docs |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Panel anclado al `trace_id` del resultado actual | Página aparte de "observabilidad" | El usuario pidió debuguear *esa* triage, en contexto |
| Gate con `can(role, 'traces:read')` | Mostrar siempre y fallar en 403 | UX: no ofrecer lo que el rol no puede; backend re-valida igual |
| Historial en estado local del componente | Persistir en backend/DB | v1 simple; el backend recibe `history` en cada request |
| Chat en texto | Waterfall/timeline de spans | Menor superficie; el agente ya resume el trace en lenguaje natural |

## Risks / Open questions

- **Consumo SSE en el cliente:** reusar el patrón de streaming existente del Dashboard/Compare si lo
  hay; si Plan 31 entrega no-streaming, `traceChat` hace un `fetch` normal.
- **Layout:** el Dashboard es una sola columna (`max-w-2xl`); decidir si el panel va debajo del
  resultado (más simple) o en columna lateral (requiere ensanchar el contenedor).
- **`trace_id` ausente:** si el backend aún no lo devuelve (orden de merge), ocultar el botón.

## Done when

- [x] Owner/admin ven "Ver traces" en el resultado; member no lo ve (gate `can()`)
- [x] El panel abre un chat anclado al `trace_id` y muestra respuestas del agente
- [x] `tsc --noEmit` + `eslint` + `vite build` verdes
- [x] `docs/features/32-*` y `docs/testing/32-*` actualizados
- [ ] Humano validó con la guía de testing
