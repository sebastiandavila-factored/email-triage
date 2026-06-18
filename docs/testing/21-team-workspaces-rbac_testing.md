# Testing: Team Workspaces + RBAC

## Prerequisites

- Suite automática: `uv run pytest tests/test_workspaces.py tests/test_workspaces_api.py`
  (no requiere DB real ni red; usa SQLite en memoria/archivo).
- Manual end-to-end: backend con `DATABASE_URL` (Neon/local), dos cuentas de
  usuario, token Bearer de cada una.

## Test Cases (automáticos)

Reglas de negocio (`tests/test_workspaces.py`, contra `WorkspaceService`):

### TC-01: crear team
**Action**: `create_team(owner, "Acme")`.
**Expected**: `tenant.type == "team"` y el creador queda `owner`.

### TC-02: jerarquía de roles
**Action**: un `admin` intenta cambiar el rol de un `owner`.
**Expected**: `WorkspaceError` 403 ("Only an owner can manage owners").

### TC-03: último owner
**Action**: degradar o quitar al único `owner`.
**Expected**: 409 ("Cannot demote/remove the last owner").

### TC-04: ciclo de invitación
**Action**: `create_invitation` → `accept_invitation` con el email correcto.
**Expected**: membership creada con el rol invitado. Email distinto → 403;
expirada → 410; rol `owner` → 422; duplicada / ya-miembro → 409.

Enforcement HTTP (`tests/test_workspaces_api.py`, vía `httpx.ASGITransport`):

### TC-05: sin token
**Action**: `GET /workspaces/{tid}/members` sin `Authorization`.
**Expected**: 401.

### TC-06: IDOR (no miembro)
**Action**: usuario autenticado que **no** pertenece al workspace → `GET members`.
**Expected**: 403 ("Not a member of this workspace"), nunca 200.

### TC-07: scope insuficiente
**Action**: un `member` hace `POST /workspaces/{tid}/invitations`.
**Expected**: 403 ("Scope required: workspace:manage").

### TC-08: owner gestiona
**Action**: owner lista miembros, crea invitación, crea/lista workspaces.
**Expected**: 200; la invitación devuelve un `link` con `#token=`.

## Edge Cases

| Scenario | Expected |
|---|---|
| Aceptar invitación ya aceptada/revocada | 409 |
| Aceptar token inexistente | 404 |
| `change_role` a un rol inválido | 422 |
| Borrar workspace personal | 403 |
| Leave (auto-remove) siendo el último owner | 409 |

## Log verification

```bash
# eventos estructurados del servicio
grep -E 'workspace\.(role_changed|member_removed|invite_accepted)' <logs>
```

## Manual E2E (dos cuentas)

1. Cuenta A: `POST /workspaces {name}` → es `owner`.
2. A: `POST /workspaces/{tid}/invitations {email: B, role: member}` → copia el `link`.
3. Cuenta B (logueada con ese email): `POST /invitations/accept {token}` → 200.
4. B: `GET /workspaces` incluye el team con rol `member`.
5. B intenta `POST .../invitations` → 403. A puede.

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| 403 "Not a member" siendo miembro | `{tid}` equivocado o token de otro usuario | verificar el path y el Bearer |
| 503 en endpoints | DB no configurada (`get_session_factory()` None) | setear `DATABASE_URL` / fixture |
| Aceptar invite da 403 email | el email del invite ≠ email de la sesión | invitar al email correcto |
| Borrar team falla en Postgres | `triage_logs` referencian el tenant | limitación conocida (ver feature doc) |
