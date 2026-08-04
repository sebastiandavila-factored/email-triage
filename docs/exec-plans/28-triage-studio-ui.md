# 28. Triage Studio F5 — Studio UI (React)

**Status:** ✅ delivered (página `/studio` con categorías/ejemplos/prompt/versiones + gating por rol + banner "publicado gana"; `tsc` + `eslint` + `vite build` verdes).
**Estimate:** ~5 hrs
**Depends on:** Plan 24–26 (Studio backend), Plan 17/22 (React app + workspace UI).
**Propuesta madre:** [docs/proposals/001-triage-studio.md](../proposals/001-triage-studio.md) — Fase F5.

## Intent

Dar a los owners/admins una **UI no técnica** para el Triage Studio: gestionar categorías,
añadir ejemplos few-shot, editar los bloques del prompt, **previsualizar** el XML compilado,
y **publicar / hacer rollback** de versiones. Consume la API de F1–F3 con los patrones ya
establecidos en el frontend (`api.ts` tipado, `useAuth`, `can(role, scope)`, Tailwind).

Frontend-only: **cero cambios de backend**.

## Scope

**Incluido:**
- `api.ts`: tipos + métodos para categorías, ejemplos, draft, preview, versiones, publish, activate.
- `rbac.ts`: añadir `triage:configure` y `prompt:publish` al espejo de scopes.
- `pages/Studio.tsx`: página con secciones — Categorías (CRUD), Ejemplos (por categoría
  seleccionada), Prompt (editor de bloques + botón Preview que muestra el XML), Versiones
  (lista + Publish + Activar/rollback).
- Gating por rol: edición con `triage:configure` (owner/admin); publish/rollback con
  `prompt:publish` (solo owner). Lectura para cualquier miembro.
- Ruta `/studio` protegida en `App.tsx` + enlace "Studio" en la nav (Dashboard/Workspace).

**Fuera de scope:**
- Diff visual entre versiones (se listan; el diff es F5.1 futuro).
- Editor con validación de XML en vivo (el backend valida al preview/publish).
- i18n; tests E2E de UI (el repo no tiene infra de test de front — gate = `tsc` + eslint).

## Concrete changes

| Archivo | Cambio |
|---|---|
| `frontend/src/api.ts` | + tipos `Category`, `TriageExample`, `PromptDraft`, `PromptPreview`, `PromptVersion` + métodos |
| `frontend/src/rbac.ts` | + `triage:configure`, `prompt:publish` en `FRONT_ROLE_SCOPES` |
| `frontend/src/pages/Studio.tsx` | **nueva** página del Studio |
| `frontend/src/App.tsx` | ruta `/studio` protegida |
| `frontend/src/pages/Dashboard.tsx`, `Workspace.tsx` | enlace "Studio" en la nav |
| `docs/features/28-*`, `docs/testing/28-*` | docs |

## UX (secciones de la página)

1. **Categorías** — tabla: slug (readonly), name/description editables, toggle activo, borrar.
   Form para crear (slug/name/description). Errores del API (409/422) inline.
2. **Ejemplos** — selector de categoría → lista de ejemplos + form para añadir
   (kind, subject, body, expected_reply?). Borrar.
3. **Prompt** — textareas para role/task/guardrails/tone (vacío = default). Botón
   **Guardar draft** y **Preview** (muestra el XML compilado + allowed_slugs).
4. **Versiones** — botón **Publish** (owner), lista de versiones con métricas y estado,
   botón **Activar** por versión (rollback). Aviso "publicado gana" cuando hay versión activa.

## Design decisions

| Decisión | Alternativa | Razón |
|---|---|---|
| Una página con secciones | Varias rutas | Flujo de configuración es lineal; menos navegación |
| Reusar `can()` para gating | Comprobar rol a mano | Consistencia con Workspace UI; el backend re-valida igual |
| Preview vía endpoint (no compilar en front) | Recompilar en JS | Una sola fuente de verdad (el compilador del backend) |
| Sin diff de versiones aún | Implementarlo ya | Mantener F5 acotado; el diff es incremental |

## Risks / Open questions

- **"Publicado gana":** la UI debe dejar claro que, con versión publicada, editar no afecta
  `/triage` hasta re-publicar. Se muestra un banner.
- **Slug inmutable:** el form de edición no permite cambiar slug (solo name/description/activo).
- **Sin tests de front:** el gate es `npm run build` (tsc) + `eslint`. Verificación visual
  manual (o screenshot con backend levantado).

## Execution order

1. `rbac.ts` + tipos/métodos en `api.ts` (45 min).
2. `Studio.tsx`: Categorías (60 min).
3. Ejemplos + Prompt/preview (75 min).
4. Versiones + publish/rollback + banner "publicado gana" (60 min).
5. Ruta + enlaces de nav (20 min).
6. `npm run build` + `eslint` verdes; docs `28-*` (40 min).

## Done when

- [x] `/studio` lista/crea/edita/borra categorías con gating por rol
- [x] Añadir/borrar ejemplos por categoría; se ven reflejados en Preview
- [x] Editar draft (role/task/guardrails/tone) + Preview muestra el XML compilado
- [x] Publish (solo owner) crea versión; lista de versiones con Activar (rollback)
- [x] Banner "publicado gana" cuando hay versión activa
- [x] `npm run build` y `eslint` verdes; `docs/features/28-*` y `docs/testing/28-*`

> **Nota:** verificación a nivel de gate (`tsc` + `eslint` + `vite build`). La verificación
> visual/E2E es manual contra el backend levantado (el repo no tiene infra de test de front).
