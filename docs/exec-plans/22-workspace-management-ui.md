# 22. Workspace Management UI (frontend)

**Status:** 🚧 in progress (UI implementada: switcher, members/roles, invitar/aceptar, crear team; build + lint verdes. Pendiente: smoke test E2E manual con dos cuentas)
**Estimate:** 5 hrs
**Depends on:** Plan 21 (Team workspaces + RBAC backend), Plan 17 (React SPA).

## Intent

Exponer en la SPA lo que el Plan 21 dejó en el backend: cambiar de workspace,
ver/gestionar miembros y roles, crear workspaces de equipo, e invitar gente por
link. La UI **refleja** el RBAC: muestra/oculta acciones según el rol del caller
en el workspace activo (defensa en profundidad — el backend sigue siendo la
autoridad; el frontend solo evita ofrecer botones que darían 403).

## Scope

**Incluido:**
- **Workspace switcher** en el navbar: lista `GET /workspaces`, workspace activo persistido en `localStorage`, propaga el `tid` a las llamadas scoped.
- Página **Workspace / Members**: lista miembros + rol; cambiar rol y quitar (solo si el caller tiene `workspace:manage`); "leave workspace".
- **Invitaciones**: crear (muestra el link una vez, botón copiar), listar pendientes, revocar.
- **Crear workspace de equipo** (modal/página).
- Página **Accept invite** (`/accept-invite`): lee `#token=`, llama `POST /invitations/accept`, redirige al workspace.
- Gating de UI por rol: helper `can(scope)` derivado del rol del workspace activo.
- Settings: rotate-key sigue, pero ahora **scoped** al workspace activo.

**Fuera de scope:**
- Transferencia de ownership por UI.
- Notificaciones/emails de invitación (el link se copia y reparte a mano).
- Realtime / websockets para cambios de miembros.

## Modelo de "workspace activo"

El JWT no lleva el workspace (Plan 21). El **activo** es estado de cliente:

```
localStorage: active_workspace_id
AuthContext: workspaces[], activeWorkspace, setActiveWorkspace(id)
```

- Al montar (tras validar el token) → `GET /workspaces` → si no hay activo guardado, default al **personal**.
- Toda llamada scoped usa el `tid` activo en el path (`/workspaces/{tid}/...`).
- `can(scope)` = `ROLE_SCOPES_FRONT[activeWorkspace.role].includes(scope)` — una copia mínima del mapa de scopes en el front, solo para mostrar/ocultar (no es seguridad).

## Pantallas

| Ruta | Auth | Descripción |
|---|---|---|
| `/dashboard` | sí | triage del workspace activo (sin cambios estructurales) |
| `/workspace` | sí | miembros + roles + invitaciones del workspace activo |
| `/workspace/new` | sí | crear workspace de equipo |
| `/accept-invite` | sí | lee `#token=`, acepta, redirige |
| `/settings` | sí | info + rotate-key (scoped al activo) |

Navbar: **switcher** de workspace + link a `/workspace`.

## API client (`api.ts`) — añadir

```ts
listWorkspaces(token)                                  // GET /workspaces
createWorkspace(token, name)                           // POST /workspaces
getMembers(token, tid)                                 // GET /workspaces/{tid}/members
changeRole(token, tid, uid, role)                      // PATCH .../members/{uid}
removeMember(token, tid, uid)                          // DELETE .../members/{uid}
createInvite(token, tid, email, role)                  // POST .../invitations  → { link }
listInvites(token, tid)                                // GET .../invitations
revokeInvite(token, tid, id)                           // DELETE .../invitations/{id}
acceptInvite(token, inviteToken)                       // POST /invitations/accept
deleteWorkspace(token, tid)                            // DELETE /workspaces/{tid}
```

(Todas con `Authorization: Bearer`; reutilizan el `request()` con `API_BASE`.)

## Gating por rol (defensa en profundidad)

```tsx
const { activeWorkspace } = useAuth()
const can = (scope: string) => FRONT_ROLE_SCOPES[activeWorkspace.role]?.includes(scope) ?? false

{can('workspace:manage') && <InviteButton />}
{can('workspace:delete') && <DeleteWorkspaceButton />}
```

El backend **siempre** revalida (Plan 21). Si el front se desincroniza, la acción
devuelve 403 y se muestra el error — nunca un falso "éxito".

## Concrete changes

| Archivo | Cambio |
|---|---|
| `frontend/src/api.ts` | + wrappers de workspaces/members/invites |
| `frontend/src/AuthContext.tsx` | + `workspaces`, `activeWorkspace`, `setActiveWorkspace`; carga `GET /workspaces` |
| `frontend/src/components/WorkspaceSwitcher.tsx` | **nuevo** selector en navbar |
| `frontend/src/pages/Workspace.tsx` | **nuevo** miembros + roles + invitaciones |
| `frontend/src/pages/NewWorkspace.tsx` | **nuevo** crear team |
| `frontend/src/pages/AcceptInvite.tsx` | **nuevo** acepta `#token=` |
| `frontend/src/pages/Settings.tsx` | rotate-key scoped al workspace activo |
| `frontend/src/App.tsx` | rutas nuevas |
| `frontend/src/rbac.ts` | **nuevo** `FRONT_ROLE_SCOPES` (espejo de scopes, solo UI) |

## Design decisions

| Decisión | Alternativa | Razón |
|---|---|---|
| Workspace activo en `localStorage` + path `{tid}` | activo en el JWT | El JWT se emite al login, antes de elegir; el path-scoped es stateless y ya es como el backend (Plan 21) lo espera |
| Espejo de scopes en el front solo para gating visual | pedir permisos al backend | UX (ocultar botones), pero la **autoridad** es el backend; el front nunca decide seguridad |
| Aceptar invite vía `#token=` | `?token=` en query | El fragmento no llega al servidor → no aparece en logs (igual que el SSO) |
| Reusar `API_BASE`/`request()` | cliente nuevo | Consistencia con lo ya hecho en Plan 20 |

## Risks / Open questions

- **Desincronización de rol:** si cambian tu rol mientras navegas, el front puede
  mostrar un botón de más → 403 al usarlo. Aceptable; refrescar `GET /workspaces`
  tras acciones de gestión lo mitiga.
- **Aceptar invite sin sesión:** `/accept-invite` requiere estar logueado; si no,
  redirige a `/login?next=/accept-invite#token=...` y vuelve. (Conservar el
  fragmento en el round-trip de login.)
- **Borrar el workspace activo:** tras `DELETE`, hacer fallback al personal y
  refrescar la lista.

## Execution order

1. `api.ts` wrappers + `rbac.ts` (30 min).
2. `AuthContext`: `workspaces`/`activeWorkspace` + carga `GET /workspaces` (45 min).
3. `WorkspaceSwitcher` en navbar (30 min).
4. `Workspace.tsx`: miembros + cambiar rol + quitar + leave (75 min).
5. Invitaciones (crear/listar/revocar) en `Workspace.tsx` (45 min).
6. `NewWorkspace.tsx` + `AcceptInvite.tsx` (45 min).
7. Gating `can()` + `Settings` scoped (30 min).
8. Smoke test E2E con dos cuentas (owner invita, member acepta) (30 min).

## Done when

- [ ] El switcher lista mis workspaces y cambia el activo (persistente)
- [ ] Como `owner`/`admin` veo y uso invitar / cambiar rol / quitar; como `member` no aparecen
- [ ] Crear invite muestra el link una vez; otro usuario lo acepta en `/accept-invite` y entra al workspace
- [ ] Crear workspace de equipo funciona y aparece en el switcher
- [ ] Acciones sin permiso (si se fuerzan) muestran el 403 del backend, no un falso éxito
- [ ] `make frontend-build` verde
