# Propuesta 003 — Audit trail + detección de anomalías: la otra mitad de la estrategia

> **Estado:** Draft para discusión
> **Autor:** Sebastián + agente
> **Fecha:** 2026-08-17
> **Objetivo estratégico:** cerrar la brecha entre *prevención* y *detección*. Hoy Triage Studio
> tiene RBAC sólido (quién **puede** hacer qué), pero no sabe **qué se hizo realmente**: quién
> tocó la config, quién exportó cuántos correos, cuándo y desde dónde. Prevención sin detección
> es media estrategia.

---

## 0. La lección (por qué esto, por qué ahora)

> *"El breach de Snowflake es el ejemplo más claro de qué pasa cuando la autenticación es débil
> y el monitoreo está ausente. Aunque tu RBAC sea sólido, necesitas saber quién consultó qué,
> cuándo y cuánto."*

RBAC es una barrera **a priori**: reduce la superficie decidiendo permisos. Pero una credencial
válida filtrada (phishing, token robado, API key en un repo) entra **con permisos legítimos** —
el RBAC la saluda y la deja pasar. Lo único que salva en ese punto es **notar el comportamiento
anómalo**: una cuenta que de repente hace `SELECT *` a las 3 AM, o un service account exportando
10× su volumen normal. Y para notarlo hace falta, primero, **registrarlo**.

Esta propuesta añade las dos capas que faltan, en este orden:

1. **Audit trail** (registrar) — un rastro append-only de las acciones sensibles del plano de
   control: *quién / qué / cuándo / desde dónde*.
2. **Detección de anomalías + alerting** (notar) — líneas base por actor/workspace sobre el
   plano de datos, con reglas que disparan alertas **en tiempo casi real**, no "semanas después
   en un artículo".

---

## 1. Resumen ejecutivo

La buena noticia: **casi todo el substrato ya existe**, esta feature es sobre todo *conectarlo y
consultarlo*, no construir infra nueva.

| Pieza que ya existe | Dónde | Qué aporta a esta feature |
|---|---|---|
| Identidad del actor | `deps.py` → `SessionContext` / `WorkspaceContext` (`user_id`, `role`, `tenant_id`) | El *quién* de cada acción, ya resuelto por `require_scope`. |
| RBAC / scopes | [auth/scopes.py](../../email_triage/auth/scopes.py) | Define qué acciones son sensibles → qué eventos auditar. |
| `request_id` + `trace_id` | [middleware.py](../../email_triage/middleware.py) | Correlación de cada evento con su request y su traza. |
| Telemetría del plano de datos | `TriageLog` (chars, categoría, latencia, `tenant_id`) + Logfire con `tenant_id` propagado por baggage (Plan 33) | El *cuánto* y el *cuándo* para las líneas base. |
| Query API de Logfire | `LogfireTraceClient` / `LogfireQueryApiClient` ([services/trace_agent.py](../../email_triage/services/trace_agent.py)) | Motor de consulta ya envuelto y aislado por tenant para calcular anomalías. |
| Dispatch post-request no-bloqueante | [evals_online.py](../../email_triage/evals_online.py) | Precedente de cómo correr trabajo (detección) fuera del camino crítico. |
| Métricas de seguridad | `auth_failures_total`, `rate_limit_hits_total` ([observability.py](../../email_triage/observability.py)) | Señales de fuerza bruta / abuso ya emitidas. |

**La brecha real:** los rastros de autoría hoy están **dispersos y mudos** — columnas
`created_by` / `updated_by` / `published_by` en `triage_examples`, `prompt_templates` y
`prompt_versions`, sin nadie que las consulte, sin IP/user-agent, sin cubrir *lecturas*, *auth
failures*, *conexión de Gmail* ni *cambios de rol*. No hay una tabla append-only ni un panel.

Esta propuesta introduce: **(a)** una tabla `audit_events` inmutable + un `AuditService`
cableado en las acciones sensibles, espejada a Logfire; **(b)** un motor de **detección por
reglas** sobre líneas base por actor/workspace; **(c)** **alerting** a Logfire + webhook
opcional; y **(d)** un panel `/audit` role-gated. Sin tocar el motor de triage.

---

## 2. Perspectiva de producto (PM)

### 2.1 Problema y valor

Un workspace de Triage Studio procesa correos de clientes (potencialmente PII). Si una API key
se filtra o un miembro se vuelve malicioso, hoy **no hay forma de saberlo ni de reconstruir qué
pasó**. Para cualquier comprador con requisitos mínimos de compliance (SOC 2, ISO 27001, un
cuestionario de seguridad de vendor), la pregunta *"¿tienen audit logs de acceso a datos?"* es
un gate binario. Hoy la respuesta es "no". Esta feature la vuelve "sí".

Valor en tres frentes:

- **Seguridad:** detectar el abuso mientras ocurre, no post-mortem.
- **Confianza / ventas:** desbloquea la conversación con clientes que exigen trazabilidad.
- **Operación:** un rastro para responder "¿quién cambió este prompt y rompió el triage?".

### 2.2 Jobs To Be Done

> *"Cuando reviso la seguridad de mi workspace, quiero ver quién accedió o cambió qué y cuándo,
> para poder responder a un incidente o a un auditor sin adivinar."*

> *"Cuando una cuenta se comporta raro (volumen o horario fuera de lo normal), quiero enterarme
> al momento, para cortar antes de que se convierta en un breach."*

### 2.3 Personas

| Persona | Necesidad | Rol (RBAC) |
|---|---|---|
| **Owner de workspace** | Ver el rastro completo, recibir alertas, responder a auditores | `owner` |
| **Admin** | Revisar actividad, triage de alertas | `admin` |
| **Miembro** | (sin acceso al audit trail — es dato de seguridad) | `member` (excluido) |
| **Auditor / comprador** (externo, vía el owner) | Evidencia de trazabilidad | — |

### 2.4 Alcance

**Dentro (v1):**
- Tabla `audit_events` **append-only** e inmutable, tenant-scoped.
- `AuditService.record(...)` cableado en las acciones sensibles del plano de control
  (config de categorías/ejemplos/prompt, publish/rollback, conexión/desconexión de Gmail,
  cambios de rol, rotación de API key, auth failures).
- Panel `/audit`: timeline filtrable por actor / acción / rango de fechas, role-gated
  (`owner` + `admin`).
- **Detección por reglas** sobre líneas base por actor/workspace (volumen, horario, ráfagas de
  auth-failure, volumen de export/sync). Corre fuera del camino crítico.
- **Alertas** a Logfire (alerta nativa) + **webhook opcional** (Slack/email); visibles en un
  banner/inbox del Dashboard.

**Fuera (v2+):**
- **Agente investigador de anomalías** en lenguaje natural (reusa la infra del Trace-Diagnosis
  agent, Plan 43): *"muéstrame la actividad rara de esta semana"*.
- Detección con ML / baselines aprendidos (v1 es **umbrales + estadística simple**, a propósito).
- Inmutabilidad a nivel storage (WORM / grants de DB `REVOKE UPDATE,DELETE`, tabla append-only
  con trigger).
- Export a SIEM (Datadog / Splunk) y retención larga/archivado a cold storage.
- Canales de alerta configurables por workspace desde la UI.

### 2.5 Principio de scope (anti over-engineering)

v1 es **deliberadamente rule-based y de bajo costo**. Nada de ML, nada de streaming de detección.
Reusa Logfire y `TriageLog` en vez de montar un pipeline de eventos nuevo. El objetivo es
**cerrar la brecha de detección con lo mínimo defendible**, dejando el agente y el ML como v2
justificado por uso real.

### 2.6 Métricas de éxito

- **Cobertura de auditoría:** % de acciones sensibles que emiten un `audit_event` (meta: 100%).
- **Time-to-detect:** minutos desde una anomalía sintética inyectada hasta la alerta.
- **Señal/ruido:** ratio de alertas accionables vs falsos positivos (ajustar umbrales).
- **Compliance-readiness:** poder responder "sí" con evidencia al cuestionario de vendor.

---

## 3. Perspectiva de experiencia (UX)

Reutiliza el design system teal/ámbar unificado (Plan 34): `AppShell`, `Card`, `Tag`, `Button`,
tema claro/oscuro.

### 3.1 Panel de auditoría (`/audit`, protegido, owner+admin)

- **Timeline** de eventos, fila por evento: `actor` · `acción` · `recurso` · `hora` · `IP`.
  - `Tag` por tipo de acción (config = ámbar, auth-fail = rojo, publish = teal, gmail = azul).
  - Fila expandible → metadata de bajo cardinal (antes/después de un cambio de rol, `request_id`
    y `trace_id` con enlace al Trace-Debug chat existente).
- **Filtros:** por actor, por tipo de acción, por rango de fechas. Paginado (cursor por `created_at`).
- **Empty state:** *"Sin actividad registrada en este rango"*.

### 3.2 Alertas (banner + inbox en el Dashboard)

- **Banner** cuando hay alertas abiertas: *"⚠️ 2 alertas de seguridad — revisar"*.
- Cada alerta: qué regla disparó, actor implicado, evidencia (p. ej. "142 syncs en 10 min,
  baseline ~6/h"), y un enlace al panel de auditoría filtrado por ese actor.
- Acciones: `Marcar como revisada` / `Ver actividad del actor`.

### 3.3 Principios

1. **Transparencia sin ruido:** el audit trail es completo; las *alertas* son curadas (solo lo
   accionable sube al Dashboard).
2. **De la alerta a la evidencia en un clic:** cada alerta enlaza al rastro que la originó y a la
   traza en Logfire.
3. **Solo lectura para el usuario:** nadie edita ni borra el audit trail desde la UI — es la
   propiedad que lo hace confiable.

---

## 4. Mapa a los dominios de la certificación

Igual que la 001 y la 002, esta feature ejercita dominios del *Claude Certified Architect*:

| Dominio | Cómo lo expone esta feature |
|---|---|
| **Context Management & Reliability** | Rastro append-only + degradación con feature-flag (sin sink de alertas → solo registra); detección fuera del camino crítico (patrón `evals_online`). |
| **Observability & Evaluation** | Detección de anomalías **sobre la telemetría existente** (Logfire Query API, `tenant_id` baggage); líneas base y reglas como "evaluadores online" de seguridad. |
| **Tool Design & MCP Integration** *(v2)* | El agente investigador reusa `LogfireTraceClient` con tools curadas y `WHERE tenant_id` fijado por el server — mismo aislamiento estructural que el Trace-Debug chat (Plan 31). |
| **Prompt Engineering & Structured Output** *(v2)* | El agente investigador emite hallazgos como output tipado (regla, actor, evidencia, severidad). |

---

## 5. Seguridad y privacidad

- **Append-only por diseño.** `AuditService` solo hace `INSERT`. Sin `UPDATE`/`DELETE` en el
  código. v2 lo endurece a nivel DB (`REVOKE UPDATE, DELETE` para el rol de la app, o trigger
  que rechaza mutaciones) para que ni un bug ni un atacante con acceso a la DB borren su rastro.
- **Sin contenido de correo, sin PII.** El audit trail registra **metadata**, no cuerpos: actor,
  acción, tipo+id de recurso, IP, user-agent, `request_id`/`trace_id`, y un JSON de metadata de
  **bajo cardinal** (p. ej. `{"role_from":"member","role_to":"admin"}`). Misma disciplina que ya
  gobierna `TriageLog` (chars, no contenido) y las labels de OTel (bajo cardinal, sin free-text).
- **El audit trail es dato sensible.** Se lee con un scope nuevo `audit:read` (owner + admin);
  los miembros quedan excluidos, igual que `traces:read`.
- **IP y user-agent = dato personal.** Se guardan por necesidad de seguridad, con retención
  acotada (config, default p. ej. 180 días) y declarados en la política de privacidad.
- **El sink de alertas no filtra secretos.** El webhook (Slack/email) manda el *hecho* de la
  anomalía y el enlace al panel — nunca contenido de correos ni tokens.
- **La detección respeta el aislamiento multi-tenant** ya establecido (Plan 33): toda consulta a
  Logfire lleva `WHERE tenant_id`, el read token vive solo en el backend.

---

## 6. Mapa técnico

Sin reescribir el motor de triage. Piezas nuevas, todas aditivas.

### 6.1 Plano de control — Audit trail

- **Modelo / migración** (`0007_audit_events`): tabla `audit_events` inmutable.

  | Columna | Tipo | Nota |
  |---|---|---|
  | `id` | UUID PK | |
  | `tenant_id` | UUID FK → tenants, `ondelete=CASCADE`, index | scope multi-tenant |
  | `actor_type` | String(20) | `user` \| `api_key` \| `system` |
  | `actor_user_id` | UUID FK → users, nullable | null si `api_key`/`system` |
  | `action` | String(50), index | enum-string, p. ej. `category.update`, `prompt.publish`, `gmail.connect`, `role.change`, `auth.failure`, `apikey.rotate` |
  | `resource_type` | String(50), nullable | `category` \| `prompt_version` \| `membership` … |
  | `resource_id` | String(255), nullable | id del recurso afectado |
  | `ip` | String(45), nullable | IPv4/IPv6 |
  | `user_agent` | Text, nullable | |
  | `request_id` | String(255), nullable | correlación con middleware |
  | `trace_id` | String(32), nullable | enlace a Logfire |
  | `metadata_json` | Text (JSON), nullable | bajo cardinal, sin PII |
  | `created_at` | DateTime(tz), `server_default=now()`, index | |

  Índices: `(tenant_id, created_at)` para el timeline paginado; `(tenant_id, action)` y
  `(tenant_id, actor_user_id)` para filtros y baselines.

- **Servicio** (`services/audit.py`): `AuditService.record(session, ctx, action, *,
  resource_type=None, resource_id=None, metadata=None)`. Toma el actor/IP/UA de la request y el
  `SessionContext`/`WorkspaceContext` (o el tenant de la API key), inserta la fila **y** emite un
  `logfire.info("audit", action=..., tenant_id=..., actor=...)` para tener la vista SIEM en
  Logfire además de la consultable en DB. Nunca lanza excepción que rompa la acción de negocio
  (best-effort + log de error, como los evaluadores online).

- **Cableado** (rutas que ya existen): invocar `AuditService.record(...)` en las mutaciones
  sensibles de `routers/categories.py`, `routers/prompt_studio.py` (publish/rollback),
  `routers/gmail.py` (connect/disconnect), `routers/workspaces.py` (cambios de rol / invitaciones),
  y en el fallo de auth de `auth/api_key.py` (`auth.failure`, reusando `auth_failures_total`).

- **RBAC** ([auth/scopes.py](../../email_triage/auth/scopes.py)): nuevo scope **`audit:read`**
  (owner + admin), en la línea de `traces:read`.

- **Endpoint** (`routers/audit.py`): `GET /workspaces/{tid}/audit` (scope `audit:read`) con
  filtros `?actor=&action=&since=&until=&cursor=&limit=` → lista paginada. Feature-flag implícito:
  la tabla siempre registra; el panel solo aparece si el workspace tiene el scope.

### 6.2 Plano de datos — Detección de anomalías

- **Reglas v1** (puras, umbral + estadística simple), computadas por actor/workspace:

  | Regla | Señal | Fuente |
  |---|---|---|
  | **Spike de volumen** | requests/hora ≫ baseline (p. ej. > media + 3σ, o > 10× la mediana) | `TriageLog` / Logfire por `tenant_id` |
  | **Actividad fuera de horario** | actividad en ventana histórica "muerta" del workspace | `TriageLog.created_at` |
  | **Ráfaga de auth-failure** | N fallos de API key en M minutos (fuerza bruta) | `auth_failures_total` / `audit_events(auth.failure)` |
  | **Volumen de export/sync anómalo** | `POST /gmail/sync` o lecturas ≫ baseline del actor | `audit_events` / Logfire |
  | **IP nueva para un actor** | primera vez que un actor aparece desde una IP | `audit_events.ip` |

- **Motor** (`services/detection.py`): funciones puras `rule(ctx, window) -> Alert | None` sobre
  agregados. Se alimenta de dos fuentes intercambiables tras una interfaz (igual que
  `LogfireTraceClient`): (a) consultas SQL agregadas a `TriageLog`/`audit_events` (barato, sin
  red externa, ideal para tests) o (b) el `LogfireQueryApiClient` para ventanas más ricas.

- **Ejecución** (fuera del camino crítico): un job periódico (p. ej. cada 5–15 min) — arrancable
  con el mecanismo de tareas programadas del entorno o un `RemoteTrigger`/cron — que corre las
  reglas por tenant y **materializa las alertas como `audit_events` de acción `alert.<regla>`**
  (una alerta *es* un evento auditable, cero tablas nuevas para v1). Alternativa de menor latencia:
  disparar reglas baratas post-request con el patrón `evals_online` (dispatch async, sampled).

- **Alerting** (`services/alerting.py`): al materializar una alerta →
  (1) `logfire.error("security.alert", ...)` para aprovechar **las alertas nativas de Logfire**;
  (2) webhook opcional (`ALERT_WEBHOOK_URL`, Slack/email) — feature-flag: sin URL, solo Logfire+DB.

- **Endpoint** (`routers/audit.py`): `GET /workspaces/{tid}/alerts` (scope `audit:read`) →
  alertas abiertas; `POST .../alerts/{id}/ack` para marcarlas revisadas (un `audit_event`
  `alert.ack` con el actor que la revisó — el rastro se audita a sí mismo).

### 6.3 Frontend

- Ruta `/audit` protegida en `App.tsx`, entrada en `AppShell` (visible solo con `audit:read`).
- Componente timeline + filtros; banner de alertas en `Dashboard`; métodos nuevos en
  [api.ts](../../frontend/src/api.ts) (`auditList`, `alertsList`, `alertAck`).
- Reusa el enlace al **Trace-Debug chat** desde cada evento con `trace_id`.

---

## 7. Plan de implementación por fases (exec-plans)

Convención del repo: cada fase deja los gates verdes (`ruff` + `pyright` + `pytest`; frontend
`tsc` + `eslint` + `vite build`). El humano hace los commits.

### F1 — Audit trail: tabla + servicio + cableado *(backend)*
- Migración `0007_audit_events` + modelo `AuditEvent` en `db/models.py` + repo
  `db/repos/audit.py`.
- `services/audit.py`: `AuditService.record(...)` (INSERT + espejo a Logfire, best-effort).
- Cablear en las mutaciones sensibles existentes (categories, prompt publish/rollback, gmail
  connect/disconnect, cambios de rol, auth.failure).
- Scope `audit:read` en `auth/scopes.py` (owner + admin).
- Tests: cada acción sensible emite el evento correcto; `record` nunca rompe la acción de
  negocio; RBAC del scope; append-only (sin rutas de update/delete).
- **Entregable:** cada acción sensible deja un rastro inmutable con actor/IP/timestamp.

### F2 — Endpoint + panel de auditoría *(backend + frontend)*
- `routers/audit.py`: `GET /workspaces/{tid}/audit` filtrable y paginado.
- Frontend `/audit`: timeline, filtros, fila expandible, enlace a Trace-Debug.
- Tests backend (filtros, paginación, aislamiento por tenant, RBAC); verificación visual
  claro/oscuro con el preview.
- **Entregable:** owner/admin ven y filtran el rastro completo de su workspace.

### F3 — Detección por reglas + alerting *(backend)*
- `services/detection.py` (reglas puras sobre agregados) + `services/alerting.py` (Logfire +
  webhook opcional, feature-flagged).
- Job periódico que corre las reglas por tenant y materializa alertas como `audit_events`
  `alert.<regla>`; `GET /alerts` + `POST /alerts/{id}/ack`.
- Config: umbrales, ventana, `ALERT_WEBHOOK_URL`, retención.
- Tests: inyectar volúmenes/horarios/ráfagas sintéticas → la regla dispara; sin webhook → solo
  Logfire+DB; ack registra su propio evento.
- **Entregable:** una anomalía sintética (spike, off-hours, brute-force) genera una alerta
  visible y notificada.

### F4 — Alertas en la UI *(frontend)*
- Banner + inbox de alertas en `Dashboard`; de la alerta al actor/traza en un clic; `alertAck`.
- Gates verdes; verificación visual claro/oscuro.
- **Entregable:** el owner ve y triagea alertas sin salir de la app.

### v2 (fuera de este plan)
- **Agente investigador de anomalías** (reusa `LogfireTraceClient` + tools curadas, patrón Plan 43).
- Inmutabilidad a nivel storage (grants/trigger WORM), export a SIEM, retención larga.
- Baselines aprendidos (estacionalidad) en vez de umbrales fijos.
- Canales de alerta configurables por workspace desde la UI.

---

## 8. Riesgos y preguntas abiertas

1. **Falsos positivos:** umbrales fijos generan ruido (un cliente con un pico legítimo de correos).
   Mitigación: baselines por-actor, ventana de calentamiento antes de alertar, y `ack` para
   silenciar. ¿Umbrales globales o por-workspace en v1?
2. **Retención de IP/UA (privacidad):** son dato personal. Propuesta: 180 días configurable +
   declaración en la política. ¿Ese plazo sirve para el objetivo de compliance buscado?
3. **Mecanismo del job periódico:** ¿tarea programada del entorno, cron externo, o dispatch
   post-request tipo `evals_online`? Trade-off latencia-de-detección vs simplicidad. Recomendado:
   dispatch barato post-request para brute-force + job de 5–15 min para volúmenes.
4. **Inmutabilidad real:** v1 es append-only *por convención de código*. ¿Se necesita la garantía
   a nivel DB (grants/trigger) ya en v1, o basta como v2? Depende de la exigencia del comprador.
5. **Costo de la detección sobre Logfire:** las consultas agregadas tienen costo/latencia.
   Preferir agregados sobre `TriageLog`/`audit_events` en DB local cuando alcancen, y Logfire solo
   para ventanas ricas. Monitorear (ya instrumentado).
6. **¿Alertas por email reusan el sender existente?** Si no hay uno, el webhook a Slack es el
   sink de menor scope para v1.
