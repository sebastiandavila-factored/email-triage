# 30. Landing as the app root + login entry

**Status:** ✅ delivered (`/` = landing en el SPA, botón "Log in", CSS scopeado; `tsc`+`eslint`+`vite build` verdes, verificado en vivo).
**Estimate:** ~2 hrs
**Depends on:** Plan 28 (SPA), F6 (landing HTML).

## Intent

El SPA arrancaba en `/dashboard`/`/login`. El usuario quiere que **la base sea la
landing**: `/` muestra la página explicativa (la de F6) con un **botón de "Log in"**
para entrar a la plataforma. Los usuarios ya autenticados (incluido el retorno de
Google SSO, que llega a `/#token=…`) se redirigen directo a la app.

## Cómo

La landing de F6 es un HTML self-contained. Para meterla en el SPA sin reescribir 300
líneas a JSX a mano (y sin arriesgar bugs de conversión), se **porta con un script**:

- `frontend/src/pages/Landing.css` — el `<style>` de la landing, con los selectores
  **de elemento/globales scopeados bajo `.ts-root`** (`*`, `h1/h2/h3`, `p`, `code`,
  `section`, `footer`, `:focus-visible`) para que **no se filtren** a login/dashboard.
  Además: fix de `content: "\2192"` (las flechas del flujo estaban como `&rarr;`
  literal en CSS) y `min-height: 100vh`.
- `frontend/src/pages/landingBody.ts` — el body (topbar→footer) como string, con las
  CTAs reescritas a **"Log in"** (`/login`).
- `frontend/src/pages/Landing.tsx` — renderiza el body vía `dangerouslySetInnerHTML`
  (así las entidades HTML decodifican bien, cosa que JSX no haría), corre los scripts
  (tema, reveal, barra de confianza) en un `useEffect`, e **intercepta los clicks a
  links internos** (`/…`) para navegar por SPA (los `#hash` mantienen su scroll nativo).
  Si hay `token`, `→ <Navigate to={nextAfterAuth()} />`.

Regenerar (si se edita la landing fuente):
```bash
# el script de porte vive en el historial del Plan 30; re-ejecutar sobre
# docs/landing/triage-studio.html regenera Landing.css + landingBody.ts
```

## Routing (`App.tsx`)

- `+ <Route path="/" element={<Landing />} />` (público).
- Catch-all `*` → `<Navigate to="/" />` (antes iba a `nextAfterAuth()`; ahora la Landing
  hace ese reenvío cuando hay sesión). SSO vuelve a `/#token` → `AuthContext` captura el
  token en bootstrap → Landing ve `token` → redirige a la app. Sin cambios de backend.

## Concrete changes

| Archivo | Cambio |
|---|---|
| `frontend/src/pages/Landing.tsx` | **nuevo** — página landing (redirect si autenticado, scripts, SPA-nav) |
| `frontend/src/pages/Landing.css` | **nuevo** — CSS de la landing scopeado bajo `.ts-root` |
| `frontend/src/pages/landingBody.ts` | **nuevo** — body HTML + CTAs de login |
| `frontend/src/App.tsx` | ruta `/` → Landing; catch-all → `/`; quita `nextAfterAuth` import |
| `docs/landing/triage-studio.html` | fix flechas `content: "\2192"` (republicado el Artifact) |

## Design decisions

| Decisión | Alternativa | Razón |
|---|---|---|
| Port por script + `dangerouslySetInnerHTML` | Reescribir a JSX a mano | Evita bugs de conversión (entidades, inline styles); HTML idéntico |
| CSS scopeado bajo `.ts-root` | CSS global | El SPA es Tailwind; los selectores de elemento de la landing romperían login/dashboard |
| Interceptar clicks internos → router | `<a href>` full reload | Navegación SPA fluida a `/login`; los `#hash` siguen con scroll nativo |
| Landing redirige a la app si hay sesión | Mostrar landing a logueados | Comportamiento SaaS habitual; además resuelve el retorno de SSO a `/` |

## Riesgos / notas

- **Drift landing↔SPA:** hay dos copias (el HTML fuente/Artifact y los archivos porteados).
  Si se edita la landing, re-correr el script de porte. Anotado en `landingBody.ts`.
- **Tema en la app:** el toggle estampa `data-theme` en `<html>`; la app usa colores fijos
  de Tailwind (sin variantes dark), así que no la afecta visualmente.

## Done when

- [x] `/` muestra la landing; `/login` y `/dashboard` sin fugas de estilo
- [x] Botón "Log in" (topbar + hero + closing) entra a `/login` por SPA
- [x] Usuario autenticado en `/` → redirige a la app (SSO incluido)
- [x] `npm run build` + `eslint` verdes; verificado en vivo (dev server)
