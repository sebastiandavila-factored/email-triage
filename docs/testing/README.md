# Testing Guides

Manual testing guides. **These are mandatory and serve as the human's acceptance protocol.** The agent runs automated tests; the human validates UX and real edge cases following these guides.

## Existing guides

| # | Feature | Guide |
|---|---|---|
| 01 | Day 1 — Skeleton + Tooling | [01-day1-skeleton_testing.md](01-day1-skeleton_testing.md) |
| 02 | Day 2 — Schemas and LLMService | [02-schemas-and-llm_testing.md](02-schemas-and-llm_testing.md) |

## Conventions

- **One file per feature** with chronological prefix `NN-feature_testing.md`, same number as `docs/features/NN-feature.md`.
- Each guide must include:
  - **Prerequisites** — environment variables, external services, test data
  - **Happy path** — the expected flow step by step
  - **Preventive edge cases** — scenarios the agent cannot test (real network, valid secrets, latency, real rate limits)
  - **Workarounds** if there are technical blockers (e.g. how to simulate a Groq rate limit without spending quota)
  - **Log / DB verification** — what to grep, what `request_id` to look for, what metric to check
- If the agent hits a blocker during implementation, document it here so the next one doesn't stumble on it.

## Template

See [TEMPLATE.md](TEMPLATE.md).
