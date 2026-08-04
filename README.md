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

## MCP server

Triage Studio is also exposed as an MCP server (`triage-studio`) with typed tools
(`classify_email`, `list_categories`, `create_category`, `add_example`, `preview_prompt`,
`list_prompt_versions`) so any Claude client can drive it. See
[docs/features/27-triage-studio-mcp-workflows.md](docs/features/27-triage-studio-mcp-workflows.md).

```bash
uv sync --extra mcp
export TRIAGE_API_URL=http://localhost:8000 TRIAGE_API_KEY=<key>
export TRIAGE_SESSION_TOKEN=<jwt> TRIAGE_WORKSPACE_ID=<tid>
uv run triage-mcp   # stdio
```

## Documentation

- [CLAUDE.md](CLAUDE.md) — technical conventions for AI agents
- [AGENTS.md](AGENTS.md) — agent-human workflow and project map
- [docs/exec-plans/](docs/exec-plans/) — implementation plans
- [docs/features/](docs/features/) — feature walkthroughs
- [docs/testing/](docs/testing/) — manual acceptance protocols
