# 34. Unify the app UI/UX with the Triage Studio design system (light + dark)

**Status:** 🚧 implemented (pending human review/merge)
**Estimate:** ~8 hrs
**Depends on:** Plan 30 (landing as SPA root — provides the design tokens), Plan 32 (TraceChat UI).
**Relacionado:** F5 Studio UI (Plan 28), Plan 22 (workspace UI).

## Intent

La landing de Triage Studio tiene un sistema de diseño "control-room" cuidado (paleta teal/ámbar,
tokens CSS, light+dark), pero **el resto de la app está dispar**: páginas en Tailwind indigo/gris,
navbar "Email Triage" **duplicado en 5 páginas**, sin modo oscuro, y "Email Triage" residual en
varios lugares. Parecen dos productos.

Este plan unifica todo bajo **un solo sistema de diseño** derivado de la landing, con marca
**"Triage Studio"** consistente y **modo claro/oscuro en toda la app**. Decisión del usuario:
**rediseño completo** de todas las páginas (no solo un swap de color) + **light + dark**.

## Prior reading

- Tokens de la landing: `frontend/src/pages/Landing.css` (`:root` light, `@media
  prefers-color-scheme: dark`, `:root[data-theme="light|dark"]`) — ya globales, solo cargados en `/`.
- Toggle de tema actual: efecto en `frontend/src/pages/Landing.tsx` (flip de `data-theme` en `<html>`).
- Tailwind **v4** sin config; `frontend/src/index.css` = solo `@import "tailwindcss"`.
- Root: `frontend/src/main.tsx` → `App` → `AuthProvider` → `BrowserRouter`.
- Navbar duplicado + "Email Triage": `pages/{Dashboard,Studio,Settings,Workspace,Compare}.tsx`;
  taglines en `pages/{Login,Signup}.tsx`. `index.html` `<title>` = "frontend".
- Tailwind v4 theming (`@theme` / `@theme inline`) para exponer los tokens como utilidades.

## Scope

**Incluido:**
- **Fundación:** `theme.css` (tokens canónicos light/dark + base global) + puente `@theme inline` en
  `index.css`; `ThemeContext` (provider + toggle + persistencia) + script no-flash en `index.html`.
- **Primitivas** `components/ui/*`: `AppShell`/Navbar, `Card`, `SectionHead`, `Button`, `Field`,
  `Tag`, `AuthLayout`, `ThemeToggle`.
- **Rediseño** de las 9 páginas a shell + primitivas + tokens (solo presentación).
- Restyle de `components/{WorkspaceSwitcher,TraceChat}.tsx` a tokens.
- Rename "Email Triage" → "Triage Studio"; `index.html` `<title>` + favicon.
- Landing consume los tokens globales (deja de duplicarlos) y usa el toggle del provider.

**Fuera de scope:**
- Cambios de backend o de contenido (solo presentación).
- Nuevas páginas o features; cambios de layout de la landing (solo tokens + toggle unificado).
- Rediseño del contenido del prompt de ejemplo (`landingBody.ts`) — el `email-triage assistant` ahí
  es contenido, se deja.

## Concrete changes

| Archivo | Cambio |
|---|---|
| `frontend/src/theme.css` | **nuevo** — tokens (light/dark/`data-theme`) + `body`/`::selection`/`:focus-visible` |
| `frontend/src/index.css` | `@import "./theme.css"` + `@theme inline` (map vars → utilidades Tailwind) |
| `frontend/src/ThemeContext.tsx` | **nuevo** — `theme`, `toggle`, persistencia (localStorage + `prefers-color-scheme`) |
| `frontend/src/main.tsx` | envolver en `ThemeProvider` |
| `frontend/index.html` | `<title>` = "Triage Studio", script no-flash, favicon `</>` |
| `frontend/src/components/ui/*` | **nuevos** — AppShell, Card, SectionHead, Button, Field, Tag, AuthLayout, ThemeToggle |
| `frontend/src/components/{WorkspaceSwitcher,TraceChat}.tsx` | restyle indigo → brand/tokens |
| `frontend/src/pages/Landing.{tsx,css}` | quitar bloque de tokens (usa globales); toggle vía provider |
| `frontend/src/pages/*.tsx` (9) | rediseño a shell + primitivas + tokens; rename marca |

Utilidades nuevas vía `@theme inline`: `bg-paper`, `bg-ground`, `text-ink`, `text-muted`,
`border-line`, `bg-brand`, `hover:bg-brand-bright`, `text-brand`, `ring-brand`, `font-mono`.

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Tokens semánticos + `@theme inline` | Paleta indigo de Tailwind | Theme-aware solo; reusa el diseño ya validado de la landing |
| Un `theme.css` global (fuente única) | Duplicar tokens en app y landing | Evita drift; la landing ya los declara en `:root` |
| `data-theme` en `<html>` + script no-flash | Solo `prefers-color-scheme` | Toggle manual + sin parpadeo al recargar |
| Primitivas `components/ui/*` | Restyle inline por página | Consistencia y velocidad; mata el navbar duplicado (×5) |
| Solo presentación (handlers intactos) | Refactor de lógica | Minimiza riesgo; los tests backend no cambian |

## Risks / Open questions

- **Contraste en dark:** usar SIEMPRE tokens semánticos (`text-ink`, `text-muted`, `bg-paper`,
  `border-line`), nunca grises hardcodeados, o el dark se rompe. Revisar página por página.
- **Flash de tema:** requiere el script inline en `index.html` antes de React.
- **Doble manejo de tema landing/app:** unificar en el provider; el `#themeBtn` de la landing debe
  llamar al toggle compartido (no flipear `data-theme` por su cuenta).
- **Chips de categoría dinámicos:** el Dashboard hoy hardcodea colores; pasar a chip brand/neutral
  (las categorías son slugs por-workspace, no un enum fijo).
- **Superficie grande** (~12+ archivos): faseado abajo; verificación visual claro/oscuro en cada fase.

## Execution order

1. Fundación: `theme.css` + `index.css` bridge + `ThemeContext` + no-flash + `main.tsx`.
2. Primitivas `components/ui/*` + `AppShell`; montar en 1 página de prueba.
3. Páginas autenticadas: Dashboard → Studio → Settings → Workspace → Compare → NewWorkspace.
4. Auth pages: Login/Signup/AcceptInvite con `AuthLayout`.
5. Landing: consumir tokens globales + toggle unificado; rename + `index.html`.
6. Gates + walkthrough visual claro/oscuro.

## Done when

- [x] Ninguna página dice "Email Triage" (salvo un comentario de código en `api.ts` sobre el backend); marca "Triage Studio" en UI + `<title>`
- [x] Toda la app usa la paleta teal/ámbar y soporta claro/oscuro (toggle + `prefers-color-scheme`, sin flash)
- [x] Un solo navbar/shell compartido (`AppShell`, no duplicado) + primitivas `components/ui/*`
- [x] `tsc --noEmit` + `eslint` + `vite build` verdes
- [~] Walkthrough visual: **landing, login, signup verificados en claro y oscuro**; páginas autenticadas (Dashboard/Studio/Settings/Workspace/Compare) pendientes de verificación con backend/login (reusan el mismo shell+primitivas y compilan verde)
- [x] `docs/features/34-*` y `docs/testing/34-*`
- [ ] Humano validó con la guía de testing (login → recorrer páginas autenticadas en ambos temas)
