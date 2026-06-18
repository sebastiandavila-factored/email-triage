# 20. Frontend Deploy — Vercel (SPA) + FastAPI Cloud (API) + Neon (DB)

**Status:** 📋 proposed
**Estimate:** 2.5 hrs
**Depends on:** Plan 17 (React frontend), CORS middleware (config-gated, ya en `main.py`).

> Guía ejecutable paso a paso: [docs/DEPLOY.md](../DEPLOY.md).

## Intent

El frontend funciona en local gracias al **proxy de Vite** (`/auth`, `/triage`,
`/health` → `localhost:8000`), que hace que todo sea same-origin. En producción
no hay proxy: el SPA será estático en **Vercel** (`https://…vercel.app`) y
llamará a la **API en FastAPI Cloud** (`https://…fastapicloud.dev`), con la DB en
**Neon** — orígenes distintos. Este plan hace los cambios mínimos para que el SPA
hable con la API cross-origin de forma segura, y documenta el despliegue.

> FastAPI Cloud usa su propio buildpack uv e **ignora** `Dockerfile`/`render.yaml`
> (ver [postmortem 01](../postmortems/01-fastapi-cloud-src-layout.md)). El
> entrypoint sale de `[tool.fastapi]` en `pyproject.toml`. Secrets vía
> `fastapi cloud env set --secret`; deploy con `fastapi deploy`.

La pieza conceptual clave: distinguir **navegaciones top-level** (el flujo
OAuth, que va directo al backend) de **peticiones fetch del SPA** (que son
cross-origin y necesitan CORS). Solo las segundas pasan por CORS.

## Arquitectura de producción

```
                         ┌────────────────────────────────┐
  navegador  ──fetch────▶│ <app>.fastapicloud.dev          │  ← CORS aplica aquí
     │                   │ FastAPI Cloud → Neon (Postgres) │
     │  /auth/signup, /auth/login(POST), /auth/me,          │
     │  /triage, /auth/rotate-key   (Authorization /        │
     │                   │ X-Api-Key en headers)            │
     │                   └────────────────────────────────┘
     │
     │  estáticos (HTML/JS/CSS)
     ▼
  app…vercel.app (Vercel)  ── SPA build (vite) ──

  Flujo Google SSO = NAVEGACIONES top-level (NO fetch, NO CORS):
  Login → GET <app>.fastapicloud.dev/auth/login → Google → /auth/callback
        → 302 a app…vercel.app/#token=<jwt>
```

## Scope

**Incluido:**
- `frontend/src/api.ts`: base URL configurable vía `VITE_API_URL` (vacío en dev → relativo/proxy; absoluto en prod).
- `frontend/src/pages/Login.tsx`: el enlace "Continue with Google" usa la base absoluta.
- `frontend/vercel.json`: rewrites SPA (todas las rutas → `index.html`) para que `/dashboard`, `/login`, etc. no den 404 al recargar.
- `frontend/.env.example`: documentar `VITE_API_URL`.
- Guía de configuración en Vercel (root dir, build, env) y en FastAPI Cloud (CORS, FRONTEND_URL).
- Guía de Google Cloud Console (redirect URI de prod).

**Fuera de scope:**
- Dominio propio / DNS (se usa el `*.vercel.app` y `*.fastapicloud.dev` por defecto).
- CI/CD más allá del auto-deploy de Vercel por push.
- SSR / edge functions (el SPA es estático puro).
- Streaming UI (`/triage/stream`) — plan aparte.

## Cambios de código

| Archivo | Cambio |
|---|---|
| `frontend/src/api.ts` | `const API_BASE = import.meta.env.VITE_API_URL ?? ''`; prefijar todas las rutas con `API_BASE`. |
| `frontend/src/pages/Login.tsx` | `href={`${API_BASE}/auth/login`}` en vez de `/auth/login` (es una navegación al **backend**, no al SPA). |
| `frontend/vercel.json` | Rewrites SPA + (opcional) headers de caché. |
| `frontend/.env.example` | Añadir `VITE_API_URL=` (vacío = usa el proxy de Vite en dev). |
| `email_triage/...` | Ninguno — el backend ya está listo (CORS gated + `frontend_url`). Solo cambian variables de entorno. |

### Detalle: `api.ts`

```ts
// Vacío en dev → rutas relativas → las resuelve el proxy de Vite.
// En prod, VITE_API_URL = https://<app>.fastapicloud.dev (sin barra final).
const API_BASE = import.meta.env.VITE_API_URL ?? ''

async function request<T>(path: string, options: RequestInit = {}, token?: string | null): Promise<T> {
  ...
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  ...
}
```

`import.meta.env.VITE_*` se inyecta **en build time** por Vite — por eso la URL
del backend debe estar en las env vars de Vercel antes del build, no en runtime.

### Detalle: `vercel.json`

```json
{
  "rewrites": [{ "source": "/(.*)", "destination": "/index.html" }]
}
```

Sin esto, recargar en `/dashboard` devuelve 404 (Vercel busca un archivo
`/dashboard` que no existe). El rewrite sirve `index.html` para toda ruta y deja
que React Router resuelva en el cliente.

## Variables de entorno (resumen)

| Dónde | Var | Valor |
|---|---|---|
| Vercel (build-time) | `VITE_API_URL` | `https://<app>.fastapicloud.dev` |
| FastAPI Cloud | `CORS_ORIGINS` | `https://<tu-app>.vercel.app` (separado por comas si hay varios) |
| FastAPI Cloud | `FRONTEND_URL` | `https://<tu-app>.vercel.app` |
| FastAPI Cloud | `GOOGLE_REDIRECT_URI` | `https://<app>.fastapicloud.dev/auth/callback` |
| FastAPI Cloud | `DATABASE_URL` | `postgresql+asyncpg://…neon…?sslmode=require` (endpoint **directo**) |
| FastAPI Cloud | `SESSION_SECRET` | 32+ bytes reales (no el default) |
| FastAPI Cloud | `LOGFIRE_ENVIRONMENT` | `production` (cookie `Secure` + valida el secret) |

Comandos concretos (`fastapi cloud env set --secret`, deploy, Vercel UI, Google
Console, Neon) y verificaciones por fase: ver **[docs/DEPLOY.md](../DEPLOY.md)**.

## Orden de ejecución

1. **Código** (ya hecho): `api.ts` base URL, `Login.tsx` link, `vercel.json`.
   Verificar local con el pre-flight CORS (Fase 0 de DEPLOY.md).
2. **DB** → **backend** (FastAPI Cloud) → **frontend** (Vercel) → **re-cablear**
   (`CORS_ORIGINS`/`FRONTEND_URL` con la URL real de Vercel) → **smoke test**.
   Cada paso con su verificación en DEPLOY.md.

## Design decisions

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| `VITE_API_URL` con default vacío | Hardcodear la URL del backend | Dev sigue usando el proxy (cero fricción); prod inyecta la URL en build |
| CORS sin `allow_credentials` | `allow_credentials=True` | La auth va en headers (`Authorization`/`X-Api-Key`), no en cookies → no hace falta, y evita la combinación prohibida con `*` |
| Origen pineado en `CORS_ORIGINS` | `allow_origins=["*"]` | Práctica correcta; `*` es innecesario y peor higiene |
| El link de Google va al backend absoluto | Proxyear `/auth/login` desde Vercel | Es una navegación top-level que setea una cookie first-party del backend; proxyearla complicaría el dominio de la cookie |
| Vercel (estático) + FastAPI Cloud (API) | Todo junto en un PaaS, o Next.js SSR | El SPA es estático puro; Vercel da CDN + previews gratis sin SSR, y el backend ya está linkeado a FastAPI Cloud |

## Riesgos / Open questions

- **Preview deployments de Vercel:** cada PR genera una URL única
  (`<hash>.vercel.app`). Esa URL **no** estará en `CORS_ORIGINS` ni en el
  `redirect_uri` de Google → en previews, las llamadas fetch fallan por CORS y
  el SSO de Google no vuelve bien. Mitigaciones: (a) `allow_origin_regex` para
  `https://.*\.vercel\.app` en el backend para que al menos el login por
  password funcione en previews; (b) asumir que el SSO de Google solo se prueba
  en producción. Documentar la limitación.
- **Cold start (free tier):** el primer request tras inactividad puede tardar;
  el SPA debe tolerar timeouts/spinners.
- **Neon + asyncpg:** usar el endpoint **directo**, no el `-pooler` (PgBouncer en
  modo transacción rompe los prepared statements de asyncpg).
- **`VITE_API_URL` es build-time:** cambiarla exige re-build en Vercel (un
  redeploy), no basta con editar la env y reiniciar.
- **Cookie `Secure` en prod:** requiere `LOGFIRE_ENVIRONMENT=production` para que
  `is_prod` sea true y la cookie PKCE sea `Secure`. Si no, el navegador podría
  rechazarla bajo HTTPS estricto.

## Done when

- [ ] `VITE_API_URL` vacío en dev → la app sigue funcionando con el proxy de Vite
- [ ] Build de Vercel verde; `https://<app>.vercel.app` carga el SPA
- [ ] Signup / login / triage funcionan contra la API de FastAPI Cloud (CORS OK, sin errores en consola)
- [ ] "Continue with Google" completa el flujo y aterriza en `/dashboard`
- [ ] Recargar en `/dashboard` no da 404 (rewrite SPA)
- [ ] `docs/exec-plans/README.md` actualizado con entry #20
