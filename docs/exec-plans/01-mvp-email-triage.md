# 01. MVP Email Triage API (7 días)

**Estado:** 🚧 en progreso (Día 1)
**Estimación:** 12.5 hrs total · <2 hrs/día

## Intención

Construir y desplegar el MVP del API descrito en `README.md`: tres endpoints (`/triage`, `/triage/stream`, `/health`), auth por API key, deploy en Render o Railway. Target al final del Día 7: un founder de e-commerce puede abrir `/docs`, pegar un email de muestra y ver un resultado de triage real.

## Alcance

**Incluido:**
- Endpoints `POST /triage`, `POST /triage/stream`, `GET /health`
- Clasificación en 4 categorías (`billing`, `refund`, `general`, `urgent`)
- Draft de respuesta con confidence score
- Auth vía header `X-API-Key`
- Logging estructurado con `request_id`
- Tests automatizados (≥3) con dependency overrides
- Docker multi-stage + Gunicorn + Uvicorn workers
- Deploy con HTTPS

**Fuera (post-MVP):**
- Multi-tenancy real (un mailbox = una API key persistida)
- Persistencia (DB) de resultados
- Webhooks de retorno
- Métricas / observabilidad avanzada
- Rate limiting fino (slowapi opcional en Día 7)

## Plan día por día

Cada día empieza con la lectura asignada de [fastapi.tiangolo.com](https://fastapi.tiangolo.com). Sin esa lectura, no se codea.

### Día 0 — Pre-requisitos (15 min)

- Instalar `uv` (`brew install uv` o `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Crear cuenta en `console.groq.com` y obtener API key

### Día 1 — Skeleton + Tooling (2 hrs)

**Lectura previa:** Python Types Intro · Virtual Environments · First Steps

**Tareas:**
- [x] `uv init`, `uv add fastapi uvicorn httpx`
- [x] `GET /health` funciona en `localhost:8000/docs`
- [x] `.env` con `GROQ_API_KEY`, `.gitignore` configurado
- [x] Contrato agente-humano (`CLAUDE.md`, `AGENTS.md`, `docs/`)
- [ ] Migrar a `src/email_triage/` layout (ajustar `pyproject.toml` con `[tool.hatch.build.targets.wheel]` o `[tool.setuptools.packages.find]`)
- [ ] Crear `.env.example` con keys vacías
- [ ] `uv add --dev ruff pyright pre-commit`
- [ ] Configurar `[tool.ruff]` (E, F, I, UP, B, SIM) y `[tool.pyright]` (strict) en `pyproject.toml`
- [ ] `.pre-commit-config.yaml` con ruff (lint+format) y pyright
- [ ] `uv run pre-commit install`

**Deliverable:** `uv run uvicorn email_triage.main:app --reload` funciona, `/docs` carga, `pre-commit run --all-files` pasa.

### Día 2 — Schemas + LLMService (2 hrs)

**Lectura previa:** Async / await · Request Body · Body Fields · Nested Models

**Tareas:**
- [ ] `src/email_triage/schemas.py`:
  - `Category(StrEnum)` con `billing | refund | general | urgent`
  - `TriageRequest(subject: str, sender: EmailStr, body: str)`
  - `TriageResponse(category: Category, draft_reply: str, confidence: float)` con validación `0 ≤ confidence ≤ 1`
- [ ] `src/email_triage/services/llm.py`:
  - `LLMService` async usando `httpx.AsyncClient`
  - Method `triage(req: TriageRequest) -> TriageResponse`
  - Prompt pidiendo JSON estructurado matching el schema
  - Parsing con `TriageResponse.model_validate_json`
- [ ] Smoke test manual

**Documentar:** `docs/features/02-llm-service.md` + `docs/testing/02-llm-service_testing.md`

### Día 3 — Endpoints + Streaming (2 hrs)

**Lectura previa:** Response Model · Handling Errors · `StreamingResponse` con `text/event-stream`

**Tareas:**
- [ ] `src/email_triage/routers/triage.py`:
  - `POST /triage` → `TriageResponse`
  - `POST /triage/stream` → `StreamingResponse` SSE
  - `try/except` en LLM → `HTTPException(503)`
- [ ] `src/email_triage/routers/health.py`: mover `/health` aquí
- [ ] Registrar routers en `main.py` con `app.include_router(...)`

**Documentar:** `03-triage-endpoint.md`, `04-streaming.md`

### Día 4 — Config + Auth + Middleware (1.5 hrs)

**Lectura previa:** Settings (pydantic-settings) · Dependencies · Security (API Key) · Middleware

**Tareas:**
- [ ] `uv add pydantic-settings structlog`
- [ ] `src/email_triage/config.py`: `Settings(BaseSettings)` con `groq_api_key`, `groq_model`, `api_key`
- [ ] `src/email_triage/deps.py`:
  - `get_settings()` cached con `@lru_cache`
  - `verify_api_key(x_api_key: str = Header(...))` raise 403 si no matchea
  - `get_llm_service()` retorna instancia compartida
- [ ] Aplicar `Depends(verify_api_key)` a `/triage` y `/triage/stream`
- [ ] `src/email_triage/middleware.py`: middleware que genera `request_id`, mide tiempo, loggea con structlog
- [ ] Configurar structlog formato JSON

**Documentar:** `05-auth.md`, `06-logging.md`

### Día 5 — Tests + Background Tasks + Refactor a Pydantic AI (2 hrs)

**Lectura previa:** Testing · Async Tests · Dependency Overrides · Background Tasks

**Tareas:**
- [ ] `uv add --dev pytest pytest-asyncio`
- [ ] `[tool.pytest.ini_options] asyncio_mode = "auto"` en `pyproject.toml`
- [ ] `tests/conftest.py`: fixture `client` con `TestClient`, override de `get_llm_service` con mock
- [ ] `tests/test_health.py`: `GET /health` retorna 200
- [ ] `tests/test_triage.py`:
  - happy path retorna shape correcto
  - sin `X-API-Key` retorna 403
  - mock de Groq down → 503
- [ ] Background task en `/triage`: loggear resultado después de responder
- [ ] **Refactor LLMService a Pydantic AI:**
  - `uv add pydantic-ai-slim[groq]`
  - Reemplazar httpx crudo por `Agent(GroqModel(...), result_type=TriageResponse)`
  - Tests siguen pasando sin cambios (mismo schema)
  - Actualizar CLAUDE.md §Stack con la nueva dependencia

**Documentar:** `07-tests.md`, `08-pydantic-ai-refactor.md`

### Día 6 — Producción (Gunicorn + Docker + Lifespan) (2 hrs)

**Lectura previa:** Run Manually · Server Workers · Docker · Lifespan

**Tareas:**
- [ ] Lifespan handler en `main.py`: crear `httpx.AsyncClient` compartido al startup, cerrar al shutdown
- [ ] `gunicorn.conf.py`: `worker_class = "uvicorn.workers.UvicornWorker"`, `workers = (2*cores)+1`, `timeout = 120`, `bind = "0.0.0.0:8000"`
- [ ] `Dockerfile` multi-stage:
  - Stage 1: `python:3.14-slim` + `uv sync --frozen --no-dev`
  - Stage 2: copy venv, `CMD ["gunicorn", "-c", "gunicorn.conf.py", "email_triage.main:app"]`
- [ ] Healthcheck en Dockerfile

**Documentar:** `09-deploy-config.md`

### Día 7 — Deploy + Polish (1.5 hrs)

**Lectura previa:** Behind a Proxy · Deployment Concepts · Metadata + Docs URLs

**Tareas:**
- [ ] `root_path` en FastAPI config si el provider usa prefijo
- [ ] Título, descripción, versión, contacto en `FastAPI(...)`
- [ ] Deploy a Render o Railway (HTTPS automático)
- [ ] (Opcional) Rate limiting con `slowapi`
- [ ] Verificar `/docs` público funciona
- [ ] **SHIP:** contactar un founder de e-commerce, dar 1 mes gratis

**Documentar:** `10-deploy.md` con URL del API y runbook de rollback

## Decisiones de diseño

| Decisión | Alternativa descartada | Razón |
|---|---|---|
| Groq free tier desde Día 2 | OpenAI / Anthropic desde inicio | Unit economics: $9/mailbox necesita LLM near-zero-cost para validar |
| Pydantic AI en Día 5 | httpx crudo permanente | Provider-agnostic + parsing automático a `TriageResponse` |
| Pydantic AI en Día 5 (no Día 2) | Pydantic AI desde Día 2 | El humano quiere aprender httpx crudo primero; refactor después |
| `src/` layout | Flat (`app/`) | Práctica estándar 2026: previene bugs de import en tests |
| ruff + pyright | mypy + black + isort | Stack moderno; una herramienta para format+lint |
| Pydantic AI vs LangChain | LangChain | Overkill para 1 llamada; LangGraph solo para agentes complejos |
| `StrEnum` para categorías | `Literal[...]` | Mejor serialización en OpenAPI docs |
| Provider abstracto vía env var desde Día 4 | Hardcoded Groq | Switch a Anthropic con una variable cuando haya margen |

## Riesgos / Open questions

- **Python 3.14 + Gunicorn:** 3.14 es muy nuevo. Si Gunicorn da problemas en Día 6, fallback a Python 3.13. Sospechoso #1 si algo rompe.
- **Groq rate limit en free tier:** validar early que aguanta 5 req/s. Si no, considerar Anthropic con créditos iniciales.
- **Streaming + parsing estructurado:** Pydantic AI streamea tokens pero `TriageResponse` solo está completo al final. Probablemente streamear solo `draft_reply` y devolver categoría/confidence en un último evento del stream.
- **Hatch vs setuptools para `src/` layout:** decidir Día 1 según lo que uv recomiende como default.

## Done cuando

- [ ] Los tres endpoints funcionan en producción detrás de HTTPS
- [ ] Auth por API key funciona y los tests lo verifican
- [ ] Tests automatizados pasan sin internet
- [ ] `docs/features/` tiene un walkthrough por feature implementada
- [ ] `docs/testing/` tiene una guía por feature
- [ ] Un founder real probó `/docs` interactivo con un email de muestra
- [ ] Este archivo cambia a estado ✅
