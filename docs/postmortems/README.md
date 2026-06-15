# Postmortems

Incident write-ups for outages, deployment failures, and other production-impacting events. Each doc captures what happened, the root cause, the fix, and — most importantly — what NOT to touch going forward.

## Conventions

- One file per incident, chronological prefix (`01-`, `02-`, …).
- Title format: `NN-short-slug.md`.
- Every postmortem ends with a **Do NOT touch** section listing load-bearing decisions. Future agents must respect them or update the postmortem.

## Index

| # | Incident | Date | Status |
|---|---|---|---|
| 01 | [FastAPI Cloud cannot import `email_triage` (src layout)](01-fastapi-cloud-src-layout.md) | 2026-06-04 | Resolved |
