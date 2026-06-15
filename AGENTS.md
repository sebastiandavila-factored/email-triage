# AGENTS.md — Project Map and Collaboration Contract

Orients AI agents: where everything is, how to work with the human, what to document.

## 1. Documentation map

| Looking for | Where it is |
|---|---|
| Technical conventions (stack, patterns, agent limits) | [CLAUDE.md](CLAUDE.md) |
| Day-by-day implementation plan | [docs/exec-plans/01-mvp-email-triage.md](docs/exec-plans/01-mvp-email-triage.md) |
| Feature walkthroughs | [docs/features/](docs/features/) |
| Manual testing protocols | [docs/testing/](docs/testing/) |
| Quickstart and public endpoints | [README.md](README.md) |

## 2. Code map — who owns what

| Domain | Key files | Read before touching |
|---|---|---|
| App entrypoint | `src/email_triage/main.py` | CLAUDE.md §Structure · exec-plans/01 §Day 1 and 6 |
| Schemas (request/response) | `src/email_triage/schemas.py` | CLAUDE.md §Patterns #1 · exec-plans/01 §Day 2 |
| LLM provider | `src/email_triage/services/llm.py` | CLAUDE.md §Patterns #3 · exec-plans/01 §Day 2 and 5 |
| Endpoints | `src/email_triage/routers/triage.py`, `routers/health.py` | CLAUDE.md §Patterns #4 · exec-plans/01 §Day 3 |
| Config | `src/email_triage/config.py` | exec-plans/01 §Day 4 |
| Auth (API key) | `src/email_triage/deps.py` | CLAUDE.md §Patterns #2 · exec-plans/01 §Day 4 |
| Middleware (logging) | `src/email_triage/middleware.py` | CLAUDE.md §Patterns #5 · exec-plans/01 §Day 4 |
| Tests | `tests/` | CLAUDE.md §Tests · exec-plans/01 §Day 5 |
| Deploy | `Dockerfile`, `gunicorn.conf.py`, `render.yaml` | exec-plans/01 §Day 6 and 7 |
| Rate limiting | `src/email_triage/deps.py` (`limiter`) · `routers/triage.py` | CLAUDE.md §Stack · features/10 |
| Observability | `src/email_triage/main.py` (logfire setup) | CLAUDE.md §Stack · features/10 |

**Day 1:** most of these files don't exist yet. Create them according to the plan.

## 3. Development and validation workflow

**Roles:**

- **Human (Architect):** defines intent, approves merges, makes commits, validates UX following `docs/testing/`.
- **Agent (Executor):** reads docs before editing, implements, runs automated tests, documents. **Never** commits or pushes.

**Rule:** the agent validates in theory (tests + types). The human validates in practice (UX, real edge cases). If the agent is blocked (inaccessible link, broken dependency, ambiguity), it must warn and **not hallucinate values**.

**Cycle per feature:**

1. **PLAN** — If the feature touches ≥3 files, introduces a new dependency or changes a pattern, write/update `docs/exec-plans/NN-feature.md` before coding.
2. **IMPLEMENT** — New branch. Automated tests mandatory (unit + integration with dependency overrides).
3. **DOCUMENT** — Create `docs/features/NN-feature.md` + `docs/testing/NN-feature_testing.md`. Update `CLAUDE.md` if a new pattern emerges. Update this file if the code map changes.
4. **EVALUATE** — Human follows `docs/testing/NN-feature_testing.md`. If blockers or bugs are found, go back to step 2.
5. **DELIVER** — Human commits, pushes and opens PR.

## 4. Documentation protocol

Required when closing a feature:

- **Chronological prefix:** `01-`, `02-`, etc. in `docs/exec-plans/`, `docs/features/`, `docs/testing/`. The same number links all three per feature (e.g. `02-streaming.md` in each folder, `02-streaming_testing.md` in testing).
- **Walkthrough:** copy `docs/features/TEMPLATE.md` → `docs/features/NN-feature.md`. Fill it in.
- **Testing guide:** copy `docs/testing/TEMPLATE.md` → `docs/testing/NN-feature_testing.md`. Include happy path, preventive edge cases, workarounds if there are technical blockers, log verification.
- **Update CLAUDE.md:** only if the feature establishes a new pattern or changes an existing one.
- **Update AGENTS.md:** only if the code map changes (new folder, new domain, new "read before touching" file).
- **Exec plans:** mandatory for features ≥3 files or dependency changes. Not needed for trivial fixes.

## 5. Current state and next steps

**Existing (Day 1 + 2 complete):**
- `src/email_triage/main.py` — FastAPI app with `GET /health` ✅
- `src/email_triage/schemas.py` — `Category` (StrEnum, 5 values), `TriageRequest`, `TriageResponse` ✅
- `src/email_triage/services/llm.py` — async `LLMService` with httpx against Groq ✅
- `scripts/smoke_llm.py` — manual smoke test against real Groq ✅
- `pyproject.toml` with FastAPI, Uvicorn, httpx, `pydantic[email]` + hatchling ✅
- `.env` with `GROQ_API_KEY` (gitignored), `.env.example` committable ✅
- Tooling: ruff + pyright + pre-commit configured and passing ✅
- `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/` (with walkthroughs 01 and 02) ✅

**Completed (Day 3):**
- `src/email_triage/routers/triage.py` — `POST /triage` and `POST /triage/stream` (SSE) ✅
- `src/email_triage/routers/health.py` — `/health` moved here ✅
- `try/except` for Groq down → `HTTPException(503)` ✅

**Completed (Day 4):**
- `src/email_triage/config.py` — `Settings(BaseSettings)` with pydantic-settings ✅
- `src/email_triage/deps.py` — `get_settings()`, `verify_api_key()`, `get_llm_service()` with @lru_cache ✅
- Auth `X-API-Key` on `/triage` and `/triage/stream` via router-level dependency ✅
- `src/email_triage/middleware.py` — request_id + structlog JSON + X-Request-Id header ✅

**Completed (Day 5):**
- `tests/conftest.py` with fixtures `client` + `failing_client` (dependency_overrides) ✅
- `tests/test_health.py` + `tests/test_triage.py` — 9 tests, no Groq calls ✅
- Background task in `POST /triage` with `BackgroundTasks` + structlog ✅
- `LLMService` refactored to Pydantic AI (`pydantic-ai-slim[groq]` v1.104.0) ✅
- `LLMError(RuntimeError)` as LLM service exception contract ✅

**Completed (exec-plan 11 — real streaming):**
- `StreamingTriageResponse` in `schemas.py` — parallel model with optional fields for incremental validation ✅
- `LLMService.triage_stream()` — `@asynccontextmanager` over `agent.run_stream()` with `output_type=StreamingTriageResponse` ✅
- `triage_stream` handler rewritten: pre-fetch for pre-stream 503, delta encoding, log at generator close ✅
- **Real token-level streaming** via `stream_output(debounce_by=None)` — TTFT target < 500 ms ✅
- 3 new tests: meta-before-data, draft_reply reconstruction from deltas, 503 on open failure ✅
- 10/10 tests passing, ruff + pyright clean ✅

**Completed (exec-plan 12 — Logfire observability):**
- `src/email_triage/observability.py` — centralized catalog of counters/histograms/gauge ✅
- `logfire.configure` with `scrubbing=ScrubbingOptions(sender redacted)`, `sampling=SamplingOptions(head + tail)` ✅
- `instrument_pydantic()`, `instrument_system_metrics()`, `instrument_httpx()` active ✅
- structlog ↔ traces correlation: `trace_id` + `span_id` in every JSON log ✅
- Spans `triage.sync` / `triage.stream` with attributes: `endpoint`, `email.*_chars`, `triage.result.*`, `triage.stream.ttft_ms` ✅
- `LLM_IN_FLIGHT` gauge + `LLM_ERRORS_TOTAL` in `services/llm.py`; `AUTH_FAILURES_TOTAL` in `deps.py` ✅
- `scripts/measure_ttft.py` — measures client-side TTFT with p50/p95/max ✅
- 5 new tests in `tests/test_observability.py` with `capfire` fixture ✅
- `config.py` — fields `logfire_send_to_logfire`, `logfire_sample_rate`, `logfire_environment` ✅
- 17/17 tests passing, ruff + pyright clean ✅

**Completed (Day 6):**
- Lifespan `@asynccontextmanager` in `main.py` — eager init of `LLMService` + structlog startup/shutdown ✅
- `gunicorn.conf.py` — `UvicornWorker`, `(2×CPUs)+1` workers, `timeout=120` ✅
- `Dockerfile` multi-stage with uv — builder + runtime, no `.env` or build tools ✅
- `.dockerignore` — `.env`, `.venv`, `tests/`, `docs/` excluded ✅

**Completed (Day 7):**
- Metadata in `FastAPI(...)`: title, summary, description, contact, license ✅
- Rate limiting `slowapi` 20 req/min by IP on `/triage` and `/triage/stream` ✅
- OTEL observability with Logfire: `instrument_pydantic_ai()` + `instrument_fastapi(app)` ✅
- `render.yaml` with `env: docker` pointing to multi-stage Dockerfile ✅
- `.env.example` updated with `LOGFIRE_TOKEN` and `LOGFIRE_SEND_TO_LOGFIRE` ✅
- 9/9 tests passing, ruff + pyright clean ✅

**Pending (post-code):**
- Deploy on Render and verify public `/docs`
- SHIP: contact an e-commerce founder, give 1 month free

Full 7-day plan: [docs/exec-plans/01-mvp-email-triage.md](docs/exec-plans/01-mvp-email-triage.md).

## 6. Project principles

1. **The proposal is the truth of scope.** Do not add features outside the three endpoints (`/triage`, `/triage/stream`, `/health`) until the MVP is in production.
2. **Short day (<2 hrs) with reading first.** Each day starts by reading the official FastAPI docs assigned in the plan. Without that reading, no coding.
3. **Pydantic is the contract.** If the shape of the data changes, change the schema first. The handler only orchestrates.
4. **Dependency injection whenever touching external I/O.** Makes tests trivial and the code more readable.
5. **Errors with correct HTTP code.** Zapier/Make need semantic 4xx vs 5xx to retry. Never return 500 with a stack trace.
6. **The $9/mailbox margin drives decisions.** If a dependency or provider breaks unit economics, it's discarded — no matter how cool it is.
7. **The human commits.** The agent never runs `git commit`, `git push` or `git amend`.
