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
