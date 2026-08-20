# 49. CI de frontend — gates estáticos + Vitest (unit) + Playwright (e2e)

**Status:** 🚧 implemented (rama `feat/frontend_CI`, pending human commit/review/merge)
**Estimate:** ~4–6 hrs (Playwright es el grueso)
**Depends on:** nada del backend. Reutiliza el `frontend/` de Plans 17/20/…; complementa el
CI de backend de [Plan 48](48-ci-testing-and-security.md). Externo: la versión de Node de
Vercel (ver §Node).
**Tipo:** tooling / CI + tests nuevos. No toca código de la app (`src/**` de la app), solo
config y tests nuevos. Si un test revela un bug real, se **reporta**, no se arregla de callado.

## Intent

El `frontend/` (Vite 8 + React 19 + TS ~6 + Tailwind 4) **no tiene ningún test ni gate en
CI** hoy. Un PR puede romper tipos, lint o el build sin señal, y no hay red de seguridad de
comportamiento. Este plan agrega, en tres capas de valor creciente:

1. **Gates estáticos** — lint + typecheck + build en cada PR. Cero tests que escribir,
   valor inmediato (atrapa tipos rotos, imports muertos, reglas de eslint, y que el bundle
   compile).
2. **Vitest (unit)** — framework + smoke tests sobre la **lógica pura** del SPA.
3. **Playwright (e2e)** — flujos de UI end-to-end con la **API mockeada** (sin backend real),
   deterministas y self-contained en CI.

## Scope

- **Incluido:** un workflow `frontend-ci.yml` con jobs paralelos (`lint`, `build`, `test`,
  `e2e`), instalación de Vitest + Testing Library + Playwright, configs, y un set inicial de
  tests. Node fijado en repo (`engines` + `.nvmrc`) para atar CI == Vercel == dev.
- **Fuera de alcance:** cobertura como gate, visual regression, e2e contra el backend real
  (se mockea la API), y tests exhaustivos de todas las páginas (se arranca con los flujos de
  mayor valor / menor flakiness).

## Node — cómo "matcheamos Vercel" de verdad

**Hallazgo:** no hay versión de Node fijada en ningún lado del repo — sin `.nvmrc`, sin
`engines` en `package.json`, y `vercel.json` solo tiene rewrites SPA. La versión que usa
Vercel vive en el **dashboard del proyecto** (no accesible desde el repo).

**Decisión:** en vez de adivinar, **fijar la versión en el repo y forzar a Vercel a
respetarla**:

- `package.json` → `"engines": { "node": "24.x" }` — **Vercel respeta `engines.node`**, así
  que esto ata el deploy.
- `frontend/.nvmrc` → `24` — para dev local.
- El workflow usa `node-version-file: frontend/.nvmrc` — misma fuente de verdad.

Valor: **24** — match literal con lo que el proyecto tenía en el dashboard de Vercel (el log
del deploy mostró `Node.js version changed from "24.x" to "22.x"`), y coincide con
`@types/node ^24`. Antes del fix las tres fuentes divergían (Vercel 24, CI/engines sin fijar);
ahora quedan atadas a 24.

## Estructura en 3 commits (para que el PR sea revisable por capas)

### Commit 1 — Gates estáticos
- `.github/workflows/frontend-ci.yml`: triggers push→main + PR con
  `paths: ['frontend/**', '.github/workflows/frontend-ci.yml']` (no corre en PRs de backend);
  `concurrency` cancel-in-progress; `defaults.run.working-directory: frontend`.
- Setup común: `checkout` → `setup-node@v4` (`node-version-file: frontend/.nvmrc`,
  `cache: npm`, `cache-dependency-path: frontend/package-lock.json`) → `npm ci`.
- Job `lint`: `npm run lint` (eslint flat config, v10).
- Job `build`: `npx tsc -b` (typecheck con señal propia) + `npm run build` (valida bundle Vite).
- `engines` en `package.json` + `frontend/.nvmrc`.

### Commit 2 — Vitest (unit)
- Deps dev: `vitest`, `@testing-library/react`, `@testing-library/jest-dom`,
  `@testing-library/user-event`, `jsdom`.
- `vitest.config.ts` (environment `jsdom`, setup file con `jest-dom`); scripts
  `"test": "vitest run"`, `"test:watch": "vitest"`.
- Tests iniciales sobre **lógica pura** (mejor ROI, sin flakiness):
  - `src/api.ts` → `API_BASE`, wrappers con `fetch` mockeado, y el manejo de 401
    (`setUnauthorizedHandler`).
  - `src/rbac.ts`, `src/invite.ts` → permisos / parsing.
  - Un smoke render: `Landing` monta sin romper.
- Job `test`: `npm run test`.

### Commit 3 — Playwright (e2e)
- Dep dev: `@playwright/test`; `playwright.config.ts` con `webServer` que levanta
  `vite preview` (el build servido) — **sin backend**.
- **API mockeada** vía `page.route('**/auth/**', …)`, `'**/triage/**'`, etc. → e2e
  determinista, sin Postgres/Groq.
- Flujos iniciales (mayor valor / menor flakiness):
  - Landing carga y muestra el CTA.
  - Ruta protegida sin sesión (`/dashboard`) → redirige a `/login` (pura lógica de
    `ProtectedRoute`; ni siquiera necesita mock).
  - Login con API mockeada devolviendo token → aterriza en el dashboard.
- Job `e2e`: cachea browsers, `npx playwright install --with-deps chromium`,
  `npx playwright test`; sube `playwright-report` como artifact.

## Concrete changes

| File | Change |
|---|---|
| `.github/workflows/frontend-ci.yml` | Nuevo. Jobs `lint` / `build` / `test` / `e2e` (paralelos), path-filtered a `frontend/**`. |
| `frontend/package.json` | `engines.node`, scripts `test`/`test:watch`, devDeps (vitest, testing-library, jsdom, @playwright/test). |
| `frontend/.nvmrc` | Nuevo. `22`. |
| `frontend/vitest.config.ts` | Nuevo. jsdom + setup. |
| `frontend/vitest.setup.ts` | Nuevo. `@testing-library/jest-dom`. |
| `frontend/playwright.config.ts` | Nuevo. `webServer: vite preview`, chromium. |
| `frontend/src/**/*.test.ts(x)` | Nuevos. Unit tests (api/rbac/invite/Landing). |
| `frontend/e2e/*.spec.ts` | Nuevos. Flujos con API mockeada. |
| `frontend/package-lock.json` | Actualizado por `npm install` de las nuevas devDeps. |
| `frontend/.gitignore` | `playwright-report/`, `test-results/`, `coverage/`. |

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Fijar Node vía `engines` + `.nvmrc`, workflow con `node-version-file` | Hardcodear `node-version: 22` en el YAML | Ata CI == Vercel == dev a una única fuente; evita divergencia CI/prod (que era el pedido "matchear Vercel"). |
| e2e con **API mockeada** (`page.route`) sobre `vite preview` | Levantar el backend real (Postgres + Groq) en CI | Determinista, sin infra ni secrets; el objetivo es la UI, no re-testear la API (eso es Plan 48). |
| Jobs **separados** lint/build/test/e2e | Un solo job con steps secuenciales | Señales de fallo claras (tipos vs lint vs bundle vs UI) y paralelismo. |
| Path-filter `frontend/**` | Correr siempre | No gasta minutos en PRs que solo tocan backend. |
| Unit sobre **lógica pura** primero | Empezar por render de páginas complejas | Máximo ROI, mínima flakiness; los componentes con contexto/routing se cubren mejor en e2e. |
| Arrancar e2e solo con chromium | Los 3 browsers (chromium/firefox/webkit) | CI más rápido/estable; se amplía cuando el set madure. |

## Risks / Open questions

- **PR grande** (3 frameworks + config). Mitigado con los 3 commits separados; si se
  prefiere, Commit 3 (Playwright) puede ir en su propia rama/PR.
- **Node de Vercel:** se asume 22; **confirmar con el dashboard** antes de implementar. Es
  la única decisión abierta.
- **Flakiness de Playwright:** aun mockeado, es el punto más frágil. Si un flujo depende de
  estado del backend que no vale mockear, se marca y se deja fuera del set inicial.
- **Bugs reales:** si un test falla por un bug de la app (no del test), se reporta al humano;
  no se toca código de la app en este plan.
- **`main` ya roto:** si lint/tipos vienen fallando desde `main`, se reporta en vez de
  silenciar; el humano decide si se arregla acá o en otra rama.

## Setup (humano — el agente no puede)

1. Confirmar la versión de Node del proyecto en Vercel (o aceptar 22 como default).
2. Post-merge: (opcional) marcar los checks de `frontend-ci` como required en `main`.

## Testing

- **Local antes de entregar:** en `frontend/` correr `npm ci` → `npm run lint` →
  `npx tsc -b` → `npm run build` → `npm run test` → `npx playwright test`, y mostrar la salida.
- **Post-merge (humano):** abrir un PR que toque `frontend/**` y verificar los 4 checks +
  el artifact `playwright-report`.

## Done when

- [x] `frontend-ci.yml` con lint/build/test/e2e, path-filtered.
- [x] Node atado vía `engines` + `.nvmrc` + `node-version-file`.
- [x] Vitest instalado + set inicial de unit tests verde (14 tests: `api`/`rbac`/`invite`).
- [x] Playwright instalado + flujos iniciales (API mockeada) verdes (4 tests: landing + auth).
- [ ] `docs/features/49-*.md` + `docs/testing/49-*_testing.md` (pendiente).
- [x] Node confirmado por el humano: **24** (match con el dashboard de Vercel).
- [ ] Humano validó el PR.

## Implementación (registro)

- **Baseline verificado:** `main` estaba verde en lint/tsc/build antes de empezar.
- **Unit split de diseño:** el render de páginas (Router/Theme providers) se dejó **fuera de
  Vitest** por frágil en jsdom; se cubre en Playwright. Vitest = solo lógica pura.
- **Deps agregadas (dev):** `vitest`, `jsdom`, `@playwright/test`. No se instaló
  `@testing-library/*` (no hay render en Vitest); se agrega si/cuando haya component tests.
- **e2e sin backend:** `page.route()` mockea `/auth/login`, `/auth/me`, `/workspaces`;
  `vite preview` sirve el bundle. Selectores estables: placeholders del form de login y el
  heading `Hello, {display_name}` del Dashboard; CTA `Log in` del landing.
- **`tsconfig.node.json`** ahora incluye `vitest.config.ts` y `playwright.config.ts` para
  que `tsc -b` los typechequee.
- **Dependabot npm:** NO se agregó en esta rama a propósito — la rama de backend (Plan 48)
  ya crea `.github/dependabot.yml` con el ecosistema `npm` para `/frontend`. Crear otro acá
  garantizaría un conflicto de merge. Si esa rama no mergea, agregarlo después.
- **Verificado local:** lint ✓ · `tsc -b` ✓ · build ✓ · Vitest 14/14 ✓ · Playwright 4/4 ✓ · YAML ✓.

### Build de prod desacoplado del tooling de tests (fix Vercel)

**Problema (visto en Vercel):** el deploy corre `npm run build` = `tsc -b && vite build`, y
`tsc -b` estaba typecheckeando `vitest.config.ts` (que tenía `all: true`, inválido en Vitest
4) → el build de prod rompía por config de **tests**. Además, meter tooling de test en el
grafo del build es incorrecto de por sí.

**Fix (separación de responsabilidades):**
- `tsconfig.app.json` **excluye** `src/**/*.test.ts(x)`.
- `tsconfig.node.json` vuelve a incluir **solo** `vite.config.ts` (sin vitest/playwright).
- Nuevo `tsconfig.test.json` (standalone, **no** en las project-references del root) typechea
  tests + configs. Se corre en CI con `npm run typecheck:test`, nunca en el build de prod.
- `vitest.config.ts`: se quitó `all: true` (Vitest 4 lo removió de `CoverageOptions`); el
  universo del reporte lo define `coverage.include`.

**Garantía verificada:** `tsc -b --listFiles` del build de prod **no** contiene
`vitest.config`, `playwright.config`, `*.test.ts` ni `e2e/`. El tooling de test se instala en
Vercel (son devDeps, como `vite`/`tsc`) pero el build no lo ejecuta ni lo typechea.
