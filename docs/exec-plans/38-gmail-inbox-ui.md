# 38. Gmail Ingestion F3 — UI de la bandeja del día + card de conexión

**Status:** 📋 proposed
**Estimate:** ~4 hrs
**Depends on:** Plan 36 (connect/disconnect), Plan 37 (`/gmail/status`, `/gmail/sync`), Plan 34 (design system unificado: `AppShell`, `kit`, tokens, tema claro/oscuro).
**Relacionado:** Propuesta madre: [002-gmail-ingestion](../proposals/002-gmail-ingestion.md). Frontend-only, consume 36+37.

## Intent

Dar la superficie visual: una pantalla **Bandeja del día** (`/inbox`) donde el usuario conecta
Gmail, pulsa "Traer correos de hoy" y ve sus correos ya triados (categoría + confianza +
borrador), reutilizando el mismo lenguaje visual del resultado del [Dashboard](../../frontend/src/pages/Dashboard.tsx)
y del design system unificado (Plan 34). Mockup de referencia acordado con el usuario (bandeja
con cabecera de conexión, filas expandibles con borrador, y estado "Clasificando…").

## Prior reading

- [Dashboard.tsx](../../frontend/src/pages/Dashboard.tsx) — patrón de resultado (Tag categoría +
  confianza + "Copy reply" + "Ver traces" con `TraceChat`), a reusar en la fila expandida.
- [components/ui/AppShell.tsx](../../frontend/src/components/ui/AppShell.tsx),
  [components/ui/kit.tsx](../../frontend/src/components/ui/kit.tsx) — shell + primitivas (`Button`,
  `Card`, `SectionHead`, `Tag`, `Field`).
- [App.tsx](../../frontend/src/App.tsx) — routing + `ProtectedRoute`.
- [api.ts](../../frontend/src/api.ts), `AuthContext`, `rbac.ts` (`can`).

## Scope

**Incluido:**
- Ruta `/inbox` protegida en `App.tsx`; entrada "Bandeja" en `AppShell`.
- `pages/Inbox.tsx` (**nuevo**):
  - **Cabecera de conexión:** conectado como `x@gmail.com` + última sync + `↻ Traer correos de
    hoy` + overflow `Desconectar`. Si no conectado → card con `Conectar Gmail` + micro-nota de
    privacidad ("Solo lectura. No enviamos ni borramos nada.").
  - **Lista de correos:** fila con remitente/asunto/hora + `Tag` categoría + confianza%;
    expandible → cuerpo/borrador + `Copiar` + (owner/admin) `Ver traces` (reusa `TraceChat`).
  - **Estados:** skeleton de carga por fila, empty state celebratorio ("Sin correos nuevos hoy"),
    banner de reconexión si `/gmail/status` o `/gmail/sync` devuelven desconectado/409.
- `api.ts`: `gmailStatus(token)`, `gmailSync(token)`, `gmailConnectUrl()`, `gmailDisconnect(token)`.
- Gating por rol: `Conectar/Desconectar` solo si `can(role, 'gmail:connect')`; sincronizar con
  `triage:write` (todos los roles).
- Verificación visual con el preview en **claro y oscuro** (browser tools).

**Fuera de scope:**
- Cambios de backend (los cubren 36/37).
- Responder/enviar desde la UI (v2).
- Auto-refresh en background / polling (v1 es on-demand con el botón).
- Paginación real server-side (v1: el backend ya limita; "mostrar más" es follow-up si hace falta).

## Concrete changes

| Archivo | Cambio |
|---|---|
| `frontend/src/pages/Inbox.tsx` | **nuevo** — pantalla bandeja (conexión + lista + estados) |
| `frontend/src/App.tsx` | ruta `/inbox` protegida |
| `frontend/src/components/ui/AppShell.tsx` | entrada de nav "Bandeja" |
| `frontend/src/api.ts` | `gmailStatus`, `gmailSync`, `gmailConnectUrl`, `gmailDisconnect` + tipos `InboxItem`, `GmailStatus` |
| `frontend/src/pages/Settings.tsx` | card "Gmail" (estado + conectar/desconectar) |
| `frontend/src/rbac.ts` | añadir `gmail:connect` al espejo de scopes |
| `docs/features/38-*`, `docs/testing/38-*` | docs |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Pantalla `/inbox` dedicada | Meter la bandeja dentro del Dashboard | La bandeja es un modo de trabajo distinto (lista) del triage manual (formulario) |
| Reusar el render de resultado del Dashboard | Componente de fila nuevo desde cero | Continuidad visual; el usuario ya conoce Tag+confianza+Copy+Ver traces |
| Conectar = redirect del browser a `/gmail/connect` | fetch/XHR del flujo OAuth | OAuth necesita navegación top-level (consent de Google) — no cabe en fetch |
| Botón "Traer correos de hoy" on-demand | Auto-sync al entrar | Control del usuario + evita coste de triage no pedido; auto-sync es v2 |
| Empty state celebratorio | "No hay datos" seco | Bandeja a cero es un buen resultado, no un error |
| Card de conexión también en Settings | Solo en `/inbox` | Settings es el lugar canónico de integraciones; descubribilidad |

## Gotchas / Edge cases

- **Retorno del OAuth:** tras `/gmail/callback`, redirigir de vuelta a `/inbox` (query flag tipo
  `?gmail=connected`) para refrescar `/gmail/status` y mostrar el toast de éxito. Si el usuario
  denegó → `?gmail=denied` con mensaje suave, sin romper la vista.
- **409 en sync (token revocado):** convertir en banner "Se perdió la conexión — reconecta", no
  en error crudo.
- **`sender` con display name:** mostrar el nombre si viene; el email como secundario.
- **Muchos correos:** el backend limita (Plan 37); la UI muestra el conteo y, si se supera el
  tope, un hint "mostrando los primeros N".
- **Tema:** todo con tokens (`bg-paper`/`text-ink`/`bg-brand`/`border-line`) → claro/oscuro sin
  hardcodear color (Plan 34).

## Execution order

1. `api.ts`: métodos + tipos `InboxItem`/`GmailStatus` (30 min).
2. `Inbox.tsx`: cabecera de conexión (conectado/desconectado) + `Conectar` redirect (45 min).
3. Lista + fila expandible (reusa render del Dashboard + `TraceChat`) (75 min).
4. Estados: skeleton, empty, banner de reconexión + manejo de `?gmail=connected|denied` (45 min).
5. Ruta en `App.tsx` + nav en `AppShell` + card en `Settings` + `rbac.ts` (30 min).
6. `tsc` + `eslint` + `vite build` verdes; verificación visual claro/oscuro con el preview (45 min).
7. Docs `38-*`.

## Done when

- [ ] `/inbox` protegida; entrada visible en `AppShell`
- [ ] Desconectado → card `Conectar Gmail` (owner/admin) con nota de privacidad; miembro no ve conectar
- [ ] Conectado → cabecera con `google_email` + última sync + `Traer correos de hoy`
- [ ] La bandeja lista correos con categoría + confianza; fila expandible muestra borrador + `Copiar` (+ `Ver traces` para owner/admin)
- [ ] Estados cubiertos: skeleton de carga, empty celebratorio, banner de reconexión (409)
- [ ] Verificado en claro y oscuro con el preview (screenshot en el testing doc)
- [ ] `tsc --noEmit` + `eslint` + `vite build` verdes; `docs/features/38-*` y `docs/testing/38-*`
- [ ] Humano validó con la guía de testing
