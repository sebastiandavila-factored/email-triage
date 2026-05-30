# AGENTS.md — Mapa del proyecto y contrato de colaboración

Orienta a agentes AI: dónde está cada cosa, cómo trabajar con el humano, qué documentar.

## 1. Mapa de documentación

| Qué buscás | Dónde está |
|---|---|
| Convenciones técnicas (stack, patrones, límites del agente) | [CLAUDE.md](CLAUDE.md) |
| Plan de implementación día por día | [docs/exec-plans/01-mvp-email-triage.md](docs/exec-plans/01-mvp-email-triage.md) |
| Walkthroughs por feature | [docs/features/](docs/features/) |
| Protocolos de testing manual | [docs/testing/](docs/testing/) |
| Quickstart y endpoints públicos | [README.md](README.md) |

## 2. Mapa de código — quién posee qué

| Dominio | Archivos clave | Leer antes de tocar |
|---|---|---|
| App entrypoint | `src/email_triage/main.py` | CLAUDE.md §Estructura · exec-plans/01 §Día 1 y 6 |
| Schemas (request/response) | `src/email_triage/schemas.py` | CLAUDE.md §Patrones #1 · exec-plans/01 §Día 2 |
| LLM provider | `src/email_triage/services/llm.py` | CLAUDE.md §Patrones #3 · exec-plans/01 §Día 2 y 5 |
| Endpoints | `src/email_triage/routers/triage.py`, `routers/health.py` | CLAUDE.md §Patrones #4 · exec-plans/01 §Día 3 |
| Config | `src/email_triage/config.py` | exec-plans/01 §Día 4 |
| Auth (API key) | `src/email_triage/deps.py` | CLAUDE.md §Patrones #2 · exec-plans/01 §Día 4 |
| Middleware (logging) | `src/email_triage/middleware.py` | CLAUDE.md §Patrones #5 · exec-plans/01 §Día 4 |
| Tests | `tests/` | CLAUDE.md §Tests · exec-plans/01 §Día 5 |
| Deploy | `Dockerfile`, `gunicorn.conf.py` | exec-plans/01 §Día 6 y 7 |

**Día 1:** la mayoría de estos archivos aún no existen. Crear según el plan.

## 3. Workflow de desarrollo y validación

**Roles:**

- **Humano (Arquitecto):** define intención, aprueba merges, hace los commits, valida UX siguiendo `docs/testing/`.
- **Agente (Ejecutor):** lee docs antes de editar, implementa, corre tests automatizados, documenta. **Nunca** hace commits ni push.

**Regla:** el agente valida en teoría (tests + types). El humano valida en la práctica (UX, edge cases reales). Si el agente se bloquea (link inaccesible, dependencia rota, ambigüedad), debe avisar y **no alucinar valores**.

**Ciclo por feature:**

1. **PLAN** — Si la feature toca ≥3 archivos, introduce dependencia nueva o cambia un patrón, escribir/actualizar `docs/exec-plans/NN-feature.md` antes de codear.
2. **IMPLEMENTAR** — Branch nueva. Tests automatizados obligatorios (unit + integration con dependency overrides).
3. **DOCUMENTAR** — Crear `docs/features/NN-feature.md` + `docs/testing/NN-feature_testing.md`. Actualizar `CLAUDE.md` si surge un patrón nuevo. Actualizar este archivo si cambia el mapa de código.
4. **EVALUATE** — Humano sigue `docs/testing/NN-feature_testing.md`. Si encuentra blockers o bugs, vuelve a paso 2.
5. **DELIVER** — Humano hace commit, push y PR.

## 4. Protocolo de documentación

Obligatorio al cerrar una feature:

- **Prefijo cronológico:** `01-`, `02-`, etc. en `docs/exec-plans/`, `docs/features/`, `docs/testing/`. El mismo número une los tres por feature (ej. `02-streaming.md` en cada carpeta, `02-streaming_testing.md` en testing).
- **Walkthrough:** copiar `docs/features/TEMPLATE.md` → `docs/features/NN-feature.md`. Llenarlo.
- **Guía de testing:** copiar `docs/testing/TEMPLATE.md` → `docs/testing/NN-feature_testing.md`. Incluir happy path, edge cases preventivos, workarounds si hay blockers técnicos, verificación en logs.
- **Actualizar CLAUDE.md:** solo si la feature establece un patrón nuevo o cambia uno existente.
- **Actualizar AGENTS.md:** solo si cambia el mapa de código (nueva carpeta, nuevo dominio, nuevo archivo "leer antes de tocar").
- **Exec plans:** obligatorios para features ≥3 archivos o cambios de dependencias. No hace falta para fixes triviales.

## 5. Estado actual y próximos pasos

**Existente (Día 1, parcial):**
- `main.py` — FastAPI app con `GET /health` ✅
- `pyproject.toml` con FastAPI, Uvicorn, httpx ✅
- `.env` con `GROQ_API_KEY` (gitignored) ✅
- `.gitignore` ✅
- `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/` ✅ (este commit)

**Pendiente para cerrar Día 1:**
- Migrar a `src/email_triage/` layout
- Crear `.env.example`
- Setup ruff + pyright en `pyproject.toml`
- Setup pre-commit hooks
- Primer commit del Día 1 (lo hace el humano)

**Próximo (Día 2):**
- Schemas Pydantic (`TriageRequest`, `TriageResponse`, `Category`)
- `LLMService` async con httpx contra Groq

Plan completo de 7 días: [docs/exec-plans/01-mvp-email-triage.md](docs/exec-plans/01-mvp-email-triage.md).

## 6. Principios del proyecto

1. **El proposal es la verdad del scope.** No agregar features fuera de los tres endpoints (`/triage`, `/triage/stream`, `/health`) hasta que el MVP esté en producción.
2. **Día corto (<2 hrs) con lectura primero.** Cada día empieza leyendo las docs oficiales de FastAPI asignadas en el plan. Sin esa lectura, no se codea.
3. **Pydantic es el contrato.** Si la forma del dato cambia, cambia el schema primero. El handler solo orquesta.
4. **Dependency injection siempre que toque I/O externo.** Hace los tests triviales y el código más legible.
5. **Errores con código HTTP correcto.** Zapier/Make necesitan 4xx vs 5xx semánticos para reintentar. Nunca devolver 500 con stack trace.
6. **El margen sobre $9/mailbox define decisiones.** Si una dependencia o provider rompe el unit economics, se descarta — por más cool que sea.
7. **El humano commitea.** El agente nunca corre `git commit`, `git push` ni `git amend`.
