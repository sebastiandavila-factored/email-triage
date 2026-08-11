# 40. Gmail Sync — Filtros de lectura y ventana de días

**Status:** 🚧 implemented (pending human review/merge)
**Estimate:** ~3 hrs
**Depends on:** Plan 37 (`POST /gmail/sync` + `GmailClient.list_today`), Plan 38 (UI `/inbox`).
**Relacionado:** Propuesta madre: [002-gmail-ingestion](../proposals/002-gmail-ingestion.md).

## Intent

Hoy la sync trae siempre lo mismo: **no leídos de las últimas 24h**
(`services/gmail.py:27` → `TODAY_QUERY = "in:inbox is:unread newer_than:1d"`, hardcodeado).
El usuario quiere controlar dos ejes desde la UI:

1. **Estado de lectura:** traer *todos* los correos o *solo no leídos*.
2. **Ventana temporal:** cuántos días hacia atrás consultar (1, 3, 7, … con un tope).

Es un cambio acotado: parametrizar el query de Gmail (que ya se construye del lado servidor) y
exponer dos selectores en `Inbox.tsx`. El motor de triage **no se toca**.

## Prior reading

- [services/gmail.py](../../email_triage/services/gmail.py) — `list_today(http, access_token, query, max_results)` ya acepta `query`; `TODAY_QUERY` es la constante a reemplazar.
- [routers/inbox.py](../../email_triage/routers/inbox.py) — `POST /gmail/sync` hoy **no recibe body**; llama `gmail.list_today(http, access_token, TODAY_QUERY, settings.gmail_sync_max_results)`.
- [schemas.py](../../email_triage/schemas.py) — `SyncResponse`, `InboxItem`; aquí va el nuevo `SyncRequest`.
- [frontend/src/pages/Inbox.tsx](../../frontend/src/pages/Inbox.tsx), `frontend/src/api.ts` — botón "Traer correos" que hoy llama `api.gmailSync(token)` sin parámetros.
- Sintaxis de query de Gmail: `is:unread` (no leídos), `newer_than:<N>d` (últimos N días), `in:inbox`.

## Scope

**Incluido:**
- `schemas.py`: `SyncRequest{ unread_only: bool = True, days: int = 1 }` con validación
  `1 <= days <= gmail_sync_max_days` (Pydantic `Field(ge=1, le=...)`).
- `services/gmail.py`: `build_inbox_query(unread_only: bool, days: int) -> str` (reemplaza la
  constante `TODAY_QUERY`; deja un alias `TODAY_QUERY = build_inbox_query(True, 1)` para no romper
  tests existentes que lo importan).
- `routers/inbox.py`: `POST /gmail/sync` acepta `SyncRequest` (body opcional, default = comportamiento
  actual) y pasa el query construido a `list_today`. Span `gmail.sync` gana atributos
  `filter.unread_only` y `filter.days` (baja cardinalidad).
- `config.py`: `gmail_sync_max_days: int = 30` (tope de la ventana).
- Frontend: en `Inbox.tsx`, un toggle **Todos / No leídos** y un selector de **días** (1/3/7/30);
  `api.gmailSync(token, { unreadOnly, days })`.
- Tests: query construido correcto para las 4 combinaciones clave, validación de `days` fuera de
  rango (422), y que el default preserva el comportamiento de Plan 37.

**Fuera de scope:**
- Filtros por etiqueta/label o remitente (v2).
- Paginación / "mostrar más" real (el tope sigue siendo `gmail_sync_max_results`).
- Persistir la preferencia de filtros del usuario (v2; por ahora es estado de la vista).

## Flujo de `POST /gmail/sync` (con body)

```
body = SyncRequest(unread_only=false, days=7)   # o {} → default (true, 1)
q = build_inbox_query(unread_only, days)
  → "in:inbox newer_than:7d"                     (todos, 7 días)
  → "in:inbox is:unread newer_than:1d"           (no leídos, 1 día = default actual)
list_today(http, access_token, q, settings.gmail_sync_max_results)
… (resto igual que Plan 37) …
```

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/schemas.py` | `SyncRequest{unread_only, days}` con validación de rango |
| `email_triage/services/gmail.py` | `build_inbox_query(unread_only, days)`; `TODAY_QUERY` pasa a ser alias |
| `email_triage/routers/inbox.py` | `sync(...)` acepta `SyncRequest`; atributos de span |
| `email_triage/config.py` | `gmail_sync_max_days: int = 30` |
| `frontend/src/api.ts` | `gmailSync(token, { unreadOnly, days })` |
| `frontend/src/pages/Inbox.tsx` | toggle Todos/No leídos + selector de días |
| `tests/test_gmail_sync.py` | casos de query construido + validación 422 + default preservado |
| `docs/features/40-*` | doc |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Body opcional con defaults = comportamiento de Plan 37 | Body obligatorio | Cero regresión; clientes viejos siguen funcionando |
| Construir el query en el server | Recibir el `q` crudo de Gmail desde el cliente | Evita inyección de operadores y mantiene el server como única fuente del query |
| `days` validado `1..gmail_sync_max_days` | Días libres | Acota coste/latencia del triage por-correo; tope configurable |
| `unread_only` booleano | Enum de estados | Solo hay dos estados relevantes hoy; enum es sobre-ingeniería |
| Reusar `gmail_sync_max_results` como tope duro | Subir el tope al ampliar días | La ventana amplía *qué* correos entran, no *cuántos* se triagean por sync |

## Risks / Open questions

- **Ventana amplia × tope de resultados:** con `days=30` y `is:unread=false` puede haber cientos de
  correos; el `maxResults` de Gmail sigue acotando a `gmail_sync_max_results`. Documentar que "más
  días" no significa "más correos por sync", y dejar el "mostrar más" para v2.
- **Coste del triage:** traer *todos* (no solo no leídos) multiplica los triages. El tope de
  resultados lo contiene; medir vía Logfire (se cruza con Plan 42).
- **Zona horaria:** `newer_than:Nd` sigue siendo relativo (N×24h), no medianoche local — igual que
  Plan 37. Si se quiere "desde las 00:00 locales" habría que usar `after:<epoch>` (fuera de scope).

## Execution order

1. `SyncRequest` + `build_inbox_query` + `gmail_sync_max_days` (40 min).
2. `routers/inbox.py`: aceptar body, construir query, atributos de span (30 min).
3. Frontend: selectores + `api.gmailSync` con params (60 min).
4. Tests backend (query, 422, default) (40 min).
5. Doc `40-*`; `make check` verde; verificación visual en `/inbox`.

## Done when

- [x] `POST /gmail/sync` sin body sigue trayendo no-leídos de 1 día (comportamiento de Plan 37 intacto)
- [x] `POST /gmail/sync {unread_only:false, days:7}` construye `in:inbox newer_than:7d`
- [x] `days` fuera de `1..gmail_sync_max_days` → 422
- [x] `Inbox.tsx` expone toggle Unread only y selector de días, y los pasa a la API
- [x] El span `gmail.sync` lleva `filter.unread_only` y `filter.days`
- [x] Ningún test toca red real (Gmail + `LLMService` mockeados) — `CLAUDE.md`
- [x] `make check` verde (ruff + pyright 0 + **235 tests**); frontend eslint + tsc + vite build verdes
- [ ] Humano validó con la guía de testing (pase visual autenticado en `/inbox` con Gmail conectado)
