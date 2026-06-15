# Exec Plans

Technical documents that translate a product intent into concrete code changes. Each exec plan describes the "what" and "how" before starting to implement.

## Plans

| # | Plan | Status | Description |
|---|---|---|---|
| 01 | [MVP email-triage (7 days)](01-mvp-email-triage.md) | 🚧 | Day-by-day plan to reach the deployed MVP |
| 11 | [Real streaming with Pydantic AI](11-streaming-real.md) | ✅ | Replace the cosmetic streaming in `/triage/stream` with real token-streaming via `agent.run_stream()` |
| 12 | [Observability with Logfire (OTel) + TTFT](12-observability-logfire.md) | ✅ | Metrics catalog, TTFT instrumentation in streaming, logs↔traces correlation, scrubbing and sampling |
| 13 | [Accuracy Evaluation — Golden Dataset + Metrics + LLM Judge](13-evals.md) | ✅ | Golden dataset of 40 cases, classification metrics (F1, ECE), LLM-as-judge for reply quality, Logfire run persistence, `make eval` CLI |
| 14 | [PostgreSQL + SQLAlchemy — Persistence Layer](14-database-postgresql.md) | ✅ | Async ORM (SQLAlchemy 2.x + asyncpg), Alembic migrations, repository pattern, triage logs + eval run persistence, per-tenant data model |
| 15 | [Google OAuth2 SSO — Authentication & Authorization](15-auth-google-oauth2.md) | ✅ | Authorization Code Flow + PKCE, signed HttpOnly session cookies, per-tenant API key (bcrypt), `/auth/login` `/auth/callback` `/auth/me` `/auth/rotate-key` endpoints |
| 16 | [Users + Password Auth — Separate User/Tenant Models](16-users-and-password-auth.md) | ✅ | Split User (person) from Tenant (org/domain), email+password signup alongside Google SSO, Membership table, Alembic migration 0002 |
| 17 | [React Frontend — Auth + Triage UI](17-react-frontend.md) | 📋 | Vite + React + TypeScript + Tailwind SPA; signup/login/Google SSO; email triage form; JWT in localStorage; monorepo `frontend/` directory |
| 20 | [Frontend Deploy — Vercel + FastAPI Cloud + Neon](20-frontend-vercel-deploy.md) | 📋 | Static SPA on Vercel calling the FastAPI Cloud API (DB on Neon) cross-origin; `VITE_API_URL` base, absolute Google-SSO link, `vercel.json` SPA rewrites, CORS + redirect-URI wiring. Runbook: [docs/DEPLOY.md](../DEPLOY.md) |

Statuses: 📋 proposed · 🚧 in progress · ✅ delivered · ❌ discarded

## When to create an exec plan

Required if the feature:
- Touches ≥3 files
- Introduces a new dependency
- Changes an architectural pattern
- Has an impact on deploy or infra

Not needed for:
- Trivial fixes
- Cosmetic refactors
- Documentation changes

## Conventions

- **Name:** `NN-feature.md` with chronological prefix (`01-`, `02-`, …). The same number is reused for `docs/features/NN-*.md` and `docs/testing/NN-*_testing.md`.
- **Before coding:** the plan must be reviewed by the human.
- **Initial status:** 📋. Changes to 🚧 when implementation starts, ✅ on merge, ❌ if discarded.

## Minimal template

```markdown
# NN. [Feature Name]

**Status:** 📋 proposed
**Estimate:** X hrs

## Intent
[1-2 paragraphs: what it solves, for whom]

## Scope
- Included: ...
- Out of scope: ...

## Concrete changes
| File | Change |
|---|---|

## Design decisions
| Decision | Discarded alternative | Reason |
|---|---|---|

## Risks / Open questions
- ...

## Done when
- [ ] Tests pass
- [ ] `docs/features/NN-x.md` updated
- [ ] `docs/testing/NN-x_testing.md` updated
- [ ] Human validated with the testing guide
```
