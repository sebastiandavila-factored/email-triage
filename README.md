# email-triage

Support email triage API. Receives a raw email (subject/sender/body), classifies it into one of five categories (`status`, `refunds`, `availability`, `shipments`, `prices`) and returns a draft reply with a confidence score. Designed for e-commerce founders who want to reduce 1-2 hrs/day of manual triage without paying for Zendesk/Intercom.

## Endpoints

- `POST /triage` — classification + draft
- `POST /triage/stream` — same input, streaming draft via SSE
- `GET /health` — liveness check

## Stack

- Python 3.14, FastAPI + Uvicorn (dev), Gunicorn (prod)
- LLM via Groq (free tier) — refactored to Pydantic AI on Day 5
- `uv` for deps and environments
- `ruff` + `pyright` + `pre-commit`

## Quickstart

```bash
uv sync
cp .env.example .env  # edit with your GROQ_API_KEY
uv run uvicorn email_triage.main:app --reload
```

Interactive docs at `http://localhost:8000/docs`.

## Documentation

- [CLAUDE.md](CLAUDE.md) — technical conventions for AI agents
- [AGENTS.md](AGENTS.md) — agent-human workflow and project map
- [docs/exec-plans/](docs/exec-plans/) — implementation plans
- [docs/features/](docs/features/) — feature walkthroughs
- [docs/testing/](docs/testing/) — manual acceptance protocols
