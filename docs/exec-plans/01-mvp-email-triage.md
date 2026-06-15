# 01. MVP Email Triage API (7 days)

**Status:** ✅ complete
**Estimate:** 12.5 hrs total · <2 hrs/day

## Intent

Build and deploy the API MVP described in `README.md`: three endpoints (`/triage`, `/triage/stream`, `/health`), API key auth, deploy on Render or Railway. Target at the end of Day 7: an e-commerce founder can open `/docs`, paste a sample email and see a real triage result.

## Scope

**Included:**
- Endpoints `POST /triage`, `POST /triage/stream`, `GET /health`
- Classification into 5 categories (`status`, `refunds`, `availability`, `shipments`, `prices`)
- Draft reply with confidence score
- Auth via `X-API-Key` header
- Structured logging with `request_id`
- Automated tests (≥3) with dependency overrides
- Docker multi-stage + Gunicorn + Uvicorn workers
- Deploy with HTTPS

**Out of scope (post-MVP):**
- Real multi-tenancy (one mailbox = one persisted API key)
- Result persistence (DB)
- Return webhooks
- Advanced metrics / observability
- Fine-grained rate limiting (slowapi optional on Day 7)

## Day-by-day plan

Each day starts with the assigned reading from [fastapi.tiangolo.com](https://fastapi.tiangolo.com). Without that reading, no coding.

### Day 0 — Prerequisites (15 min)

- Install `uv` (`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Create account at `console.groq.com` and obtain API key

### Day 1 — Skeleton + Tooling (2 hrs)

**Prior reading:** Python Types Intro · Virtual Environments · First Steps

**Tasks:**
- [x] `uv init`, `uv add fastapi uvicorn httpx`
- [x] `GET /health` works at `localhost:8000/docs`
- [x] `.env` with `GROQ_API_KEY`, `.gitignore` configured
- [x] Agent-human contract (`CLAUDE.md`, `AGENTS.md`, `docs/`)
- [x] Migrate to `src/email_triage/` layout (hatchling with `[tool.hatch.build.targets.wheel] packages = ["src/email_triage"]`)
- [x] Create `.env.example` with empty keys
- [x] `uv add --dev ruff "pyright[nodejs]" pre-commit` (need `[nodejs]` because there's no node on the system)
- [x] Configure `[tool.ruff]` (E, F, I, UP, B, SIM) and `[tool.pyright]` (strict) in `pyproject.toml`
- [x] `.pre-commit-config.yaml` with ruff (lint+format) and pyright
- [x] `uv run pre-commit install`

**Deliverable:** `uv run uvicorn email_triage.main:app --reload` works, `/docs` loads, `pre-commit run --all-files` passes.

### Day 2 — Schemas + LLMService (2 hrs)

**Prior reading:** Async / await · Request Body · Body Fields · Nested Models

**Tasks:**
- [x] `src/email_triage/schemas.py`:
  - `Category(StrEnum)` with `status | refunds | availability | shipments | prices`
  - `TriageRequest(subject: str, sender: EmailStr, body: str)` with `Field(min/max_length)`
  - `TriageResponse(category: Category, draft_reply: str, confidence: float)` with `0 ≤ confidence ≤ 1` validation
- [x] `src/email_triage/services/llm.py`:
  - Async `LLMService` using `httpx.AsyncClient`
  - Method `triage(req: TriageRequest) -> TriageResponse`
  - Prompt requesting structured JSON matching the schema (`response_format: json_object`)
  - Parsing with `TriageResponse.model_validate_json`
- [x] Manual smoke test (`scripts/smoke_llm.py`, run with `uv run --env-file .env python scripts/smoke_llm.py`)
- [x] `uv add "pydantic[email]"` for `EmailStr`

**Document:** `docs/features/02-schemas-and-llm.md` + `docs/testing/02-schemas-and-llm_testing.md`

### Day 3 — Endpoints + Streaming (2 hrs)

**Prior reading:** Response Model · Handling Errors · `StreamingResponse` with `text/event-stream`

**Tasks:**
- [x] `src/email_triage/routers/triage.py`:
  - `POST /triage` → `TriageResponse`
  - `POST /triage/stream` → `StreamingResponse` SSE
  - `try/except` on LLM → `HTTPException(503)`
- [x] `src/email_triage/routers/health.py`: move `/health` here
- [x] Register routers in `main.py` with `app.include_router(...)`

**Document:** `03-triage-endpoint.md`, `04-streaming.md` ✅

### Day 4 — Config + Auth + Middleware (1.5 hrs)

**Prior reading:** Settings (pydantic-settings) · Dependencies · Security (API Key) · Middleware

**Tasks:**
- [x] `uv add pydantic-settings structlog`
- [x] `src/email_triage/config.py`: `Settings(BaseSettings)` with `groq_api_key`, `groq_model`, `api_key`
- [x] `src/email_triage/deps.py`:
  - `get_settings()` cached with `@lru_cache`
  - `verify_api_key(x_api_key: str | None = Header())` raise 403 if missing or not matching
  - `get_llm_service()` cached with `@lru_cache`, returns shared instance
- [x] Apply `Depends(verify_api_key)` at router level on `/triage` and `/triage/stream`
- [x] `src/email_triage/middleware.py`: middleware that generates `request_id`, measures time, logs with structlog
- [x] Configure structlog JSON format with `contextvars` for `request_id`

**Document:** `05-auth.md`, `06-logging.md` ✅

### Day 5 — Tests + Background Tasks + Refactor to Pydantic AI (2 hrs)

**Prior reading:** Testing · Async Tests · Dependency Overrides · Background Tasks

**Tasks:**
- [x] `uv add --dev pytest pytest-asyncio`
- [x] `[tool.pytest.ini_options] asyncio_mode = "auto"` in `pyproject.toml`
- [x] `tests/conftest.py`: fixtures `client` and `failing_client` with `TestClient` + `dependency_overrides`
- [x] `tests/test_health.py`: GET /health → 200 + X-Request-Id header
- [x] `tests/test_triage.py`: 7 tests — happy path, 403 (x2), 422, 503, SSE 403, SSE events
- [x] Background task in `/triage`: `BackgroundTasks` logs result with structlog after responding
- [x] **Refactor LLMService to Pydantic AI:**
  - `uv add pydantic-ai-slim[groq]` (v1.104.0)
  - `Agent(GroqModel(...), output_type=TriageResponse)` — automatic parsing
  - `LLMError(RuntimeError)` as provider exception wrapper
  - 9 tests still passing without changes
  - CLAUDE.md §Stack updated

**Document:** `07-tests.md`, `08-pydantic-ai-refactor.md` ✅

### Day 6 — Production (Gunicorn + Docker + Lifespan) (2 hrs)

**Prior reading:** Run Manually · Server Workers · Docker · Lifespan

**Tasks:**
- [x] Lifespan handler in `main.py`: warm-up of `get_llm_service()` + log startup/shutdown
- [x] `gunicorn.conf.py`: `UvicornWorker`, `workers=(2×CPUs)+1`, `timeout=120`, `keepalive=5`
- [x] `Dockerfile` multi-stage:
  - Stage 1: `python:3.14-slim` + uv + `uv sync --frozen --no-dev`
  - Stage 2: copy `.venv/` + `src/`, CMD gunicorn
- [x] Healthcheck in Dockerfile (python urllib)
- [x] `.dockerignore` with `.env`, `.venv`, `tests/`, `docs/`

**Document:** `09-deploy-config.md` ✅

### Day 7 — Deploy + Polish (1.5 hrs)

**Prior reading:** Behind a Proxy · Deployment Concepts · Metadata + Docs URLs

**Tasks:**
- [x] Title, description, version, contact in `FastAPI(...)` ✅
- [x] Rate limiting with `slowapi` (20 req/min by IP) ✅
- [x] Logfire OTEL: `instrument_pydantic_ai()` + `instrument_fastapi(app)` ✅
- [x] `render.yaml` for deploy with Dockerfile ✅
- [ ] Deploy on Render and verify public `/docs` works
- [ ] **SHIP:** contact an e-commerce founder, give 1 month free

**Document:** `10-deploy.md` with rollback runbook ✅

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Groq free tier from Day 2 | OpenAI / Anthropic from the start | Unit economics: $9/mailbox needs near-zero-cost LLM to validate |
| Pydantic AI on Day 5 | Permanent raw httpx | Provider-agnostic + automatic parsing to `TriageResponse` |
| Pydantic AI on Day 5 (not Day 2) | Pydantic AI from Day 2 | The human wants to learn raw httpx first; refactor later |
| `src/` layout | Flat (`app/`) | Standard practice 2026: prevents import bugs in tests |
| ruff + pyright | mypy + black + isort | Modern stack; one tool for format+lint |
| Pydantic AI vs LangChain | LangChain | Overkill for 1 call; LangGraph only for complex agents |
| `StrEnum` for categories | `Literal[...]` | Better serialization in OpenAPI docs |
| Abstract provider via env var from Day 4 | Hardcoded Groq | Switch to Anthropic with one variable when margin allows |

## Risks / Open questions

- **Python 3.14 + Gunicorn:** 3.14 is very new. If Gunicorn has issues on Day 6, fall back to Python 3.13. Suspect #1 if something breaks.
- **Groq rate limit on free tier:** validate early that it handles 5 req/s. If not, consider Anthropic with initial credits.
- **Streaming + structured parsing:** Pydantic AI streams tokens but `TriageResponse` is only complete at the end. Probably stream only `draft_reply` and return category/confidence in a final stream event.
- **Hatch vs setuptools for `src/` layout:** decide on Day 1 based on what uv recommends as default.

## Done when

- [ ] The three endpoints work in production behind HTTPS
- [x] API key auth works and tests verify it ✅
- [x] Automated tests pass without internet (9/9) ✅
- [x] `docs/features/` has a walkthrough per implemented feature ✅
- [x] `docs/testing/` has a guide per feature ✅
- [ ] A real founder tested `/docs` interactive with a sample email
