# CLAUDE.md — Convenciones técnicas

Referencia técnica para agentes AI trabajando en este repo. Leer antes de editar código.

## Stack

| Componente | Versión | Rol |
|---|---|---|
| Python | 3.14 | Runtime (fijado en `.python-version`) |
| FastAPI | ≥0.136 | Framework, validación, auto-docs |
| Uvicorn | ≥0.48 | ASGI server (dev `--reload`) |
| Gunicorn | TBD (Día 6) | Process manager en producción |
| httpx | ≥0.28 | Cliente HTTP async (LLM Día 2-4) |
| Pydantic AI | TBD (Día 5) | Cliente LLM provider-agnostic |
| pydantic-settings | TBD (Día 4) | Config tipada desde `.env` |
| structlog | TBD (Día 4) | Logs JSON con `request_id` |
| uv | externo | Gestor de paquetes y entornos |
| ruff | --dev | Lint + format |
| pyright | --dev | Type checker (strict) |
| pre-commit | --dev | Hooks locales |

## Estructura objetivo

```
email-triage/
├── src/email_triage/        # Paquete principal
│   ├── main.py              # FastAPI app + lifespan
│   ├── config.py            # Settings (pydantic-settings)
│   ├── schemas.py           # TriageRequest, TriageResponse, Category
│   ├── deps.py              # Dependencias inyectables (api key, llm)
│   ├── middleware.py        # request_id + timing + structlog
│   ├── services/            # Lógica de negocio
│   │   └── llm.py           # LLMService (Groq vía httpx → Pydantic AI)
│   └── routers/             # Endpoints agrupados por dominio
│       ├── health.py
│       └── triage.py
├── tests/                   # pytest async, sin red real
├── docs/                    # ver AGENTS.md
├── Dockerfile               # multi-stage uv (Día 6)
├── gunicorn.conf.py         # (Día 6)
└── pyproject.toml           # deps + ruff + pyright config
```

**Estado al Día 1:** layout flat (`main.py` en raíz). Se migra a `src/` en Tarea #1.

## Tests

Se establece formalmente Día 5. Convenciones:

- `pytest` + `pytest-asyncio` con `asyncio_mode = "auto"` (en `pyproject.toml`).
- Tests **nunca** llaman a Groq. La dependencia `get_llm_service` se sobreescribe con un mock vía `app.dependency_overrides`.
- Comandos:
  - `uv run pytest` — toda la suite
  - `uv run pytest tests/test_triage.py -v`

## Calidad de código

- Formato: `uv run ruff format`
- Lint: `uv run ruff check --fix`
- Types: `uv run pyright`
- Hooks: `uv run pre-commit run --all-files`

Pre-commit corre ruff + pyright. Si falla, arreglar el código — **no** usar `--no-verify`.

## Patrones acordados

Algunos aún no están implementados pero ya son contrato. Respetarlos al agregar código.

### 1. Pydantic como single source of truth
- **Qué:** cada payload de entrada/salida es un modelo Pydantic.
- **Dónde:** `src/email_triage/schemas.py` (desde Día 2).
- **Por qué:** FastAPI los usa para validación + serialización + docs simultáneamente.

### 2. Dependency injection para servicios externos
- **Qué:** `LLMService`, `Settings`, etc. se inyectan vía `Depends()`, no se instancian dentro del handler.
- **Dónde:** `src/email_triage/deps.py` (Día 4).
- **Por qué:** en tests se reemplaza con `app.dependency_overrides` sin monkeypatching.

### 3. Async por defecto en el critical path
- **Qué:** handlers que tocan red son `async def`. Sync solo si la op es CPU-bound trivial.
- **Dónde:** todo handler que llame `LLMService`.
- **Por qué:** cada request espera 1-3s a Groq. Sync bloquea el worker — diferencia entre 5 y 500 concurrent.

### 4. Errores con código HTTP correcto
- **Qué:** `try/except` alrededor de calls a LLM. Levantar `HTTPException` con status semántico (503 si Groq cae, 422 si el output del LLM no valida, 403 si falta API key).
- **Dónde:** handlers de `routers/triage.py`.
- **Por qué:** el caller (Zapier/Make) necesita códigos correctos para reintentar.

### 5. Logging estructurado con request_id
- **Qué:** middleware genera `request_id` por request. Todos los logs lo incluyen. `structlog` en formato JSON.
- **Dónde:** `src/email_triage/middleware.py` (Día 4).
- **Por qué:** debug en producción sin pegar grep a stdout.

## Performance — critical path

`POST /triage` → Groq → respuesta. Decisiones que dependen de esto:

- **Cliente `httpx.AsyncClient` compartido** vía lifespan (Día 6), no uno por request.
- **Workers:** `(2 × cores) + 1` con `UvicornWorker` debajo de Gunicorn.
- **Streaming** (`POST /triage/stream`) para que el caller no espere generación completa.

## Límites del agente

- **NO commitear**: el humano hace los commits. Nunca correr `git commit`, `git push`, `git amend`.
- **NO llamar a Groq desde tests**: usar dependency override.
- **NO inventar categorías**: las cuatro son `billing`, `refund`, `general`, `urgent`. Cambiarlas requiere actualizar este archivo + `schemas.py` + `docs/features/`.
- **NO usar `--no-verify`**: si pre-commit falla, fijar el código.
- **NO agregar features fuera del scope** del exec plan activo sin discutir con el humano primero.
- **NO alucinar valores**: si un secreto o variable de entorno no está disponible, avisar y detenerse.
