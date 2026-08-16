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
| 36 | [Gmail Ingestion F1 — Connect OAuth + encrypted refresh token](36-gmail-connect-oauth.md) | 🚧 | Separate incremental-consent OAuth flow (`/gmail/connect` + `/gmail/callback`, `gmail.readonly`, `access_type=offline`) that stores a **Fernet-encrypted** `refresh_token` per user/workspace; new `gmail:connect` scope, `gmail_connections` table (migration 0006), 503 when unconfigured. Reuses Plan 15's PKCE + signed-cookie `state`. First phase of [proposal 002](../proposals/002-gmail-ingestion.md) |
| 37 | [Gmail Ingestion F2 — Sync endpoint + today's triaged inbox](37-gmail-sync-inbox.md) | 🚧 | `POST /gmail/sync` pulls today's unread inbox (`newer_than:1d`), maps each message → `TriageRequest` and runs the existing per-tenant `LLMService` (engine untouched); `GET /gmail/status`; emails are **ephemeral** (no body persisted, only the existing `TriageLog`). Revoked token → 409 "reconnect". Consumes Plan 36 |
| 38 | [Gmail Ingestion F3 — Inbox UI + connection card](38-gmail-inbox-ui.md) | 🚧 | React `/inbox` page: connect/disconnect Gmail, "Traer correos de hoy", list of triaged emails (Tag + confidence + expandable draft, reusing the Dashboard render + `TraceChat`), skeleton / celebratory-empty / reconnect states; Settings connection card. Role-gated, light+dark via Plan 34 tokens. Consumes Plan 36+37 |
| 39 | [Negatives render as counter-examples](39-negative-examples-as-counter-examples.md) | ✅ | Fix a Plan 29 regression: `kind="negative"` few-shot examples rendered like positives (mislabelling). A negative now renders `This email is NOT "{slug}"` (no label/reply) — a real counter-example to kill false positives. Compiler-only |
| 40 | [Gmail sync — filtros de lectura y días](40-gmail-sync-filters.md) | 🚧 | `POST /gmail/sync` acepta `SyncRequest{unread_only, days}`: construye el query de Gmail del lado servidor (`in:inbox [is:unread] newer_than:Nd`), valida `days` contra `gmail_sync_max_days`, y expone toggle Todos/No-leídos + selector de días en `Inbox.tsx`. Body opcional = comportamiento de Plan 37 intacto. Consume Plan 37/38 |
| 41 | [Reporte de voz — workflow de resumen + guion](41-voice-report-agent.md) | 🚧 | Workflow determinista (pydantic-ai/Groq) `resumir → guionizar` sobre los `items` que el cliente ya tiene (desacoplado de Gmail). `POST /reports/voice` → `VoiceReport` (guion estructurado + `by_category`/`total` calculados por el harness). v1 solo guion (`audio_url=None`); instrumenta los 2 pasos LLM con Plan 42 |
| 42 | [Telemetría de agentes (OTel) — 6 métricas del taller](42-agent-telemetry-otel.md) | 🚧 | Instrumenta los agentes de Plan 43/44 con las 6 métricas de OpenTelemetry-for-agents (token usage, tool-call success rate, LLM latency, loop iterations, context utilization, e2e latency) en `observability.py`, cableadas vía `instrument_agent_run`; material del taller en `charla-observabilidad-evals/` mapeando cada métrica a span/atributo/query de Logfire. El workflow de Plan 41 aporta las 4 que aplican. Ref: mintmcp blog |
| 43 | [Agente de diagnóstico de trazas](43-trace-diagnosis-agent.md) | 🚧 | Convierte el trace-debug agent de Plan 31 (pydantic-ai + tools curadas sobre Logfire, loop ReAct, aislamiento estructural) en un primitivo reutilizable: `POST /workspaces/{tid}/traces/{trace_id}/diagnose` → `TraceDiagnosis` estructurado (causa raíz + evidencia + `suggested_fix_kind`). Read-only. Sujeto de Plan 42; consumido por Plan 44 |
| 44 | [Copiloto de tuning de triage — orquestador](44-triage-tuning-copilot.md) | 🚧 | La feature genuinamente agéntica: dada una triage mal clasificada, un orquestador diagnostica (Plan 43) → propone cambios al **borrador** (contra-ejemplo/categoría vía Plan 26) → **re-clasifica un check-set** (correo marcado + hold-out de few-shots) contra el borrador → itera hasta arreglarlo sin regresiones. `POST /workspaces/{tid}/tune` → `TuningProposal`; **el publish lo hace el humano**. Sujeto principal de las 6 métricas (Plan 42) |
| 45 | [Agente investigador de bandeja (a futuro)](45-inbox-investigator-agent.md) | 📋 | **Plan a futuro** (backlog): agente que responde preguntas NL abiertas sobre la bandeja con tools read-only (`search_inbox`/`get_email_detail`), loop y tool-calls variables según la pregunta. Documentado para retomar; el ejemplo del taller ya lo cubren Plan 43/44 |
| 46 | [Frontend de las features agénticas](46-agentic-features-frontend.md) | 📋 | UI (React) para los 3 endpoints sin frontend, cada uno donde el usuario ya tiene el contexto: **F1** reporte de voz en `/inbox` (Plan 41), **F2** "Diagnosticar" junto a "Ver traces" (Plan 43), **F3** "Sugerir mejora" en el resultado del Dashboard (Plan 44, solo owner, enlaza a Studio para publicar). Fases independientes; la UI nunca publica |
| 47 | [Code review asistido por IA en CI](47-ai-code-review-ci.md) | 🚧 | `anthropics/claude-code-action@v1` (sobre el Agent SDK) en cada PR, invocando un skill del repo `.claude/skills/review-pr/` que conoce las convenciones de CLAUDE.md (async/DI/HTTP-codes/**Triage Studio**/tests-sin-Groq/pyright-strict) y postea comentarios inline. Auth con `ANTHROPIC_API_KEY`. Tooling/CI: no toca `email_triage/`. Runbook: [docs/CODE-REVIEW.md](../CODE-REVIEW.md) |

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
