# Team Workspaces + RBAC completo

## What it does

Lleva el RBAC del andamiaje a features reales: **workspaces de equipo**,
**invitaciones por token (link)**, **gestión de miembros y roles**, y **borrado
de workspace**. Antes todo usuario era `owner` de su workspace personal y los
roles `admin`/`member` y los scopes `workspace:delete`/`triage:write` no se
ejercían; ahora un equipo tiene varios miembros con roles distintos y cada
endpoint exige el scope correcto.

## How it works

Tres capas (ver [walkthrough RBAC en el código](../../email_triage/auth/scopes.py)):

```
ROL (Membership.role)  ──ROLE_SCOPES──▶  SCOPES  ──require_scope("...")──▶  ENDPOINT
```

- **Enforcement por-workspace:** las rutas llevan `{tid}` en el path y usan
  `require_scope(scope)` ([deps.py](../../email_triage/deps.py)), que resuelve la
  membership del caller **en ese workspace** (`get_membership_in`). Resolver el
  rol ahí mismo también prueba que el caller pertenece al workspace → **anti-IDOR**.
- **Reglas de negocio en `WorkspaceService`**
  ([services/workspace.py](../../email_triage/services/workspace.py)): último owner
  protegido, jerarquía `owner > admin > member`, validez de invitaciones. Los
  repos solo hacen SQL; el servicio hace las reglas y es testeable sin HTTP.
- **Invitaciones por token:** `secrets.token_urlsafe(32)` → se guarda `sha256`
  (mismo patrón que las API keys); el plaintext viaja una vez en el link
  (`{frontend_url}/accept-invite#token=...`). Aceptar = lookup por hash → validar
  (pending, no expirada, email coincide) → crear membership.

## Files involved

| File | Role |
|---|---|
| `email_triage/db/models.py` | `Invitation` + cascade en `Tenant` |
| `alembic/versions/0003_invitations.py` | tabla `invitations` |
| `email_triage/services/workspace.py` | `WorkspaceService` (reglas) |
| `email_triage/deps.py` | `WorkspaceContext` + `require_scope()` |
| `email_triage/db/repos/invitations.py` | `InvitationRepo` |
| `email_triage/db/repos/{users,tenants}.py` | `get_membership_in`, `list_members`, `count_owners`, `create_team`, `list_for_user`, `delete` |
| `email_triage/routers/workspaces.py` | endpoints `/workspaces*` + `/invitations/accept` |

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| RBAC scoped por `{tid}` | rol global en el JWT | Un usuario tiene roles distintos por workspace; evaluar en el objetivo tapa IDOR |
| `WorkspaceService` separado | lógica en handlers/repos | Reglas no son SQL ni HTTP; aisladas se testean directo |
| Invite por token hasheado | token plano / JWT de invite | Consistente con API keys; revocable; sin plaintext en DB |
| Email del invite debe coincidir | aceptar con cualquier cuenta | Evita que un link filtrado meta a un tercero |

## Gotchas / Edge cases

- **Workspace activo:** el JWT no lo lleva; el `{tid}` va en el path (stateless).
  Elegir el activo es trabajo de la UI (Plan 22).
- **Borrar workspace con `triage_logs` (Postgres):** el FK `triage_logs.tenant_id`
  no tiene `ON DELETE`, así que borrar un team con historial fallaría en PG
  (en SQLite/tests no se aplica). Limitación conocida; `memberships` e
  `invitations` sí cascedean.
- **Expiración de invites:** se deriva de `expires_at < now()` al validar (no hay
  estado `expired` persistido ni cron). El comparador trata datetimes naive
  (SQLite) como UTC.
- **No se invita como `owner`:** solo `admin`/`member`; ownership se promueve
  explícitamente por un owner.

## Testing

📋 [Testing guide](../testing/21-team-workspaces-rbac_testing.md)
