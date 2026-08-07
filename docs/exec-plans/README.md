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
| 21 | [Team Workspaces + RBAC backend](21-team-workspaces-rbac.md) | ✅ | `WorkspaceService` + per-workspace scope enforcement (`require_scope`), team creation, member/role management, invitations by hashed token, workspace delete; wires every scope and closes finding C6 |
| 22 | [Workspace Management UI](22-workspace-management-ui.md) | 🚧 | React: workspace switcher, members/roles page, invite create/accept/revoke, create team, role-based UI gating; consumes Plan 21 |
| 23 | [Observability + Evals — State of the Art](23-observability-evals-sota.md) | ✅ | 7-phase roadmap: prompt versioning (Logfire), migrate evals to `pydantic-evals`, capability vs regression, multi-run + pass^k, judge "Unknown", online evals, balanced dataset. All 7 phases delivered |
| 24 | [Triage Studio F1 — Per-workspace taxonomy (Data & RBAC)](24-triage-studio-data-rbac.md) | ✅ | Move triage categories from the frozen `Category` StrEnum into a per-tenant `categories` table with CRUD behind a new `triage:configure` scope; legacy-seed on workspace creation. Zero regression: `/triage` untouched. First phase of [proposal 001](../proposals/001-triage-studio.md) |
| 25 | [Triage Studio F2 — Prompt compiler + dynamic output type](25-triage-studio-prompt-compiler.md) | ✅ | Compile an XML system prompt from the tenant's categories, build a per-tenant dynamic output type, serve an `LLMService` cached by `(tenant, version)`, and wire it into `/triage`. Safe degradation to the legacy prompt+enum when no DB. Touches the critical path |
| 26 | [Triage Studio F3 — Few-shot examples + template overrides + publish/eval-gate](26-triage-studio-examples-publish.md) | ✅ | Per-category few-shot examples injected into `<examples>`, editable template blocks, and a draft→preview→publish flow with an eval-gate and immutable versioned rollback. "Published wins if present; else F2 live-compile." Changes F2 semantics for published tenants |
| 27 | [Triage Studio F4 — MCP server + Claude Code workflows](27-triage-studio-mcp-workflows.md) | ✅ | `triage-studio` MCP server (stdio) with 6 typed tools wrapping the HTTP API (auth + actionable error translation), plus `.claude/commands/*` slash commands. Optional `mcp>=2.0` dep; the API app is unchanged |
| 28 | [Triage Studio F5 — Studio UI (React)](28-triage-studio-ui.md) | ✅ | `/studio` page: manage categories, few-shot examples, prompt template blocks, preview the compiled XML, and publish/rollback versions. Role-gated via `can()`, "published wins" banner. Frontend-only |
| 29 | [Simplify the compiled prompt](29-prompt-template-simplification.md) | ✅ | Rework the compiled prompt to Anthropic's guidance: plain prose for role/task/categories/guidelines, XML tags only for the few-shot `<examples>` and the untrusted `<email>`; drop `<output_format>` (structured output covers it). Updates tests + landing §03 |
| 30 | [Landing as the app root + login entry](30-landing-as-root.md) | ✅ | Make `/` the landing page inside the SPA (ported from the F6 HTML, CSS scoped under `.ts-root`), with a "Log in" button; authenticated visitors (incl. SSO return) forward into the app |
| 31 | [Trace-Debug Chat — Backend (Logfire MCP agent) + RBAC](31-trace-debug-chat-backend.md) | 🚧 | Backend agent (pydantic-ai) over the remote Logfire MCP so owner/admin can debug a triage's traces in natural language; new `traces:read` scope, `trace_id` in the `/triage` response, `POST /workspaces/{tid}/traces/chat` (SSE). Tenant isolation is **structural**: `arbitrary_query` hidden from the model, curated tenant/trace-bound tools. Targets MCP 2026-07-28 |
| 32 | [Trace-Debug Chat — UI (Dashboard panel)](32-trace-debug-chat-ui.md) | 🚧 | "Ver traces" button on the Dashboard result card (role-gated to owner/admin) that opens a chat panel anchored to the triage's `trace_id`; `TraceChat.tsx`, `rbac.ts` mirror, `api.ts` client. Frontend-only, consumes Plan 31 |
| 33 | [Propagate `tenant_id` to `/stream` + child spans (baggage)](33-tenant-baggage-span-propagation.md) | 🚧 | Attach `tenant_id` to every span of a `/triage` request via OTel baggage so streaming traces and child spans (pydantic-ai/httpx) are covered by per-org trace queries; the `/stream` span currently lacks it |
| 34 | [Unify the app UI/UX with the Triage Studio design system](34-unify-ui-design-system.md) | 🚧 | Bring the landing's teal/amber "control-room" tokens app-wide (Tailwind v4 `@theme` + `theme.css`), add a shared `AppShell` + UI primitives (killing the navbar duplicated across 5 pages), redesign all 9 pages, add light/dark with a `ThemeProvider`, and rename every "Email Triage" → "Triage Studio" |
| 35 | [Live product demo on the landing (hero)](35-landing-live-demo.md) | 🚧 | Port the animated product demo (cold-open inbox → trace-debug via MCP → montage → CTA) into a React `DemoReel` component as the landing's hero — play-on-view / pause-off-view (IntersectionObserver), `prefers-reduced-motion` poster+play, and a mobile fallback. No iframe of the artifact; reuses the shared tokens |
| 36 | [Gmail Ingestion F1 — Connect OAuth + encrypted refresh token](36-gmail-connect-oauth.md) | 📋 | Separate incremental-consent OAuth flow (`/gmail/connect` + `/gmail/callback`, `gmail.readonly`, `access_type=offline`) that stores a **Fernet-encrypted** `refresh_token` per user/workspace; new `gmail:connect` scope, `gmail_connections` table (migration 0006), 503 when unconfigured. Reuses Plan 15's PKCE + signed-cookie `state`. First phase of [proposal 002](../proposals/002-gmail-ingestion.md) |
| 37 | [Gmail Ingestion F2 — Sync endpoint + today's triaged inbox](37-gmail-sync-inbox.md) | 📋 | `POST /gmail/sync` pulls today's unread inbox (`newer_than:1d`), maps each message → `TriageRequest` and runs the existing per-tenant `LLMService` (engine untouched); `GET /gmail/status`; emails are **ephemeral** (no body persisted, only the existing `TriageLog`). Revoked token → 409 "reconnect". Consumes Plan 36 |
| 38 | [Gmail Ingestion F3 — Inbox UI + connection card](38-gmail-inbox-ui.md) | 📋 | React `/inbox` page: connect/disconnect Gmail, "Traer correos de hoy", list of triaged emails (Tag + confidence + expandable draft, reusing the Dashboard render + `TraceChat`), skeleton / celebratory-empty / reconnect states; Settings connection card. Role-gated, light+dark via Plan 34 tokens. Consumes Plan 36+37 |

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
