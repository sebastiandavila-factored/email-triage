# Guía de deploy — producción (FastAPI Cloud + Neon + Vercel)

> Runbook ejecutable. Sigue los pasos en orden; cada uno tiene su verificación.
> Diseño y porqué en
> [exec-plans/20-frontend-vercel-deploy.md](exec-plans/20-frontend-vercel-deploy.md).
> Prerequisitos de código ya en el repo (CORS gated, `VITE_API_URL`, link de
> Google absoluto, `vercel.json`).

## Arquitectura final

```
app.vercel.app  ──fetch (CORS)──▶  <app>.fastapicloud.dev  ──▶  Neon (Postgres) + Groq
   (SPA estático, Vercel)            (FastAPI Cloud)
```

Tres servicios. El orden importa porque se cruzan: el backend necesita la URL de
Vercel (CORS/redirect) y el frontend necesita la URL del backend
(`VITE_API_URL`). Por eso: **DB → backend → frontend → re-cablear el backend**.

> **Nota:** FastAPI Cloud **no usa** el `Dockerfile` ni `render.yaml` del repo
> (corre su propio buildpack uv — ver
> [postmortems/01](postmortems/01-fastapi-cloud-src-layout.md)). Esos archivos
> son para un deploy alternativo en Render/self-host; aquí se ignoran. El
> entrypoint sale de `[tool.fastapi] entrypoint = "email_triage.main:app"` en
> `pyproject.toml`.

---

## Fase 0 — Pre-flight local (10 min)

Valida el **camino CORS real** en local (sin el proxy de Vite, que lo enmascara):

```bash
# Terminal 1 — backend con CORS para el SPA local
cd email-triage
CORS_ORIGINS=http://localhost:5173 uv run fastapi dev

# Terminal 2 — frontend apuntando DIRECTO al backend (salta el proxy)
echo 'VITE_API_URL=http://localhost:8000' > frontend/.env.local
make frontend-dev
```

Abre http://localhost:5173, haz signup + un triage. Si va sin errores de CORS en
consola, el camino cross-origin está bien. **Borra el override**:

```bash
rm frontend/.env.local
```

✅ **Check:** signup + triage OK, cero errores de CORS.

---

## Fase 1 — Base de datos en Neon (15 min)

1. En [neon.tech](https://neon.tech) crea un proyecto → te da una connection string.
2. Usa el endpoint **directo** (no el `-pooler`). El pooler de Neon es PgBouncer
   en modo transacción y rompe los *prepared statements* de asyncpg; como
   SQLAlchemy ya gestiona el pool (`pool_size=5, max_overflow=10`), el endpoint
   directo es lo correcto aquí.
3. **Transforma la string** a lo que espera la app:
   - esquema `postgresql://` → `postgresql+asyncpg://`
   - deja **solo** `?sslmode=require` (quita `channel_binding=…` y otros params
     libpq que asyncpg no entiende). `_parse_url` traduce `sslmode=require` a
     `ssl=require`.
   - Resultado: `postgresql+asyncpg://user:pass@ep-xxx.neon.tech/dbname?sslmode=require`
4. Aplica las migraciones desde tu máquina apuntando a Neon:
   ```bash
   DATABASE_URL='postgresql+asyncpg://…(neon)…?sslmode=require' uv run alembic upgrade head
   ```

✅ **Check:** `alembic upgrade head` termina sin error; en el dashboard de Neon
ves las tablas `users`, `tenants`, `memberships`, `triage_logs`, etc.

---

## Fase 2 — Backend en FastAPI Cloud (20 min)

El proyecto ya está linkeado (`.fastapicloud/cloud.json`). Si no, `fastapi cloud link`.

### 2.1 Login
```bash
cd email-triage
uv run fastapi login
```

### 2.2 Genera el SESSION_SECRET
```bash
uv run python -c "import secrets; print(secrets.token_hex(32))"
```

### 2.3 Variables de entorno (`fastapi cloud env set`)
`--secret` marca el valor como secreto (no se muestra luego). `FRONTEND_URL` y
`CORS_ORIGINS` quedan provisionales hasta la Fase 4.

```bash
uv run fastapi cloud env set GROQ_API_KEY        "<tu-groq-key>"        --secret
uv run fastapi cloud env set API_KEY             "<cualquier-fallback>" --secret
uv run fastapi cloud env set DATABASE_URL        "postgresql+asyncpg://…neon…?sslmode=require" --secret
uv run fastapi cloud env set SESSION_SECRET      "<hex-de-2.2>"         --secret
uv run fastapi cloud env set GOOGLE_CLIENT_SECRET "<google-secret>"     --secret
uv run fastapi cloud env set LOGFIRE_TOKEN       "<logfire-token>"      --secret   # opcional

uv run fastapi cloud env set LOGFIRE_ENVIRONMENT "production"        # activa cookie Secure + valida el secret
uv run fastapi cloud env set GOOGLE_CLIENT_ID    "<google-client-id>"
uv run fastapi cloud env set GOOGLE_REDIRECT_URI "https://<app>.fastapicloud.dev/auth/callback"
uv run fastapi cloud env set FRONTEND_URL        "https://placeholder"             # se corrige en Fase 4
uv run fastapi cloud env set CORS_ORIGINS        ""                                # se corrige en Fase 4
```

Verifica: `uv run fastapi cloud env list`.

### 2.4 Deploy
```bash
uv run fastapi deploy
```
Anota la URL que imprime (algo como `https://<app>.fastapicloud.dev`). Si el
`GOOGLE_REDIRECT_URI` de 2.3 usó un slug distinto al real, corrígelo ahora con
otro `env set` y redeploy.

✅ **Check:**
```bash
curl https://<app>.fastapicloud.dev/health      # {"status":"ok"}
```
`uv run fastapi cloud logs` para ver el arranque (`db.connected`, `startup`).

---

## Fase 3 — Frontend en Vercel (20 min)

1. [vercel.com/new](https://vercel.com/new) → importa el repo de GitHub.
2. **Root Directory:** `frontend` ← clave (monorepo).
3. **Framework Preset:** Vite. Build `npm run build`, output `dist`.
4. **Environment Variables:**
   | Var | Valor |
   |---|---|
   | `VITE_API_URL` | `https://<app>.fastapicloud.dev` (sin barra final) |
5. **Deploy.** Anota la URL: `https://<tu-app>.vercel.app`.

✅ **Check:** la URL de Vercel carga el login (aún sin poder llamar a la API —
falta CORS, siguiente fase).

---

## Fase 4 — Cruzar el cableado (15 min)

Con la URL real de Vercel, actualiza el backend y redeploya:

```bash
uv run fastapi cloud env set FRONTEND_URL "https://<tu-app>.vercel.app"
uv run fastapi cloud env set CORS_ORIGINS "https://<tu-app>.vercel.app"   # comas si hay varios
uv run fastapi deploy
```

### Google Cloud Console
- Credentials → tu OAuth Client → **Authorized redirect URIs** → añade
  `https://<app>.fastapicloud.dev/auth/callback` (deja también el de localhost).
- Si la app sigue en "testing", añade tu email como test user.

✅ **Check (preflight CORS):**
```bash
curl -i -X OPTIONS https://<app>.fastapicloud.dev/triage \
  -H "Origin: https://<tu-app>.vercel.app" \
  -H "Access-Control-Request-Method: POST"
# Debe incluir: Access-Control-Allow-Origin: https://<tu-app>.vercel.app
```

---

## Fase 5 — Smoke test end-to-end (15 min)

En `https://<tu-app>.vercel.app`, con la consola del navegador abierta:

- [ ] **Signup** (email+password) → aterriza en `/dashboard`, muestra la API key.
- [ ] **Triage** un email → categoría + borrador (sin error de CORS).
- [ ] **Logout** y **Login** con las mismas credenciales.
- [ ] **Continue with Google** → completa el flujo → `/dashboard`.
- [ ] Recargar (F5) en `/dashboard` → **no** 404 (rewrite SPA).
- [ ] **Settings** → rotate key → la nueva key funciona en un triage.

---

## Troubleshooting

| Síntoma | Causa probable | Fix |
|---|---|---|
| `No 'Access-Control-Allow-Origin'` en consola | `CORS_ORIGINS` no es el origen **exacto** de Vercel (barra final / http vs https / subdominio) | `env set CORS_ORIGINS` con el valor exacto + `fastapi deploy` |
| Boot falla con `ModuleNotFoundError: email_triage` | regresión del layout `src/` | el paquete debe estar en la raíz (`email_triage/`), ver postmortem 01 |
| Cambios de env "no aplican" / 503 viejo persiste | el deploy nuevo **crashea al boot** (p.ej. `SettingsError` por una env mal formada) → FastAPI Cloud sigue sirviendo el deploy sano anterior | `fastapi cloud logs` para ver el traceback de arranque; arreglar la var y `fastapi deploy` |
| App arranca pero DB falla | URL con driver/SSL mal, o usaste el endpoint `-pooler` | `postgresql+asyncpg://…?sslmode=require`, endpoint **directo** de Neon |
| `prepared statement "__asyncpg_…" already exists` | usaste el pooler de Neon (PgBouncer) | cambia al endpoint directo |
| F5 en `/dashboard` → 404 | falta rewrite SPA | `frontend/vercel.json` (ya incluido); redeploy en Vercel |
| "Continue with Google" → JSON o 404 | link no apunta al backend, o falta redirect URI en Google | `VITE_API_URL` en build + redirect URI de prod en Google |
| SSO vuelve pero rebota a /login | `FRONTEND_URL` mal o cookie `Secure` rechazada | `FRONTEND_URL` = URL de Vercel; `LOGFIRE_ENVIRONMENT=production` |
| Cambié `VITE_API_URL` y no cambia nada | es **build-time** | redeploy en Vercel |
| Triage da 403 | la SPA no manda `X-Api-Key` válida | entrar/rotar la key en Settings (formato `et_…`) |
| Login Google da 409 | el email ya existe como cuenta password no verificada | iniciar con password (es el comportamiento anti-takeover) |

### Preview deploys de Vercel
Cada PR genera `https://<hash>.vercel.app`, que **no** está en `CORS_ORIGINS` ni
en el redirect URI de Google → en previews fallan fetch y SSO. Opciones:
`allow_origin_regex` en el backend para `https://.*\.vercel\.app` (permite al
menos password auth), o probar SSO solo en producción. Limitación conocida.

---

## Rollback

- **Frontend:** Vercel → Deployments → deploy anterior → "Promote to Production".
- **Backend:** `uv run fastapi deploy` desde un commit anterior (o el dashboard
  de FastAPI Cloud). Si una migración rompió la DB, restaura desde backup de Neon
  (el downgrade de `0002` no está soportado — ver la migración).

---

## Checklist de "producción lista"

- [ ] Neon: endpoint directo, `postgresql+asyncpg://…?sslmode=require`, migraciones aplicadas
- [ ] `SESSION_SECRET` real (no el default) — el validator de `config.py` lo exige en prod
- [ ] `LOGFIRE_ENVIRONMENT=production`
- [ ] `CORS_ORIGINS` y `FRONTEND_URL` = URL exacta de Vercel
- [ ] Redirect URI de prod en Google Console
- [ ] `fastapi cloud env list` sin placeholders
- [ ] Smoke test (Fase 5) en verde
