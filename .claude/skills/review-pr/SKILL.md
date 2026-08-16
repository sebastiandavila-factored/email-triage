---
name: review-pr
description: AI-assisted code review for email-triage pull requests. Reviews the PR diff against this repo's conventions (FastAPI async, pyright strict, Triage Studio category rules) and posts inline comments. Use in CI on pull_request events, or locally with /review-pr.
when_to_use: Invoke on a pull request to get a focused, convention-aware review. Triggered automatically by the GitHub Action in .github/workflows/code-review.yml; can also be run locally as /review-pr [--comment owner/repo/pull/N] [--base <branch>].
disable-model-invocation: true
argument-hint: "[--comment owner/repo/pull/N] [--base <branch>]"
allowed-tools: >
  mcp__github_inline_comment__create_inline_comment
  Read Grep Glob
  Bash(git diff *) Bash(git fetch *) Bash(git log *) Bash(git status *)
---

# Review this pull request

You are reviewing a pull request for **email-triage**, an async FastAPI service that
classifies support emails and drafts replies. Your job is to catch real problems in
the **changed code**, judged against this repository's own conventions — not to
restyle code that lint already handles.

Arguments passed to this skill: `$ARGUMENTS`

## 1. Get the diff

- If `$ARGUMENTS` contains `--base <branch>`, use that branch as the base; otherwise use `main`.
- Fetch and diff against the base to see exactly what changed:
  - `git fetch origin <base>`
  - `git diff origin/<base>...HEAD`
- Review **only the added/modified lines** and the code they directly affect. Read
  surrounding files with Read/Grep when you need context, but do not comment on code
  the PR did not touch.

## 2. What to look for (in priority order)

Ground every finding in these repo conventions (source of truth: `CLAUDE.md`, `AGENTS.md`).
The package lives at `email_triage/` (not `src/`).

**A. Correctness bugs (highest priority)**
- Logic errors, off-by-one, wrong branches, unhandled `None`, broken async
  (missing `await`, blocking I/O on the async critical path, sync calls that should
  be `async def`).
- Concurrency: the shared `httpx.AsyncClient` / `LLMService` must come from the
  lifespan / DI, never be instantiated per request.

**B. Repo-specific contract violations**
- **Pydantic as the single source of truth** — every request/response payload is a
  Pydantic model in `schemas.py`. Flag hand-rolled dict validation or shapes that
  bypass the schema.
- **Dependency injection for external services** — `LLMService`, `Settings`, etc. are
  injected via `Depends()`, not constructed inside handlers. Flag direct instantiation.
- **Correct HTTP status codes** — LLM/Groq calls are wrapped in `try/except` that
  raises `HTTPException` with semantic codes: `503` when Groq is down, `422` when the
  LLM output fails validation, `403` when the API key is missing. Flag bare `500`s,
  swallowed exceptions, or stack traces returned to the caller.
- **Structured logging** — logs go through `structlog` and must carry `request_id`
  (and `trace_id`/`span_id`). Flag `print()` and stray `logging` calls on the
  critical path.
- **Categories — Triage Studio (critical):** the frozen five in
  `email_triage/schemas.py:Category` are legacy/fallback + offline-evals only. On the
  live path, categories are **per-workspace rows** compiled into an XML prompt with a
  dynamic `str` output. **Flag any change that re-freezes categories or routes
  `/triage` back through the enum** — see `docs/proposals/001-triage-studio.md`.
- **Scope** — the public surface is `/triage`, `/triage/stream`, `/health`. Flag new
  endpoints or features that expand scope without an exec-plan.

**C. Tests**
- Tests must **never call Groq/the real LLM** — the `get_llm_service` dependency is
  overridden with a mock via `app.dependency_overrides`. Flag any test that would hit
  the network.
- New behavior on a touched handler should come with a test. Flag missing coverage.

**D. Security & secrets**
- No hardcoded API keys, tokens, or secrets; secrets come from `Settings`/`.env`
  (gitignored). Flag any secret literal or a secret logged in plaintext.
- Email content is sensitive: flag logging of raw email bodies beyond what the
  scrubbed observability config allows.

**E. Quality (report, do not block on)**
- Type-safety gaps that `pyright` in **strict** mode would reject.
- Clear simplifications or reuse of existing helpers.
- Do **not** report pure style/formatting — `ruff format` + `ruff check` own that.

## 3. Reporting

Cover the changed code thoroughly. For each real issue, include a **severity**
(`blocker` / `should-fix` / `nit`) and a one-line rationale tied to a convention
above. Prefer a concrete suggested change over a vague concern.

- **When `$ARGUMENTS` contains `--comment`** (CI mode): post each finding as an
  **inline comment** on the exact file and line using
  `mcp__github_inline_comment__create_inline_comment`. If you find nothing worth
  raising, post a single short summary comment saying the change looks good and why.
  Keep it high-signal — do not flood the PR with nits.
- **Otherwise** (local mode): print the findings grouped by severity, each as
  `path:line — [severity] finding` followed by the suggested fix.

Do not run `git commit`, `git push`, or modify files — this is a read-only review.
Report faithfully: if you were unable to inspect something (e.g. the diff was empty),
say so instead of inventing findings.
