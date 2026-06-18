# 21. Team Workspaces + RBAC completo (backend)

**Status:** ✅ delivered (backend completo: servicio + endpoints + 21 tests + docs). UI en Plan 22.
**Estimate:** 7 hrs
**Depends on:** Plan 16 (Users + Membership + scopes), Plan 14 (DB).

## Intent

El andamiaje RBAC existe (`scopes.py`, `ROLE_SCOPES`, `SecurityScopes`) pero
solo está cableado a medias: hoy todo usuario es `owner` de su workspace
personal, los roles `admin`/`member` nunca se ejercen, y los scopes
`workspace:delete` y `triage:write` están **definidos pero sin usar**. Este plan
completa el RBAC desde el lado de las features: **workspaces de equipo**,
**invitaciones por token**, **gestión de miembros y roles**, y **borrado de
workspace** — todo detrás de una capa de servicio (`WorkspaceService`) que es
donde viven las reglas de negocio que un repo (solo SQL) no debe tener.

La UI va en el Plan 22; este plan deja el backend cableado, testeado y unificado.

## Prior reading

- **FastAPI Advanced — OAuth2 scopes** — https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/
- **OWASP Access Control Cheat Sheet** — https://cheatsheetseries.owasp.org/cheatsheets/Access_Control_Cheat_Sheet.html
- **OWASP Authorization Cheat Sheet** (IDOR, object-level checks) — https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
- Planes [14](14-database-postgresql.md), [16](16-users-and-password-auth.md), y los walkthroughs [api-keys](../WALKTHROUGH-api-keys.md) (hashing de tokens) y [oauth2](../WALKTHROUGH-oauth2-google.md).

## Scope

**Incluido:**
- `Invitation` model + migración `0003` (la tabla `tenants` ya soporta `type="team"` desde `0002`).
- `WorkspaceService` (`services/workspace.py`): reglas de negocio (último owner, jerarquía de roles, expiración de invites).
- `InvitationRepo` + extensiones a `TenantRepo`/`UserRepo`.
- Enforcement RBAC **por workspace** (no global): nueva dependencia `require_scope(...)` que resuelve la membership del caller **en el workspace de la ruta**.
- Endpoints `/workspaces*` y `/invitations*` (tabla abajo).
- Invitaciones por **token** (link), con `sha256(token)` almacenado (mismo patrón que las API keys — nunca plaintext).
- Cierra el hallazgo **C6** (`get_membership` arbitraria) al resolver siempre por `(user_id, tenant_id)`.
- Tests de servicio (reglas) + endpoints (enforcement de scopes) + invitaciones.

**Fuera de scope:**
- UI (Plan 22).
- Envío de emails (la invitación devuelve el link; el reparto es manual/externo).
- Facturación por plan/asientos.
- Auditoría / logs de cambios de rol (más allá de los logs estructurados existentes).
- Transferir un workspace personal a equipo.

## Data model

Sin cambios en `User`/`Membership`. `Tenant` ya tiene `type` (`personal|team`) y
`domain` nullable. Se añade:

```
Invitation
  id           UUID PK
  tenant_id    UUID FK → tenants.id ON DELETE CASCADE
  email        TEXT NOT NULL          — invitee esperado (debe coincidir al aceptar)
  role         TEXT NOT NULL          — 'admin' | 'member' (no se invita como owner)
  token_hash   TEXT NOT NULL UNIQUE   — sha256 del token del link; nunca el plaintext
  invited_by   UUID FK → users.id
  status       TEXT NOT NULL DEFAULT 'pending'   — 'pending' | 'accepted' | 'revoked'
  expires_at   TIMESTAMPTZ NOT NULL   — now() + 7 días
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
  accepted_at  TIMESTAMPTZ NULL

  INDEX (tenant_id), UNIQUE (token_hash)
```

> El estado `expired` no se persiste: se deriva de `expires_at < now()` al
> validar. Así no hace falta un job de limpieza para correctness.

## Endpoints

Todas las rutas de workspace son **scoped por `{tid}` en el path** → el
enforcement usa el rol del caller **en ese workspace**.

| Método | Ruta | Scope exigido | Notas |
|---|---|---|---|
| `POST` | `/workspaces` | (autenticado) | Crea workspace `team`; el creador queda `owner`. |
| `GET` | `/workspaces` | (autenticado) | Lista los workspaces del caller + su rol en cada uno. |
| `GET` | `/workspaces/{tid}` | miembro | Detalle del workspace. |
| `DELETE` | `/workspaces/{tid}` | `workspace:delete` | Solo `owner`. Prohíbe borrar el workspace **personal**. |
| `GET` | `/workspaces/{tid}/members` | miembro | Lista miembros + roles. |
| `PATCH` | `/workspaces/{tid}/members/{uid}` | `workspace:manage` | Cambia rol. Reglas abajo. |
| `DELETE` | `/workspaces/{tid}/members/{uid}` | `workspace:manage`* | Quita miembro. *`self`-remove permitido a cualquier miembro (leave). |
| `POST` | `/workspaces/{tid}/invitations` | `workspace:manage` | Crea invite; devuelve el **link una vez**. |
| `GET` | `/workspaces/{tid}/invitations` | `workspace:manage` | Lista invites pendientes. |
| `DELETE` | `/workspaces/{tid}/invitations/{id}` | `workspace:manage` | Revoca (status → `revoked`). |
| `POST` | `/invitations/accept` | (autenticado) | Body `{token}`. Crea la membership con el rol invitado. |

## Enforcement RBAC por-workspace (el núcleo)

El `get_current_user` actual usa una membership **arbitraria** (C6) — válido
cuando todos tienen una sola. Con equipos, el scope debe evaluarse **en el
workspace de la operación**. Dependencia nueva:

```python
# deps.py
@dataclass(frozen=True)
class WorkspaceContext:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str

def require_scope(scope: str) -> Callable[..., Awaitable[WorkspaceContext]]:
    async def dep(
        tid: uuid.UUID,                                   # del path
        token: Annotated[str, Depends(_oauth2_scheme)],
        settings: SettingsDep,
    ) -> WorkspaceContext:
        user_id = decode_access_token(settings.session_secret, token)
        if user_id is None: raise HTTPException(401, ...)
        membership = await UserRepo().get_membership_in(session, user_id, tid)  # (user, tenant)
        if membership is None:
            raise HTTPException(403, "Not a member of this workspace")          # también tapa IDOR
        if scope and scope not in ROLE_SCOPES.get(membership.role, frozenset()):
            raise HTTPException(403, f"Scope required: {scope}")
        return WorkspaceContext(user_id, tid, membership.role)
    return dep

# Uso:
ManageMembersDep = Annotated[WorkspaceContext, Depends(require_scope("workspace:manage"))]
WorkspaceMemberDep = Annotated[WorkspaceContext, Depends(require_scope(""))]   # solo ser miembro
DeleteWorkspaceDep = Annotated[WorkspaceContext, Depends(require_scope("workspace:delete"))]
```

Clave de seguridad (OWASP IDOR / object-level authz): **cargar la membership por
`(user_id, tid)`** no solo verifica el rol — verifica que el caller pertenece a
ese workspace. Sin eso, un usuario podría operar sobre el `{tid}` de otro.
`UserRepo.get_membership` (sin filtro de tenant) se mantiene solo para
`/auth/me`; las rutas de workspace usan `get_membership_in`.

## WorkspaceService — reglas de negocio

`services/workspace.py`. Los repos hacen SQL; el servicio hace **reglas** (y es
testeable sin HTTP):

```python
class WorkspaceService:
    async def create_team(session, owner_id, name) -> Tenant
    async def list_for_user(session, user_id) -> list[(Tenant, role)]
    async def change_role(session, actor: WorkspaceContext, target_uid, new_role)
    async def remove_member(session, actor, target_uid)
    async def create_invitation(session, actor, email, role) -> (Invitation, plaintext_token)
    async def accept_invitation(session, user, token) -> Membership
    async def delete_workspace(session, actor, tid)
```

Reglas que encapsula (cada una con su test):
- **Último owner protegido:** no se puede degradar/quitar al único `owner` (ni borrarse a sí mismo si es el último). Devuelve 409.
- **Jerarquía:** un `admin` no puede tocar (cambiar rol / quitar) a un `owner`, ni ascender a nadie a `owner`. Solo un `owner` gestiona owners.
- **No auto-invitación / no duplicados:** no invitar a un email que ya es miembro; no dos invites pendientes al mismo email.
- **Invitación:** rol ∈ {`admin`,`member`} (nunca `owner` por link); `expires_at = now()+7d`.
- **Aceptar:** token válido (sha256 match), `status=pending`, no expirado, y **el email del invite coincide con el del usuario** logueado (anti-redirección de invite). Marca `accepted`, crea `Membership`.
- **No borrar personal:** `delete_workspace` rechaza `type="personal"`.

## Invitaciones por token

Mismo patrón que las API keys (ver [walkthrough api-keys](../WALKTHROUGH-api-keys.md)):

```python
token = secrets.token_urlsafe(32)          # alta entropía → sha256 basta
token_hash = hashlib.sha256(token.encode()).hexdigest()   # se guarda esto
link = f"{settings.frontend_url}/accept-invite#token={token}"   # plaintext solo en la respuesta
```

Aceptar = `lookup por sha256(token)` (O(1), índice único) → validar → crear
membership. El plaintext se muestra **una vez** al crear el invite; en DB solo el
hash. El fragmento (`#`) mantiene el token fuera de los logs (mismo razonamiento
que el SSO).

## Concrete changes

| Archivo | Cambio |
|---|---|
| `email_triage/db/models.py` | + `Invitation` |
| `alembic/versions/0003_invitations.py` | crea `invitations` |
| `email_triage/db/repos/invitations.py` | `InvitationRepo`: create, get_by_token_hash, list_pending, set_status |
| `email_triage/db/repos/users.py` | + `get_membership_in(session, user_id, tenant_id)` |
| `email_triage/db/repos/tenants.py` | + `create_team`, `list_for_user`, `delete` |
| `email_triage/services/workspace.py` | **nuevo** `WorkspaceService` (reglas) |
| `email_triage/deps.py` | + `WorkspaceContext`, `require_scope(...)` factory |
| `email_triage/routers/workspaces.py` | **nuevo** router `/workspaces*` + `/invitations/accept` |
| `email_triage/main.py` | registra el router |
| `tests/test_workspaces.py` | servicio (reglas) + endpoints (scopes) + invitaciones |
| `docs/features/21-*.md`, `docs/testing/21-*.md` | docs |

## Nota sobre `triage:write`

`triage:write` queda definido y ahora **asignable por rol en un equipo**. El
endpoint `/triage` sigue gateado por **API key del workspace** (integración
máquina), que es el producto. La UI del Plan 22 usará la sesión + `triage:write`
para decidir si un miembro ve/usa el formulario de triage del workspace; ahí se
ejercita el scope. No se duplica la auth de `/triage`.

## Design decisions

| Decisión | Alternativa | Razón |
|---|---|---|
| RBAC scoped por `{tid}` en el path | rol global del JWT | Un usuario tiene roles distintos por workspace; el scope debe evaluarse en el workspace objetivo (y tapa IDOR) |
| `WorkspaceService` aparte de los repos | lógica en los handlers/repos | Las reglas (último owner, jerarquía) no son SQL ni HTTP; aislarlas las hace testeables |
| Invite por token hasheado (sha256) | guardar token plano / JWT de invite | Consistente con API keys; revocable (borrar fila); no plaintext en DB |
| `expired` derivado de `expires_at` | estado persistido + cron | Correctness sin job de limpieza |
| Email del invite debe coincidir al aceptar | aceptar con cualquier cuenta | Evita que un link filtrado meta a un tercero en el workspace |
| No invitar como `owner` | permitir cualquier rol | `owner` se transfiere explícitamente, no por link |

## Risks / Open questions

- **Workspace activo en sesión:** con varios workspaces, el cliente debe indicar
  cuál opera. Backend: el `{tid}` va en el path (sin estado). El "workspace
  activo" es decisión de **UI** (Plan 22) — el JWT no lo lleva.
- **Transferencia de ownership:** no incluida; "promover a owner" sí (un owner
  puede hacer owner a otro). Quitar el propio rol owner exige que quede ≥1 owner.
- **Carrera al aceptar invite / quitar último owner:** envolver en transacción y
  re-chequear dentro; mapear `IntegrityError` a 409.

## Execution order

1. Modelo `Invitation` + migración `0003` (20 min).
2. Repos: `InvitationRepo`, `get_membership_in`, `create_team`/`list_for_user`/`delete` (45 min).
3. `WorkspaceService` + tests de reglas (90 min).
4. `require_scope` + `WorkspaceContext` en deps (30 min).
5. Router `/workspaces*` + `/invitations/accept` (75 min).
6. Tests de endpoints (scopes, IDOR, invites) (75 min).
7. `main.py` + docs (30 min).
8. `make check` verde.

## Done when

- [ ] `POST /workspaces` crea team y deja al creador como `owner`
- [ ] `PATCH .../members/{uid}` → 403 para `member`, 200 para `owner`/`admin`; respeta jerarquía y último-owner
- [ ] Invite: crear (link una vez) → aceptar (email coincide, no expirado) → membership creada; revocar/expirar funcionan
- [ ] `DELETE /workspaces/{tid}` → 403 sin `workspace:delete`; rechaza workspace personal
- [ ] Operar sobre un `{tid}` del que no eres miembro → 403 (IDOR cubierto)
- [ ] `triage:write`, `workspace:manage`, `workspace:delete` todos ejercidos por algún endpoint/flujo
- [ ] `make check` verde; `docs/features/21-*` y `docs/testing/21-*`
