# Check-in Semana 2 — Triage Studio

Prep para responder sobre: *"Add dependency injection, typed schemas, AI evaluation tests, and AI-assisted code review to Triage Studio."* Incluyo también los otros dos entregables de la fila (README, deploy + demo) porque el pass condition ("merged, deployed, demo-ready") los junta.

## Estado real, con evidencia

**Dependency injection — hecho, y más maduro que lo pedido.** `email_triage/deps.py` no es un DI básico: tiene `SettingsDep`/`TenantDep` para API keys con cache TTL, `CurrentUserDep`/`ManageWorkspaceDep` para sesión JWT + scopes, y `require_scope()` como factory que genera dependencias de RBAC por workspace (`WorkspaceMemberDep`, `ConfigureTriageDep`, `PublishPromptDep`, etc.). También hay DI para el servicio de LLM: `get_triage_service()` resuelve el prompt activo o el draft compilado por tenant, con fallback seguro al servicio legacy si la DB falla. Esto es DI aplicado a multi-tenancy real, no solo a "inyectar el cliente de Groq".

**Typed schemas — hecho.** `schemas.py` tiene Pydantic en cada payload: el legacy (`Category` StrEnum congelado, `TriageRequest`/`TriageResponse`), la versión dinámica para taxonomías por workspace (`DynamicTriageResponse` con `category: str`), y modelos para features más nuevas (diagnóstico de trazas, tuning copilot, reporte de voz). Vale la pena mencionar en la reunión el patrón "legacy vs dynamic": el enum congelado sigue siendo el contrato para el fallback y los evals offline; el path multi-tenant usa `str` porque las categorías son filas de DB por workspace, y el `allowed_slugs` compilado en el prompt hace de validación blanda.

**AI evaluation tests — hecho, y es la pieza más fuerte para mostrar.** No es solo pytest con mocks: hay un paquete `evals/` completo sobre `pydantic-evals` con dos suites (regression: 25 casos balanceados por categoría, gate de publish; capability: 22 casos, tendencia), LLM-as-judge con manejo explícito de "unknown" (no infla el promedio si el juez no pudo evaluar), `pass^k` para detectar flakiness corriendo cada caso k veces, y exportación de muestras para calibración humana. `tests/test_evals.py` (310 líneas) prueba ese arnés end-to-end sin llamar a Groq (task + juez mockeados). Comandos: `make eval-quick`, `make eval`, `make eval-regression` (gate), `make eval-passk K=5`.

**AI-assisted code review — este es el punto flojo. Sé honesto en la reunión.** No encontré una práctica formalizada: no hay GitHub Action ni hook que corra una revisión con Claude sobre cada PR. Lo que sí existe es el contrato humano-agente en `AGENTS.md` (el agente implementa y corre tests/tipos, el humano aprueba y hace el merge) y comandos slash en `.claude/commands/` para flujos de Triage Studio (`/add-example`, `/eval-prompt`, `/new-category`, `/preview-prompt`) — pero ninguno es "revisar un diff antes de mergear". Dos caminos honestos para la reunión: (a) contarlo como ya lo haces hoy — pides a Claude Code que revise el diff antes de aprobar el merge, aunque no esté como step de CI — o (b) cerrar el gap antes del check-in agregando un `/code-review` (slash command) o un hook de pre-commit/pre-push que invoque revisión. Si quieres, lo armamos ahora mismo.

**README — desactualizado respecto al alcance real.** Hoy describe solo el producto legacy (5 categorías fijas, 3 endpoints). No menciona la arquitectura multi-tenant de Triage Studio (RBAC, taxonomías por workspace, prompt compiler, evals-gate, MCP server) ni conecta con valor de negocio. El pass condition de la semana pide explícitamente explicar arquitectura + trade-offs + valor de negocio — esto falta y es rápido de cerrar (ya tienes el material en `docs/proposals/001-triage-studio.md` y los exec-plans 24–28).

**Deploy — sí está armado, no solo documentado.** `.fastapicloud/cloud.json` tiene `app_id` y `team_id` reales, y `docs/DEPLOY.md` es un runbook ejecutable (Neon → FastAPI Cloud → Vercel, con checks de CORS en cada fase). Confirma en el momento que el health check responde en la URL pública antes de la reunión — es el único paso que no puedo verificar desde el código.

**Demo sin notas — hay una pieza a favor.** `docs/features/35-landing-live-demo.md` describe un demo reel autoplay en el landing (inbox auto-triado, trace-debugging, sync vs streaming, alta de categoría). Sirve como respaldo visual, pero el pass condition pide que *vos* demos sin notas — practica el flujo real (crear categoría → agregar ejemplo → preview prompt → publish → triage) antes del check-in, no solo mostrar el reel.

## Cómo contarlo (guión corto, con negocio)

Abre con el marco, no con la lista de tareas: "Convertí el clasificador de 5 categorías fijas en una plataforma multi-tenant configurable — cada workspace define su propia taxonomía, prompt y ejemplos, con gobernanza de por medio." Después baja a los 4 pilares en este orden, cerrando cada uno con la razón de negocio:

1. DI → "separar la identidad/tenant de la lógica de negocio significa que un cliente nuevo no toca código, solo agrega filas" — reduce costo de onboarding.
2. Typed schemas → "el contrato Pydantic es lo que me deja mezclar clientes legacy y dinámicos sin romper el output" — menos incidentes en producción.
3. Evals → "antes de publicar un prompt nuevo, el sistema lo corre contra 47 casos etiquetados y bloquea el publish si regresa" — esto es lo que evita que un cliente reciba peor clasificación sin que nadie se entere.
4. Code review con IA → sé honesto sobre el estado real (ver arriba) y preséntalo como práctica de trabajo, no como feature del producto.

Cierra con una cifra o proxy, aunque sea aproximado: cuántos casos cubre el eval set, cuánto tarda `eval-quick` (~30s), o el ahorro de tiempo de triage manual que mencionaba la propuesta original.

## Preguntas probables y respuesta corta

**"¿Esto lo hiciste esta semana o ya existía?"** — Responde con precisión: la base de Triage Studio (DI, schemas, evals) viene de exec-plans anteriores (24–28); lo nuevo de esta semana es [ajusta según lo que realmente tocaste estos días — revisa `git log` y `git status` antes de la reunión, hay cambios sin commitear en `main.py`, `observability.py`, `schemas.py`, `trace_agent.py`].

**"¿Cómo sabés que el eval gate funciona?"** — `make eval-regression` corre las 25 casos balanceados y sale con código no-cero si no pasa el umbral; `passes_gate()` además bloquea un "pase vacío" si demasiados casos erraron (no solo mira accuracy).

**"¿Y la revisión de código con IA?"** — No la tengo como paso de CI todavía; hoy es una práctica manual con Claude Code antes de aprobar el merge. Es el ítem que voy a formalizar [decide antes de la reunión si lo cierras o lo dejas como próximo paso explícito].

**"Demostralo sin notas."** — Ensaya el flujo real en la app (no solo el reel del landing): crear categoría → agregar ejemplo → preview del prompt compilado → publish → `POST /triage` mostrando el resultado.

## Antes del check-in

Revisa `git log`/`git status` para saber con precisión qué es de esta semana (hay cambios locales sin commitear en `main.py`, `observability.py`, `routers/traces.py`, `schemas.py`, `services/trace_agent.py`, y archivos nuevos como `routers/reports.py`, `routers/tuning.py`, `services/agent_telemetry.py`, `services/tuning.py`, `services/voice_report.py` — no están claros de qué plan son). Decide y cierra el gap de "AI-assisted code review" (o al menos ten lista la respuesta honesta). Actualiza el README con arquitectura + valor de negocio. Verifica el health check en la URL pública real. Practica el demo end-to-end sin mirar la pantalla de código.
