# email-triage

API de triage para email de soporte. Recibe un email crudo (subject/sender/body), lo clasifica en una de cuatro categorías y devuelve un draft de respuesta con confidence score. Pensado para founders de e-commerce que quieren reducir 1-2 hrs/día de triage manual sin pagar Zendesk/Intercom.

## Endpoints

- `POST /triage` — clasificación + draft
- `POST /triage/stream` — mismo input, draft streaming vía SSE
- `GET /health` — liveness check

## Stack

- Python 3.14, FastAPI + Uvicorn (dev), Gunicorn (prod)
- LLM vía Groq (free tier) — refactor a Pydantic AI en Día 5
- `uv` para deps y entornos
- `ruff` + `pyright` + `pre-commit`

## Quickstart

```bash
uv sync
cp .env.example .env  # editar con tu GROQ_API_KEY
uv run uvicorn email_triage.main:app --reload
```

Docs interactivos en `http://localhost:8000/docs`.

## Documentación

- [CLAUDE.md](CLAUDE.md) — convenciones técnicas para agentes AI
- [AGENTS.md](AGENTS.md) — workflow agente-humano y mapa del proyecto
- [docs/exec-plans/](docs/exec-plans/) — planes de implementación
- [docs/features/](docs/features/) — walkthroughs por feature
- [docs/testing/](docs/testing/) — protocolos de aceptación manual
