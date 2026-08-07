# 37. Gmail Ingestion F2 — Endpoint de sync + bandeja del día triada

**Status:** 📋 proposed
**Estimate:** ~5 hrs
**Depends on:** Plan 36 (conexión Gmail + `refresh_token` cifrado), Plan 25 (`/triage` dinámico + `LLMService` por tenant), Plan 21 (RBAC).
**Relacionado:** Plan 38 (UI `/inbox`). Propuesta madre: [002-gmail-ingestion](../proposals/002-gmail-ingestion.md).

## Intent

Con Gmail ya conectado (Plan 36), traer los **correos nuevos de hoy** y clasificarlos con el
motor de triage existente **sin tocarlo**. Cada mensaje de Gmail se mapea a un `TriageRequest`
y pasa por el mismo `LLMService` por-tenant que ya sirve `/triage`. El endpoint devuelve la
bandeja lista para pintar (Plan 38).

Los correos son **efímeros**: se triagean en vuelo y se devuelven; **no se persiste el cuerpo**.
Solo se escribe el `TriageLog` existente (que ya guarda *chars*, no contenido — decisión de
privacidad del modelo actual).

## Prior reading

- Gmail API: `users.messages.list` (query `q`, `maxResults`) → ids; `users.messages.get`
  (`format=full`) → headers + `payload` (body en base64url, preferir `text/plain`).
- Query de "hoy, no leídos, en bandeja": `in:inbox is:unread newer_than:1d`.
- Refresh de access token: `POST https://oauth2.googleapis.com/token` con
  `grant_type=refresh_token` + `refresh_token` (descifrado) → `access_token` (~1h de vida).
- [routers/triage.py](../../email_triage/routers/triage.py) — cómo se corre `LLMService.triage`.
- [services/llm.py](../../email_triage/services/llm.py), [deps.py](../../email_triage/deps.py) — `get_triage_service` por tenant.

## Scope

**Incluido:**
- `services/gmail.py` (**nuevo**): `GmailClient` —
  `refresh_access_token(refresh_token)`, `list_today(access_token, query, max_results)` →
  `list[GmailMessage]` (parse de `subject`/`from`/`date`/`body`), mapeo a `TriageRequest`.
- `routers/inbox.py` (**nuevo**):
  - `GET /gmail/status` → `{connected, google_email, last_synced_at}`.
  - `POST /gmail/sync` (scope `triage:write`) → trae correos del día, triaga cada uno con el
    `LLMService` del tenant, actualiza `last_synced_at`, devuelve la lista de resultados.
- Schemas: `InboxItem` (`message_id`, `sender`, `subject`, `received_at`, `category`,
  `confidence`, `draft_reply`, `trace_id`) y `SyncResponse` en `schemas.py`.
- Manejo de errores: `refresh_token` revocado/expirado → **409 "reconecta"**; Gmail 429 →
  backoff con reintento; sin conexión → 404.
- Observabilidad: span `gmail.sync` con `tenant_id`, `messages.count`; reusa el patrón de
  baggage de Plan 33.
- Tests sin red (Gmail API mockeada + `LLMService` override): sync feliz, bandeja vacía, token
  revocado (409), límite de resultados, aislamiento por tenant.

**Fuera de scope:**
- UI (→ Plan 38).
- Persistir cuerpos / historial de bandeja (v2).
- Streaming del triage por-correo (v1 devuelve la bandeja completa; el progresivo por-fila se
  evalúa en Plan 38 sobre el `/stream` existente).
- Sync automático / push (v2).

## Flujo de `POST /gmail/sync`

```
1. GmailConnectDep-lite: tenant + user desde la sesión (scope triage:write)
2. GmailRepo.get_by_user → conexión; si no hay → 404
3. crypto.decrypt(refresh_token_enc) → refresh_token
4. GmailClient.refresh_access_token → access_token   (si Google 400 invalid_grant → 409 reconecta)
5. GmailClient.list_today(q="in:inbox is:unread newer_than:1d", max_results=settings)
      messages.list → ids   → messages.get(full) por id → parse → TriageRequest
6. por cada correo: LLMService.triage(req)  (reusa get_triage_service del tenant)
7. update last_synced_at
8. return SyncResponse(items=[InboxItem...])
```

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/services/gmail.py` | **nuevo** — `GmailClient` (refresh token, list/get, parse a `TriageRequest`) |
| `email_triage/schemas.py` | `InboxItem`, `SyncResponse`, `GmailStatusResponse` |
| `email_triage/routers/inbox.py` | **nuevo** — `GET /gmail/status`, `POST /gmail/sync` |
| `email_triage/db/repos/gmail.py` | añadir `touch_last_synced(tenant_id, user_id)` |
| `email_triage/deps.py` | helper para obtener `GmailClient` (httpx compartido del lifespan) |
| `email_triage/main.py` | `include_router(inbox.router)` |
| `email_triage/observability.py` | (opcional) métrica `GMAIL_SYNC_MESSAGES` |
| `tests/test_gmail_sync.py` | **nuevo** — sync feliz, vacío, 409 revocado, límite, aislamiento |
| `docs/features/37-*`, `docs/testing/37-*` | docs |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Mapear correo → `TriageRequest` y reusar `LLMService` | Motor de triage nuevo para Gmail | El motor por-tenant ya está en prod; cero regresión, un solo camino |
| Correos efímeros (no persistir cuerpo) | Guardar los emails en DB | Privacidad: el modelo actual ya evita guardar contenido; menos superficie legal |
| `invalid_grant` de Google → 409 "reconecta" | 500 genérico | Es un estado accionable por el usuario (reconectar), no un error del server |
| `max_results` acotado (25, configurable) | Traer toda la bandeja | Coste/latencia del triage por-correo; UX con "mostrar más" en Plan 38 |
| `q="in:inbox is:unread newer_than:1d"` | Filtrar en cliente | Filtrar en Gmail baja payload y trabajo; "del día" = `newer_than:1d` |
| Refresh del access token en cada sync | Cachear access token | Simplicidad v1; el access token vive ~1h y el sync es puntual |

## Risks / Open questions

- **Parseo de MIME:** los correos pueden ser `multipart/alternative` (html + text), adjuntos,
  cuerpos vacíos. Preferir `text/plain`; si solo hay html, degradar (strip básico) o marcar
  "sin texto plano". Acotar `body` a `max_length` del `TriageRequest` (20k).
- **Coste/latencia de N triages por sync:** con `max_results=25` acotado; medir vía Logfire.
  Si molesta, paralelizar con límite de concurrencia (como `online_eval_max_concurrency`).
- **Rate limits de Gmail:** 429/`userRateLimitExceeded` → backoff exponencial; documentar tope.
- **Zona horaria de "hoy":** `newer_than:1d` es relativo (24h), no medianoche local. Suficiente
  para v1; si se quiere "desde las 00:00 locales", usar `after:` con epoch del día del usuario.
- **`sender` no válido como `EmailStr`:** algunos `From` traen display name; extraer el email o
  relajar el schema del item (no es el `TriageRequest.sender` estricto).

## Execution order

1. `services/gmail.py`: refresh token + list/get + parse a `TriageRequest` (120 min).
2. Schemas `InboxItem`/`SyncResponse`/`GmailStatusResponse` (20 min).
3. `routers/inbox.py`: `status` + `sync` con manejo de 404/409/429 (90 min).
4. `GmailRepo.touch_last_synced` + span `gmail.sync` (30 min).
5. Tests (mock Gmail + `LLMService` override): feliz, vacío, 409, límite, aislamiento (90 min).
6. Docs `37-*`; `make check` verde.

## Done when

- [ ] `POST /gmail/sync` devuelve los correos de hoy con `category`/`confidence`/`draft_reply` por correo
- [ ] `GET /gmail/status` refleja `connected`, `google_email`, `last_synced_at`
- [ ] `refresh_token` revocado → 409 accionable ("reconecta"), no 500
- [ ] Ningún test toca red real (Gmail y `LLMService` mockeados) — `CLAUDE.md`
- [ ] Test asegura aislamiento: la sync usa el `LLMService`/conexión del tenant de la sesión, no de otro
- [ ] Bandeja vacía → respuesta con `items: []` (no error)
- [ ] `make check` verde; `docs/features/37-*` y `docs/testing/37-*`
- [ ] Humano validó con la guía de testing
