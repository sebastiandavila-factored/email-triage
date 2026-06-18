# Walkthrough de estudio — Authentication & Authorization (consolidado)

> Guía capstone para entrevista. Une las tres piezas de auth del repo:
> **API keys** (máquinas), **sesión humana** (password + Google OIDC + JWT) y
> **RBAC** (roles → scopes → enforcement, ahora por-workspace). Profundiza en
> cada subtema en sus docs dedicados:
> [api-keys](WALKTHROUGH-api-keys.md) · [oauth2-google](WALKTHROUGH-oauth2-google.md).
>
> Verificado: `uv run pytest` → **76** · `pyright` 0 · `ruff` limpio · frontend
> build+lint limpios.

---

## 0. El concepto que ordena todo: AuthN ≠ AuthZ

- **Authentication (¿quién eres?)** → identidad. Aquí: API key, password, Google.
- **Authorization (¿qué puedes hacer?)** → permisos. Aquí: RBAC con scopes.

Si solo recuerdas una frase: *"autenticar establece la identidad; autorizar
decide qué puede hacer esa identidad sobre un recurso concreto"*. El error más
común en entrevista es mezclarlas.

---

## 1. Dos principales, dos sistemas de autenticación

El producto tiene **dos tipos de cliente**, cada uno con su mecanismo:

| Principal | Mecanismo | Header | Quién lo valida |
|---|---|---|---|
| **Máquina** (Zapier/Make/script) | API key por tenant | `X-API-Key` | `verify_api_key` ([deps.py](../email_triage/deps.py)) |
| **Humano** (SPA/navegador) | JWT de sesión | `Authorization: Bearer` | `get_current_user` / `require_scope` |

Es deliberado: una integración máquina quiere una credencial **de larga vida y
revocable** (API key); un humano quiere una **sesión corta** (JWT 30 min). No se
fuerza uno en el molde del otro.

### 1a. Máquina — API key (`et_<tenant_id>_<secret>`)
Lookup **O(1)** parseando el tenant del propio key, verificación con `sha256`
en tiempo constante; devuelve `TenantContext(tenant_id)`. El detalle de *por qué
sha256 y no bcrypt* (entropía) y *por qué no escanear todos los tenants* (DoS)
está en [WALKTHROUGH-api-keys.md](WALKTHROUGH-api-keys.md).

### 1b. Humano — password / Google → JWT
- **Password:** `bcrypt` (hash lento para secretos de baja entropía).
- **Google OIDC:** Authorization Code + PKCE; el `id_token` se valida con firma
  RS256 **+ iss + aud + exp**. Detalle en
  [WALKTHROUGH-oauth2-google.md](WALKTHROUGH-oauth2-google.md).
- Ambos terminan emitiendo **tu** JWT de sesión (HS256, claims `sub`/`iat`/`exp`,
  [auth/session.py](../email_triage/auth/session.py)). El cliente lo manda en
  cada request; `get_current_user` lo decodifica.

> Tabla mental de credenciales (no confundir): API key (máquina, larga) · JWT de
> sesión propio (humano, 30 min) · id_token de Google (solo se usa una vez, en el
> login) · access_token de Google (no se usa — no llamamos a APIs de Google).

---

## 2. Authorization — RBAC con scopes

### 2a. El modelo de datos que lo hace posible

```
User (persona) ──< Membership(role) >── Tenant (workspace)
```

El **rol vive en `Membership`**, no en `User` ni en `Tenant`. Eso permite que la
misma persona sea `owner` de su workspace personal y `member` de un equipo. Es
la base de la multi-tenancy real.

### 2b. Roles → scopes ([auth/scopes.py](../email_triage/auth/scopes.py))

```
owner   → triage:write, workspace:manage, workspace:delete
admin   → triage:write, workspace:manage
member  → triage:write
```

Los endpoints exigen **scopes** (permisos finos), no roles. Así puedes recolocar
qué rol tiene qué permiso cambiando solo `ROLE_SCOPES`, sin tocar endpoints.
`frozenset` → lookup O(1) e inmutable.

### 2c. Dos caminos de enforcement (la parte sutil)

Hay **dos** formas de exigir permisos, según el recurso:

**A) A nivel de cuenta** — `get_current_user` + `SecurityScopes`
([deps.py](../email_triage/deps.py)). Usa la membership del usuario (patrón
nativo de FastAPI: `Security(get_current_user, scopes=[...])`). Lo usan
`/auth/me`, `/auth/logout`. Resuelve un `SessionContext`.

**B) Por workspace** — `require_scope(scope)` (añadido en el Plan 21). Las rutas
llevan `{tid}` en el path; la dependencia carga la membership del caller **en ese
workspace concreto** (`get_membership_in(user, tid)`) y evalúa el scope contra
**ese** rol. Devuelve `WorkspaceContext(user_id, tenant_id, role)`.

```python
def require_scope(scope: str):
    async def dep(tid, settings, token) -> WorkspaceContext:
        user_id = decode_access_token(...)                 # AuthN
        membership = await UserRepo().get_membership_in(session, user_id, tid)
        if membership is None:                             # ← no es miembro
            raise HTTPException(403, "Not a member of this workspace")
        if scope and scope not in ROLE_SCOPES[membership.role]:
            raise HTTPException(403, f"Scope required: {scope}")
        return WorkspaceContext(user_id, tid, membership.role)
    return dep
```

**El insight de seguridad (object-level authz / anti-IDOR):** cargar la
membership por `(user_id, tid)` no solo da el rol — *prueba que el caller
pertenece a ese workspace*. Sin esto, un usuario podría operar sobre el `{tid}`
de otro (Insecure Direct Object Reference). Por eso el RBAC de equipos **debe**
ser por-workspace, no un rol global del token. Esto además cerró el hallazgo
**C6** (la antigua `get_membership` arbitraria).

Las reglas relacionales más finas (no degradar al último owner, jerarquía
owner>admin>member, validez de invites) viven en `WorkspaceService`
([services/workspace.py](../email_triage/services/workspace.py)) — separadas del
HTTP para testearlas solas.

---

## 3. Trazas (de punta a punta)

**Triage (máquina):**
```
X-API-Key ─▶ verify_api_key → TenantContext(tenant_id) ─▶ handler ─▶ Groq
                                            └─▶ triage_logs.tenant_id (atribución)
```

**Rotar API key (humano, cuenta):**
```
Bearer JWT ─▶ get_current_user (scopes=["workspace:manage"]) ─▶ rotate-key
```

**Gestionar miembros (humano, workspace):**
```
Bearer JWT + PATCH /workspaces/{tid}/members/{uid}
   └─▶ require_scope("workspace:manage")
         ├─ no miembro de {tid} → 403 (IDOR)
         ├─ member sin el scope → 403
         └─ owner/admin → WorkspaceService.change_role (jerarquía + último owner)
```

---

## 4. Q&A de entrevista (consolidado)

**P: AuthN vs AuthZ, en una frase.**
AuthN = quién eres (identidad); AuthZ = qué te dejo hacer sobre un recurso.

**P: ¿Por qué dos sistemas de autenticación?**
Máquina = credencial larga y revocable (API key con lookup en DB); humano =
sesión corta stateless (JWT). Cada caso de uso pide propiedades distintas.

**P: ¿Roles o scopes en los endpoints?**
Scopes (permisos finos). El endpoint pide `workspace:manage`, no `admin`. Cambiar
el mapa rol→scope no toca endpoints. Es el patrón de OAuth2 scopes de FastAPI.

**P: ¿Dónde poner el rol — User o Membership?**
En `Membership` (la relación user↔workspace), para roles distintos por workspace.

**P: ¿Qué es IDOR y cómo lo evitas aquí?**
Operar sobre un objeto de otro cambiando el id en la URL. Se evita con
*object-level authorization*: cargar la membership por `(user, tid)` → si no
existe, 403. El check de pertenencia y el de rol son el mismo lookup.

**P: ¿Por qué el RBAC de equipos no usa el rol del JWT?**
Porque el rol depende del workspace; el token se emite una vez y el usuario tiene
varios roles. Se evalúa contra el `{tid}` de la request.

**P: ¿Cómo revocas acceso?**
API key: rotar (nuevo hash) + invalidar cache. JWT: es stateless → expira en 30
min; revocación inmediata necesitaría blocklist (Redis), trabajo futuro.

**P: ¿`bcrypt` o `sha256`?**
bcrypt para passwords (baja entropía → hash lento). sha256 para API keys/tokens
de invitación (alta entropía → hash rápido y buscable). Usar el equivocado es un
red flag.

---

## 5. Estado honesto / gaps

- **`triage:write` no se exige en `/triage`** todavía: ese endpoint se autentica
  por API key (máquina), no por JWT+scope. El scope se usará cuando la UI ofrezca
  triage por sesión humana. Hoy es "asignable pero no enforced" en triage.
- **`/triage` y `rotate-key` no están scoped al workspace activo** del switcher:
  usan la key/membership del workspace personal. Follow-up (exponer la key por
  workspace).
- **JWT sin revocación** (blocklist) — aceptable para 30 min; Plan 18+.
- **Swagger "Authorize" (B5):** `/auth/login` espera JSON, no el form de
  `OAuth2PasswordBearer` → el botón da 422. No afecta a la app.

## 6. Mapa de archivos

| Archivo | Rol en auth |
|---|---|
| `auth/api_key.py` | API key máquina (issue/parse/verify) |
| `auth/session.py` | JWT de sesión (create/decode) |
| `auth/pkce.py`, `auth/state.py` | PKCE + state CSRF (Google) |
| `auth/scopes.py` | `ROLE_SCOPES` |
| `deps.py` | `verify_api_key`, `get_current_user`, `require_scope` |
| `services/workspace.py` | reglas RBAC de equipos |
| `routers/auth.py` | signup/login/google/me/rotate-key |
| `routers/workspaces.py` | endpoints scoped por workspace |
