# 36. Gmail Ingestion F1 — Conexión OAuth + almacenamiento cifrado del refresh token

**Status:** 🚧 implemented (pending human review/merge)
**Estimate:** ~4 hrs
**Depends on:** Plan 15 (OAuth2 + PKCE + `state` en cookie firmada), Plan 16 (User/Tenant/Membership), Plan 21 (RBAC + `require_scope`).
**Relacionado:** Plan 37 (sync + bandeja), Plan 38 (UI `/inbox`). Propuesta madre: [002-gmail-ingestion](../proposals/002-gmail-ingestion.md).

## Intent

Permitir que un **owner/admin conecte su cuenta de Gmail** al workspace activo para, más
adelante (Plan 37), traer los correos del día y triarlos. Esta fase entrega **solo la
conexión**: el flujo OAuth de consentimiento y el **almacenamiento seguro del `refresh_token`**.

La palanca: el flujo OAuth2 con Google **ya existe** para el login
([routers/auth.py](../../email_triage/routers/auth.py)), pero usa `access_type=online` con scopes
`openid email profile` y **descarta el `access_token`**. Este plan añade un flujo **separado**
(`/gmail/connect` + `/gmail/callback`) con `access_type=offline` y el scope `gmail.readonly`,
que sí devuelve un `refresh_token` reutilizable. Reutiliza PKCE y el `state` en cookie firmada
ya endurecidos; el `state` distingue `purpose=connect` de un login normal.

## Prior reading

- [WALKTHROUGH-oauth2-google.md](../WALKTHROUGH-oauth2-google.md) — flujo actual, PKCE, `state`.
- Gmail API scopes: `https://www.googleapis.com/auth/gmail.readonly` es **RESTRICTED**
  (requiere verificación Google + CASA para prod >100 users; modo *testing* permite 100 test users).
- `access_type=offline` + `prompt=consent` → Google devuelve `refresh_token` en el token exchange.
- `cryptography.fernet.Fernet` para cifrado simétrico autenticado del token en reposo.

## Seguridad — el punto crítico

El `refresh_token` es un **credencial de larga vida** que da acceso de lectura al correo del
usuario. Por eso:

1. Se guarda **cifrado en reposo** (Fernet, clave en env `GMAIL_TOKEN_ENC_KEY`), nunca en claro.
2. **Nunca** llega al cliente (mismo principio que `logfire_read_token`, Plan 31).
3. El scope es **mínimo y de solo lectura** (`gmail.readonly`): la app no puede enviar ni borrar.
4. Sin `GMAIL_TOKEN_ENC_KEY` configurada → los endpoints responden **503 "Gmail no configurado"**
   (degradación explícita, nunca inventar el secreto — `CLAUDE.md`).
5. Conectar es un flujo con **PKCE + `state`** (anti-CSRF) reusando la infra existente.

## Scope

**Incluido:**
- Modelo `GmailConnection` + migración `0006_gmail_connections`.
- Util de cifrado `services/crypto.py` (Fernet) — `encrypt(str) -> str`, `decrypt(str) -> str`.
- `routers/gmail.py` (**nuevo**): `GET /gmail/connect` (redirige a Google con scope Gmail,
  `access_type=offline`, `prompt=consent`, `state.purpose=connect`) + `GET /gmail/callback`
  (canjea code, valida `state`, guarda `refresh_token` cifrado + `google_email`).
- Scope `gmail:connect` (owner + admin) en `auth/scopes.py`; `GmailConnectDep` en `deps.py`.
- Config: `gmail_redirect_uri`, `gmail_token_enc_key`, `gmail_sync_max_results` (default 25) en
  `config.py` + `.env.example`.
- `DELETE /gmail/connection` (desconectar: borra la fila; opcional revocar en Google).
- Tests sin red (token exchange de Google mockeado, cifrado round-trip, 503 sin config, RBAC).

**Fuera de scope:**
- Traer/triar correos (→ Plan 37).
- UI (→ Plan 38).
- Casilla compartida por-workspace, multi-cuenta, otros proveedores (v2).
- Sincronización automática / Gmail `watch` + Pub/Sub (v2).

## Modelo de datos

Tabla `gmail_connections` — conexión **por-usuario dentro de un tenant** (v1):

| Columna | Tipo | Nota |
|---|---|---|
| `id` | Uuid PK | |
| `tenant_id` | Uuid FK `tenants` ON DELETE CASCADE | index |
| `user_id` | Uuid FK `users` ON DELETE CASCADE | quién conectó |
| `google_email` | String(255) | casilla conectada (puede ≠ email de login) |
| `refresh_token_enc` | Text | **cifrado Fernet**, nunca en claro |
| `scopes` | Text | scopes concedidos (auditoría) |
| `connected_at` | DateTime tz | |
| `last_synced_at` | DateTime tz \| null | lo actualiza Plan 37 |

`UniqueConstraint(tenant_id, user_id)` → una conexión por usuario/workspace en v1 (reconectar
hace upsert del token).

## Concrete changes

| Archivo | Cambio |
|---|---|
| `pyproject.toml` / `uv.lock` | asegurar `cryptography` como dep directa (Fernet); pin |
| `email_triage/db/models.py` | modelo `GmailConnection` (+ relación en `Tenant`/`User` si aplica) |
| `alembic/versions/0006_gmail_connections.py` | **nuevo** — crea la tabla + índices |
| `email_triage/services/crypto.py` | **nuevo** — `TokenCipher` (Fernet) `encrypt`/`decrypt` |
| `email_triage/db/repos/gmail.py` | **nuevo** — `GmailRepo` (upsert, get_by_user, delete) |
| `email_triage/auth/scopes.py` | `GMAIL_CONNECT = "gmail:connect"`; añadir a `owner` y `admin` |
| `email_triage/deps.py` | `GmailConnectDep = Annotated[WorkspaceContext, Depends(require_scope("gmail:connect"))]` |
| `email_triage/config.py` | `gmail_redirect_uri`, `gmail_token_enc_key: str \| None`, `gmail_sync_max_results: int = 25` |
| `.env.example` | `GMAIL_REDIRECT_URI=`, `GMAIL_TOKEN_ENC_KEY=`, `GMAIL_SYNC_MAX_RESULTS=25` |
| `email_triage/routers/gmail.py` | **nuevo** — `GET /gmail/connect`, `GET /gmail/callback`, `DELETE /gmail/connection` |
| `email_triage/auth/state.py` | extender el payload de la cookie PKCE con `purpose` (`login`\|`connect`) |
| `email_triage/main.py` | `include_router(gmail.router)` |
| `tests/test_gmail_connect.py` | **nuevo** — callback mockeado, cifrado, 503, RBAC, `state` mismatch |
| `docs/features/36-*`, `docs/testing/36-*` | docs |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Flujo `/gmail/connect` separado del login | Añadir el scope Gmail al login | Consentimiento **incremental**: login liviano, Gmail opt-in → menos abandono, mejor privacidad |
| `scope=gmail.readonly` (solo lectura) | `gmail.modify` / enviar | v1 no envía ni borra; menor riesgo y menor barrera de verificación |
| `refresh_token` cifrado (Fernet) en DB | Guardar en claro / solo en memoria | Credencial de larga vida; en claro = fuga total si se filtra la DB |
| Conexión por-usuario (`uq tenant_id,user_id`) | Casilla compartida por-workspace | Alineado con el modelo actual; compartida añade permisos/riesgo → v2 |
| `state.purpose` en la cookie firmada existente | Segunda cookie / store server-side | Reusa la infra stateless multi-worker ya endurecida (Plan 15) |
| 503 si falta `GMAIL_TOKEN_ENC_KEY` | Arrancar igual | Degradación explícita; nunca cifrar con clave por defecto |

## Risks / Open questions

- **Verificación de Google (restricted scope):** para prod pública se necesita CASA. v1 opera en
  modo *testing* con test users. Documentar en el feature doc; no bloquea el código.
- **`refresh_token` ausente en el callback:** Google **solo** devuelve `refresh_token` con
  `access_type=offline` **y** cuando el usuario concede por primera vez (o con `prompt=consent`).
  Forzar `prompt=consent` para garantizarlo en reconexiones.
- **Redirect URI:** hay que registrar `GMAIL_REDIRECT_URI` en Google Cloud Console (distinto del
  de login). Sin registrar → `redirect_uri_mismatch`. Documentar en el testing doc.
- **Rotación de `GMAIL_TOKEN_ENC_KEY`:** rotar la clave invalida los tokens guardados (habría que
  reconectar). Rotación con doble clave → v2.
- **`cryptography` como dep:** verificar si ya es transitiva; pinearla explícita.

## Execution order

1. Dep `cryptography` + `services/crypto.py` (`TokenCipher`) + test round-trip (30 min).
2. Modelo `GmailConnection` + migración `0006` + `GmailRepo` (45 min).
3. Config + `.env.example` + 503 sin clave (20 min).
4. Scope `gmail:connect` + `GmailConnectDep` (15 min).
5. `state.purpose` en `auth/state.py` (15 min).
6. `routers/gmail.py` (`connect`/`callback`/`delete`) + registro en `main.py` (75 min).
7. Tests (callback mock, cifrado, 503, RBAC, state mismatch) + docs `36-*` (60 min).
8. `make check` verde.

> **Ajuste durante ejecución:** `connect` quedó como **`POST /gmail/connect`** (no `GET` redirect)
> que devuelve `{authorization_url}`. La identidad `(user_id, tenant_id)` + el `code_verifier` viajan
> **cifrados dentro del `state`** de OAuth (Fernet, ttl 600s), **sin cookie** — el callback descifra
> el `state` para recuperar la identidad. Se descartó la cookie firmada porque en prod la SPA y la API
> son orígenes distintos y una cookie cross-site la bloquean Safari/Chrome; el `state` cifrado
> round-trip por Google no depende de cookies. CORS ahora permite `DELETE` (para `disconnect`).

## Done when

- [x] `POST /gmail/connect` devuelve la URL de Google con `scope=gmail.readonly`, `access_type=offline`, `prompt=consent`; identidad en cookie firmada
- [x] `GET /gmail/callback` guarda una fila en `gmail_connections` con `refresh_token_enc` **cifrado** (nunca en claro)
- [x] Test verifica que el token persistido NO es legible sin la clave (round-trip cifrado)
- [x] RBAC: `gmail:connect` → owner/admin 2xx, member 403
- [x] Sin `GMAIL_TOKEN_ENC_KEY` → 503 "Gmail no configurado"
- [x] `DELETE /gmail/connection` borra la conexión del usuario
- [x] `make check` verde (ruff + pyright 0 + **212 tests**); `docs/features/36-*` y `docs/testing/36-*`
- [ ] Humano validó con la guía de testing
