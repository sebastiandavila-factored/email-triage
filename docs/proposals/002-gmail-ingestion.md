# Propuesta 002 — Conexión a Gmail: traer los correos nuevos del día

> **Estado:** Draft para discusión
> **Autor:** Sebastián + agente
> **Fecha:** 2026-08-07
> **Objetivo estratégico:** cerrar la última milla del producto — pasar de "clasificas un
> correo que pegas a mano" a "abres la app y ves tu bandeja real de hoy ya triada". Convierte
> Triage Studio de demo a herramienta de trabajo diaria.

---

## 1. Resumen ejecutivo

Hoy el triage es **manual o vía API**: en el [Dashboard](../../frontend/src/pages/Dashboard.tsx)
el usuario pega `subject`/`sender`/`body`, o un cliente externo (Zapier/Make) llama a
`POST /triage` con la API key. No existe ingesta de correo real.

La palanca clave: **el flujo OAuth2 con Google ya está implementado y endurecido** para el
login ([routers/auth.py](../../email_triage/routers/auth.py), documentado en
[WALKTHROUGH-oauth2-google.md](../WALKTHROUGH-oauth2-google.md)), pero hoy usa solo los scopes
`openid email profile` con `access_type=online` y **descarta el `access_token`**. Traer los
correos del día es, en esencia, **completar ese flujo**: pedir un scope de Gmail,
`access_type=offline` para obtener un `refresh_token`, guardarlo cifrado por-usuario, y llamar
a la Gmail API. La infra de PKCE, `state`, validación de tokens y el modelo multi-tenant
(User → Membership → Tenant) ya existe y se reutiliza.

El motor de triage (`LLMService`, taxonomía y prompts por workspace) **no cambia**: cada correo
de Gmail se mapea a un `TriageRequest` y pasa por el mismo camino que ya está en producción.

---

## 2. Perspectiva de producto (PM)

### 2.1 Problema y valor

Copiar y pegar cada correo rompe la promesa de un "centro de control de triage". El producto
sabe clasificar pero no puede *alcanzar* los correos. Conectar Gmail elimina la fricción y
entrega el valor central en el primer minuto de la jornada.

### 2.2 Job To Be Done

> *"Cuando empiezo mi jornada, quiero ver los correos nuevos de hoy ya clasificados y con
> borrador de respuesta, para no triarlos uno por uno a mano."*

### 2.3 Personas

| Persona | Necesidad | Rol (RBAC) |
|---|---|---|
| **Owner de workspace** (soporte solo/dueño) | Conectar su Gmail y ver la bandeja del día triada | `owner` |
| **Admin / miembro** | Consumir la bandeja ya conectada del workspace | `admin` / `member` |

**Decisión de producto (v1):** la conexión es **por-usuario que conecta → sincroniza al
workspace activo**. Alineado con el modelo multi-tenant y el RBAC existentes. Una casilla
compartida por-workspace (`soporte@empresa`) queda para v2.

### 2.4 Alcance

**Dentro (v1):**
- Conectar / desconectar una cuenta de Gmail (consentimiento **incremental**, aparte del login).
- Acción "Traer correos de hoy" → sincroniza los mails nuevos del día
  (`in:inbox is:unread newer_than:1d`, límite configurable, p. ej. 25).
- Bandeja que lista esos correos y corre el triage existente por cada uno
  (categoría + confianza + borrador de respuesta).
- Estado de conexión visible (conectado como `x@gmail.com`, última sync) y reconexión.

**Fuera (v2+):**
- Enviar / responder desde la app (v1 es **solo lectura** → menor riesgo y menor scope).
- Sincronización automática en background (Gmail `watch` + Pub/Sub push).
- Otros proveedores (Outlook / IMAP).
- Multi-cuenta por usuario y casillas compartidas por-workspace.
- Persistir el cuerpo de los correos (ver §5, decisión de privacidad).

### 2.5 Restricción crítica de rollout (Google verification)

Leer el **cuerpo** de los correos requiere el scope `https://www.googleapis.com/auth/gmail.readonly`,
que Google clasifica como **RESTRICTED**. Para producción con >100 usuarios se necesita pasar
la **verificación de Google + evaluación de seguridad (CASA)** — semanas y costo. Mientras la
app esté en modo *testing*, funciona con hasta **100 test users** añadidos a mano.

**Implicación de producto:** v1 apunta a **demo controlada / portfolio / entrevista**, no a
escala pública inmediata. Esto se declara explícito para no vender la feature como "lista para
el mundo". Alternativas de menor scope (`gmail.metadata`, *sensitive* no *restricted*) no dan
acceso al cuerpo → no sirven para triar. Por eso `gmail.readonly` es la elección correcta,
asumiendo la restricción de rollout.

### 2.6 Métricas de éxito

- **Activación:** % de owners que conectan Gmail tras verlo.
- **Time-to-value:** segundos desde "Conectar" hasta la primera bandeja triada.
- **Volumen:** correos sincronizados / triados por sesión.
- **Retención de conexión:** % de refresh tokens válidos a 7 / 30 días.
- **Utilidad:** % de borradores copiados (ya hay "Copy reply" en el Dashboard).

---

## 3. Perspectiva de experiencia (UX)

Reutiliza el design system teal/ámbar unificado (Plan 34): `AppShell`, `Card`, `Tag`,
`Button`, tema claro/oscuro, `ThemeToggle`.

### 3.1 Flujos

**A — Conectar (una vez):**
```
Settings/Bandeja → card "Gmail" [Conectar Gmail]
  → consent de Google (scope gmail.readonly, offline, prompt=consent)
  → callback → "Conectado como sebastian@gmail.com ✓"
```

**B — Traer el día (recurrente):**
```
Bandeja → [Traer correos de hoy]
  → skeleton de N filas ("Trayendo tu bandeja…")
  → lista de correos del día
  → cada fila auto-triada: [categoría] · confianza% · ▸ ver borrador
```

### 3.2 Pantallas y estados

**1. Estado desconectado** (card en Settings o en la nueva pestaña "Bandeja"):
- Icono Gmail + copy: *"Conecta tu Gmail para triar los correos nuevos de hoy sin copiar y pegar."*
- Botón primario `Conectar Gmail`.
- Micro-nota de confianza: *"Solo lectura. No enviamos ni borramos nada. Puedes desconectar
  cuando quieras."* (sube conversión: los permisos de Gmail generan fricción).

**2. Estado conectado — Bandeja del día** (ruta nueva `/inbox`, protegida):
- Header: `Conectado como x@gmail.com` · `Última sync: hace 3 min` · `↻ Traer correos de hoy`
  · overflow `Desconectar`.
- **Lista de correos**, cada fila: remitente + asunto + hora, `Tag` de categoría (ámbar) +
  `confianza%`, expandible → cuerpo + borrador + `Copy reply` + (owner/admin) `▸ Ver traces`
  (reusa `TraceChat`).
- **Empty state:** *"Sin correos nuevos hoy 🎉"* — celebratorio, no error.
- **Carga:** skeleton por fila; triage progresivo por fila (aprovecha el streaming existente).

### 3.3 Edge cases

| Situación | Comportamiento UX |
|---|---|
| Token expirado / revocado en Google | Banner *"Se perdió la conexión con Gmail — reconecta"* + botón |
| Usuario deniega el consent | Volver a la bandeja con *"No se conectó Gmail"*, sin romper nada |
| 0 correos hoy | Empty state celebratorio |
| Muchos correos (p. ej. 80) | Limitar (25) + "mostrar más"; nunca triar 80 en serie sin feedback |
| Gmail 429 / rate limit | Reintento con backoff + mensaje suave |
| Cuenta de login ≠ cuenta de Gmail | Permitido; mostrar ambas para que no confunda |

### 3.4 Principios

1. **Consentimiento incremental:** el scope de Gmail NO se mete en el login. El login sigue
   liviano (`openid email profile`); Gmail se pide solo al pulsar "Conectar". Menos abandono,
   mejor postura de privacidad.
2. **Reversibilidad visible:** "Desconectar" siempre a un clic.
3. **Transparencia de permisos:** lenguaje humano — qué se lee, qué NO se hace.
4. **Continuidad visual:** la fila de la bandeja = el resultado del Dashboard (patrón conocido).

---

## 4. Mapa a los dominios de la certificación

Igual que la 001, esta feature toca dominios del *Claude Certified Architect*:

| Dominio | Cómo lo expone esta feature |
|---|---|
| **Tool Design & MCP Integration** | Integración con una API de terceros (Gmail) como *tool* de ingesta; mapeo de mensaje externo → `TriageRequest` tipado. |
| **Context Management & Reliability** | Manejo de secretos (refresh token cifrado), backoff ante 429, degradación con feature-flag si Gmail no está configurado (mismo patrón que `logfire_read_token`). |
| **Prompt Engineering & Structured Output** | El cuerpo de correo real (no confiable) entra en el `<email>` del prompt ya endurecido; el output tipado no cambia. |

---

## 5. Seguridad y privacidad

- **`refresh_token` = activo sensible.** Se guarda **cifrado en reposo** (Fernet con clave de
  entorno) y **nunca** llega al cliente — mismo principio que el `logfire_read_token`, que vive
  solo en el backend.
- **Scope mínimo:** solo `gmail.readonly`. Nada de enviar/borrar/modificar en v1.
- **No persistir cuerpos de correo (v1).** Los correos traídos son **efímeros**: se triagean en
  vuelo y se muestran; solo se persiste el `TriageLog` existente, que ya guarda *chars* y no
  contenido — decisión de privacidad ya tomada en el modelo actual.
- **Consentimiento incremental y revocable:** desconectar borra el `refresh_token` almacenado y
  (opcional) llama al endpoint de revocación de Google.
- **CSRF / PKCE:** el flujo de conexión reutiliza el `state` en cookie firmada y PKCE ya
  existentes; el `state` distingue *login* de *connect* para no cruzar los callbacks.

---

## 6. Mapa técnico

Sin reescribir el motor de triage. Piezas nuevas, todas aditivas:

- **Modelo / migración** (`0006_gmail_connections`): tabla `gmail_connections`
  (`user_id`, `tenant_id`, `google_email`, `refresh_token_enc`, `scopes`, `connected_at`,
  `last_synced_at`). Índice por `(tenant_id, user_id)`.
- **Config** ([config.py](../../email_triage/config.py)): reusa `google_client_id/secret`;
  añade `gmail_redirect_uri`, `gmail_token_enc_key` (clave Fernet), `gmail_sync_max_results`
  (default 25). Feature-flag implícito: sin `gmail_token_enc_key` → endpoints responden 503
  "Gmail no configurado" (patrón `logfire_read_token`).
- **Auth** (`routers/gmail.py`): `GET /gmail/connect` (redirige a Google con
  `scope=...gmail.readonly`, `access_type=offline`, `prompt=consent`, `state` que marca
  `purpose=connect`) + `GET /gmail/callback` (canjea code → guarda `refresh_token` cifrado).
  Reutiliza `pkce.py`, `state.py`.
- **Servicio** (`services/gmail.py`): `GmailClient` con
  `list_today(query="in:inbox is:unread newer_than:1d", max_results)` → `messages.list` +
  `messages.get` (formato `full`) → parse de headers (`Subject`, `From`, `Date`) y `body`
  (base64url, `text/plain` preferido) → `TriageRequest`. Refresca el `access_token` desde el
  `refresh_token` en cada sync (los access tokens de Google viven ~1h).
- **Endpoints de bandeja** (`routers/inbox.py`):
  - `GET /gmail/status` → `{connected, google_email, last_synced_at}`.
  - `POST /gmail/sync` (scope `triage:write`) → trae los correos del día, corre el triage por
    cada uno, devuelve la lista `[{message_id, sender, subject, received_at, category,
    confidence, draft_reply}]`.
  - `DELETE /gmail/connection` (scope `gmail:connect`) → desconecta.
- **RBAC** ([auth/scopes.py](../../email_triage/auth/scopes.py)): nuevo scope `gmail:connect`
  (owner + admin). Leer/sincronizar la bandeja usa el `triage:write` existente.
- **Frontend:** ruta `/inbox` en [App.tsx](../../frontend/src/App.tsx), entrada en `AppShell`,
  card de conexión en [Settings](../../frontend/src/pages/Settings.tsx), y métodos nuevos en
  [api.ts](../../frontend/src/api.ts) (`gmailStatus`, `gmailSync`, `gmailDisconnect`).

---

## 7. Plan de implementación por fases (exec-plans)

Siguiendo la convención de fases del repo. Cada fase deja los gates verdes
(`ruff` + `pyright` + `pytest`; frontend `tsc` + `eslint` + `vite build`).

### F1 — Conexión OAuth + almacenamiento seguro del token *(backend)*
- Migración `0006_gmail_connections`.
- `services/crypto.py` (o util Fernet) para cifrar/descifrar el `refresh_token`.
- `routers/gmail.py`: `GET /gmail/connect` + `GET /gmail/callback` (scope Gmail, offline,
  `state.purpose=connect`).
- `config.py`: `gmail_redirect_uri`, `gmail_token_enc_key`, `gmail_sync_max_results`; 503 si no
  configurado.
- Scope `gmail:connect` en `auth/scopes.py` (owner + admin).
- Tests: canje de code mockeado, cifrado round-trip, 503 sin config, RBAC.
- **Entregable:** un owner puede conectar su Gmail; el refresh token queda cifrado en DB.

### F2 — Endpoint de sync + bandeja del día *(backend)*
- `services/gmail.py`: `GmailClient.list_today(...)` (refresh de access token, `messages.list`
  + `messages.get`, parse a `TriageRequest`).
- `routers/inbox.py`: `GET /gmail/status`, `POST /gmail/sync` (triage por correo, reusa
  `LLMService`), `DELETE /gmail/connection`.
- Manejo de errores: token revocado → 409 "reconecta"; Gmail 429 → backoff.
- Tests: sync con Gmail API mockeada + `LLMService` override (nunca red real), token revocado,
  bandeja vacía, límite de resultados.
- **Entregable:** `POST /gmail/sync` devuelve los correos de hoy ya triados.

### F3 — UI `/inbox` + estados *(frontend)*
- Ruta `/inbox` protegida en `App.tsx`, entrada en `AppShell`.
- Card de conexión en `Settings` (conectado/desconectado, desconectar).
- Bandeja: lista de correos, fila expandible (cuerpo + borrador + `Copy reply` + `Ver traces`),
  skeleton de carga, empty state celebratorio, banner de reconexión.
- `api.ts`: `gmailStatus`, `gmailSync`, `gmailDisconnect`.
- Gates verdes; verificación visual claro/oscuro con el preview.
- **Entregable:** el usuario conecta, pulsa "Traer correos de hoy" y ve su bandeja triada.

### v2 (fuera de este plan)
Sync automático (Gmail `watch` + Pub/Sub), enviar respuestas (scope de escritura + revisión
humana obligatoria), casillas compartidas por-workspace, otros proveedores.

---

## 8. Riesgos y preguntas abiertas

1. **Verificación de Google (restricted scope):** bloqueante real para escala. v1 = modo
   testing con test users. ¿El objetivo es demo/portfolio o producción pública? (define urgencia
   de la verificación).
2. **Conexión por-usuario vs por-workspace:** recomendado por-usuario en v1.
3. **Persistencia de correos:** recomendado efímero en v1 (privacidad). Si se quiere historial,
   decidir qué se guarda (¿solo metadatos + resultado, nunca el cuerpo?).
4. **Mecanismo de cifrado del refresh token:** Fernet + clave en env es el mínimo razonable;
   ¿rotación de clave? (v2).
5. **Coste de triar N correos por sync:** con `max_results=25` y el modelo actual, acotado;
   monitorear latencia y coste vía Logfire (ya instrumentado).
