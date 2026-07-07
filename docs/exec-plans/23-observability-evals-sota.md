# 23. Observability + Evals — State of the Art

**Status:** ✅ delivered (Phases 1–7)
**Estimate:** ~14 hrs across 7 PRs
**Supersedes / extends:** [12-observability-logfire.md](12-observability-logfire.md), [13-evals.md](13-evals.md)

> This is an **umbrella plan** covering 7 small, independently reviewable phases.
> **One phase ≈ one PR.** Phases are ordered by impact/effort and (mostly) build on
> each other. Each phase has its own feature + testing docs, sub-numbered
> `23.1`…`23.7` (e.g. `docs/features/23.1-prompt-versioning.md`,
> `docs/testing/23.1-prompt-versioning_testing.md`) so the umbrella number `23`
> links the whole roadmap while each PR stays self-contained.

---

## Intent

The product already has solid offline evals (plan 13) and Logfire observability
(plan 12), but the prompt is hard-coded, the eval harness is bespoke, and there is
no online quality signal. This plan moves both systems to the state of the art:

- **Prompt as a versioned, governed artifact** managed in Logfire, with a code
  fallback that keeps the critical path alive when Logfire is unreachable.
- **Eval harness on the `pydantic-evals` framework** (`Dataset`/`Case`/`Evaluator`/
  `evaluate`), preserving every existing metric as a custom evaluator and reusing
  the `JudgeAgent`, with traces in Logfire.
- **Capability vs regression separation**, **multi-run + pass^k** reliability,
  a **judge that can abstain ("Unknown")**, **cheap online evals** on live `/triage`
  traffic, and a **balanced, provenance-documented dataset**.

## Hard constraints (from CLAUDE.md — non-negotiable)

- The agent never runs `git commit` / `git push` / `git amend`. The human commits.
- Tests never call Groq — `LLMService` / judge are replaced via
  `app.dependency_overrides` or direct mocks.
- The 5 categories (`status`, `refunds`, `availability`, `shipments`, `prices`) are
  frozen. No phase here changes them. If a prompt edit in the Logfire UI ever drifts
  from the `Category` enum, that is a **governance bug** (see Phase 1 guard), not a
  feature.
- No `--no-verify`. If pre-commit fails, fix the code.
- Missing secret (`LOGFIRE_TOKEN`, `GROQ_API_KEY`) → warn and stop, never hallucinate.
- All docs/code/CLI text in **English** (plan 13 rule).

## Environment audit (done during Phase 0 discovery)

| Item | State |
|---|---|
| `GROQ_API_KEY` in `.env` | ✅ present |
| `LOGFIRE_TOKEN` in `.env` | ✅ present |
| `logfire` version | 4.34.0 — `logfire.var(...).get(label=...)` available ✅ |
| `pydantic-evals` | ❌ not installed — must add (latest 1.107.0, requires-python ≥3.10) |
| `pydantic-ai-slim[groq]` | 1.104.0 — `Agent(capabilities=[...])` support **must be verified** for Phase 6 |
| Dataset | 40 cases; per-category 8/9/8/7/8 (mildly unbalanced); language 34 es / 6 en; difficulty 32 easy / 2 med / 6 hard |
| `logfire.var(...).get()` fallback | Confirmed: when unresolved, returns `ResolvedVariable(value=<default>, reason='code_default')` ✅ |

> **Note (out of scope, flagged):** `AGENTS.md` §2 references `src/email_triage/…`
> but the package lives at `email_triage/…`. Not fixed here; mentioned so a future
> doc PR can correct the code map.

---

## Phase 1 — Prompt versioning (Logfire Prompt Management) ✅

**Status:** ✅ delivered. Docs: [feature](../features/23.1-prompt-versioning.md) ·
[testing](../testing/23.1-prompt-versioning_testing.md).

**PR scope:** move `SYSTEM_PROMPT` out of code and into a Logfire-managed variable,
consumed once at startup with a code fallback.

### Goal
The triage system prompt becomes a versioned artifact promotable from the Logfire UI
without a deploy, while a code `default=` guarantees the critical path never breaks if
Logfire is unreachable.

### Design
- Keep the current `SYSTEM_PROMPT` string in `services/llm.py` as the **canonical code
  fallback** and the `default=` argument.
- Consume exactly as specified:
  ```python
  resolved = logfire.var(
      name="prompt__email_triage_system",
      default=SYSTEM_PROMPT,
  ).get(label="production")
  prompt_text = resolved.value
  ```
- **Resolve once in the `lifespan`** (not per request). The resolved string is passed
  into `LLMService(system_prompt=...)`. `LLMService.__init__` gains a
  `system_prompt: str = SYSTEM_PROMPT` parameter; the agent is built with it.
- Wiring: `get_llm_service()` (currently `@lru_cache`) is refactored to build the
  service from the resolved prompt. The lifespan resolves the prompt and warms the
  singleton; `Depends(get_llm_service)` returns that warmed instance. No per-request
  `.get()`.
- `config.py`: add `prompt_label: str = "production"` so the label is configurable.
- **Governance guard (prompt ↔ `Category`):** a small startup check asserts each of the
  5 `Category` values appears in the resolved prompt text; on mismatch, log a
  structured `prompt.category_drift` **warning** (do not crash — fallback still serves
  traffic). Documented in the feature doc: the code `default=` is the source of truth;
  any UI edit must keep the 5 categories and is reviewed against this guard.

### Files
| File | Change |
|---|---|
| `email_triage/services/llm.py` | `LLMService.__init__(..., system_prompt: str = SYSTEM_PROMPT)`; build agent with it. Keep `SYSTEM_PROMPT` const. |
| `email_triage/deps.py` | `get_system_prompt()` provider resolving via `logfire.var(...).get(label=settings.prompt_label)`; refactor `get_llm_service()` to use it. |
| `email_triage/main.py` | lifespan: resolve prompt once, warm `LLMService`, run the category-drift guard. |
| `email_triage/config.py` | add `prompt_label: str = "production"`. |
| `tests/test_prompt_versioning.py` | new. |
| `docs/features/23.1-prompt-versioning.md`, `docs/testing/23.1-prompt-versioning_testing.md` | new. |

### New deps
None (logfire 4.34.0 already supports `var`).

### Acceptance criteria
- [ ] With no Logfire prompt defined, `/triage` works using the code default
      (`resolved.reason == "code_default"`); no remote fetch per request.
- [ ] Prompt is resolved exactly once per process (asserted in a test by patching
      `logfire.var`).
- [ ] Category-drift guard emits a structured warning when a (mocked) prompt drops a
      category; never raises.
- [ ] ruff / pyright / pytest / pre-commit green.

### Test plan
- Mock `logfire.var(...).get` to return a `ResolvedVariable`-like object with `.value`;
  assert `LLMService` is built with that value.
- Assert default-path behavior (no token / unresolved → default value used).
- Assert resolution happens once (call count on the mock across N requests == 1).
- Drift guard: feed a prompt missing `refunds`; assert warning logged, no exception.

### Risks
- `logfire.var().get()` semantics: `.get()` reads a locally-cached snapshot, not a
  blocking network call — but we still resolve once in lifespan to be safe and explicit.
- Singleton/`lru_cache` interaction with `dependency_overrides` in tests — keep the
  override seam (`get_llm_service`) intact.

### MANUAL steps (yours)
- **Logfire UI:** create a prompt named **`prompt__email_triage_system`**, paste the
  current `SYSTEM_PROMPT` as its first version, and promote the **`production`** label.
  Until you do this, the code fallback serves traffic (by design). Code ships and is
  fully tested without this step.

---

## Phase 2 — Migrate `evals/` to `pydantic-evals` ✅

**Status:** ✅ delivered (`pydantic-evals==1.104.0` installed). Docs:
[feature](../features/23.2-pydantic-evals.md) ·
[testing](../testing/23.2-pydantic-evals_testing.md). Live-smoke verified against Groq
(classification + judge paths render both reports; DB persistence + Logfire spans work).

**PR scope:** replace the bespoke runner internals with `Dataset`/`Case`/`Evaluator`/
`evaluate`, preserving all metrics and the console report.

### Goal
Standardize the harness on `pydantic-evals` so we inherit its tracing, reporting, and
multi-run/online features (Phases 4 & 6) for free, without losing accuracy, macro-F1,
ECE, the reliability diagram, the judge, the Logfire `eval.run` span, or DB persistence.

### Design
- Build a `Dataset[TriageRequest, str]` from `dataset.jsonl`: `Case(name=id,
  inputs=TriageRequest(...), expected_output=expected_category, metadata={language,
  difficulty, notes, source})`.
- The **task** under evaluation = `await llm.triage(req)` returning `TriageResponse`.
- **Custom per-case evaluators** (in `evals/evaluators.py`):
  - `CategoryCorrect` → `bool` (predicted == expected).
  - `ConfidenceRecorded` → exposes `confidence` so the aggregate ECE step can read it.
  - `JudgeQuality` → wraps the **existing `JudgeAgent`** (reused, not reimplemented),
    returning the 5 judge scores as evaluator outputs.
- **Aggregate metrics stay in `evals/metrics.py`** (accuracy is per-case-averageable,
  but macro-F1, ECE, and the reliability diagram are dataset-level). They are computed
  from the framework report's per-case results — `metrics.py` is reused, fed by the new
  report instead of the old `EvalResult` list. A thin adapter maps report rows →
  existing `compute_report()` input.
- **Console report:** keep the rich custom `print_report` (it has ECE + reliability
  diagram + misclassified table that `report.print()` does not), AND additionally call
  the framework's `report.print()` for the standard per-case/assertions table.
  *Justification:* the framework table is great for per-case/per-assertion drill-down;
  our calibration + reliability sections are domain-specific and worth keeping.
- **Logfire:** `pydantic-evals` emits its own experiment spans when `logfire.configure`
  is active. Keep the existing `eval.run` summary span (accuracy/macro_f1/ece/judge) as
  the queryable regression anchor; ensure we don't double-count (reconcile manual span
  vs framework spans — document which to chart).
- **DB persistence** (`persist_eval_run`) preserved, fed from the new report.

### Files
| File | Change |
|---|---|
| `evals/evaluators.py` | new — `CategoryCorrect`, `ConfidenceRecorded`, `JudgeQuality(Evaluator)`. |
| `evals/dataset_loader.py` | new — JSONL → `Dataset[TriageRequest, str]`. |
| `evals/run_evals.py` | rewrite core to `dataset.evaluate(task)`; keep CLI flags, console report, Logfire span, DB persistence via an adapter. |
| `evals/metrics.py` | adapter to accept framework report rows (logic unchanged). |
| `pyproject.toml` | add `pydantic-evals` to dev deps. |
| `docs/features/23.2-pydantic-evals.md`, `docs/testing/23.2-pydantic-evals_testing.md` | new. |

### New deps
- `pydantic-evals>=1.107.0` (dev group — offline-only, like the rest of `evals/`).

### Acceptance criteria
- [ ] `make eval-quick` and `make eval` run end-to-end on `pydantic-evals`.
- [ ] accuracy / macro-F1 / ECE / reliability diagram / judge means identical (±float
      noise) to the old harness on the same dataset.
- [ ] Console report unchanged in spirit; `report.print()` also shown.
- [ ] `eval.run` span still carries `eval.accuracy`/`eval.macro_f1`/`eval.ece`.
- [ ] DB persistence still works (no-op without `DATABASE_URL`).
- [ ] ruff / pyright (strict) / pytest / pre-commit green.

### Test plan
- Unit-test evaluators with a **mock LLM** (no Groq): `CategoryCorrect` true/false,
  `JudgeQuality` with a stub judge.
- Test `dataset_loader` parses JSONL into `Case`s with metadata.
- Test the metrics adapter produces the same numbers as before on a fixed mini-report.
- (Real Groq run is a manual smoke via `make eval-quick`, not in pytest.)

### Risks
- Framework report shape vs `compute_report()` input — isolate in the adapter.
- Duplicate Logfire spans (framework + manual) — reconcile and document.
- `pydantic-evals` version pulling an incompatible `pydantic-ai` — pin and verify
  `uv sync` resolves cleanly.

### MANUAL steps
- None required to ship; viewing eval experiments in the Logfire UI is optional.

---

## Phase 3 — Separate capability vs regression suites ✅

**Status:** ✅ delivered. Docs: [feature](../features/23.3-capability-vs-regression.md) ·
[testing](../testing/23.3-capability-vs-regression_testing.md). Split: regression=25
(5×category), capability (edge/english/tone), disjoint; `dataset.jsonl` removed.
**Finding resolved:** `status-003`/`status-004` (stably predicted `shipments`, defensible
ambiguity) were **moved to capability** and replaced in regression with two unambiguous
synthetic status cases — the threshold was never lowered. The gate also guards the error
rate (`passes_gate`: `error_rate ≤ 20%`) so a mostly-errored run can't pass vacuously.

**PR scope:** split one dataset into two purpose-built suites with distinct thresholds.

### Goal
Stop conflating "how good can it get" (capability) with "did we break something"
(regression). Regression must be a stable, high-signal gate; capability tracks trends
on hard/ambiguous cases.

### Design
- `evals/datasets/regression.jsonl` — locked, unambiguous cases (mostly the current
  `easy` ones). Strict threshold (target ≈100% accuracy; any miss is a regression).
- `evals/datasets/capability.jsonl` — hard/ambiguous/multilingual/tone-variant cases.
  Tracked over time; lower/looser threshold, trend-focused.
- Each case keeps its `id`; a `suite` is implied by file. CLI: `--suite
  regression|capability` (or `--dataset PATH` still works). Make targets:
  `make eval-regression`, `make eval-capability`.
- Document selection criteria for each suite in the feature doc.

### Files
| File | Change |
|---|---|
| `evals/datasets/regression.jsonl`, `evals/datasets/capability.jsonl` | new (split from `dataset.jsonl`). |
| `evals/dataset.jsonl` | removed or kept as a symlink/alias to regression for back-compat (decide in PR). |
| `evals/run_evals.py` | `--suite` flag + per-suite thresholds. |
| `Makefile` | `eval-regression`, `eval-capability` targets. |
| `docs/features/23.3-capability-vs-regression.md`, `docs/testing/23.3-*_testing.md` | new. |

### New deps
None.

### Acceptance criteria
- [ ] Two datasets exist; every original case lands in exactly one suite, documented.
- [ ] `make eval-regression` and `make eval-capability` both run.
- [ ] Regression suite passes its strict threshold on a real run (manual smoke).
- [ ] ruff / pyright / pytest / pre-commit green.

### Test plan
- Test the loader resolves both suite paths.
- Test threshold logic (a synthetic report below threshold flags failure).

### Risks
- Choosing which cases are "regression-stable" requires judgment — document rationale;
  borderline cases go to capability.

### MANUAL steps
- Optional: review the proposed split before merge (you may want certain cases moved).

---

## Phase 4 — Multi-run + pass^k ✅

**Status:** ✅ delivered. Docs: [feature](../features/23.4-multi-run-passk.md) ·
[testing](../testing/23.4-multi-run-passk_testing.md). `--repeat K` via the framework's
`repeat=`; pass^k from `case_groups()`; `make eval-passk K=5`; span `eval.repeat`/
`eval.pass_hat_k`. Live-smoke verified (5×3 prices → pass^3 100%).

**PR scope:** run each case k times and report pass^k alongside accuracy.

### Goal
Surface nondeterminism (temperature 0.2 ⇒ flaky cases) that single-run accuracy hides.

### Design
- Use the framework's multi-run: `dataset.evaluate(task, repeat=k)`.
- Compute **pass^k** from `report.case_groups()`: per case, `pass^k = 1` iff **all k**
  runs are correct, else `0` (stricter than accuracy). Report dataset-level
  `mean(pass^k)`, plus a **flakiness list** (cases correct on some-but-not-all runs).
- CLI `--repeat K` (default 1 → current behavior). Make target `make eval-passk K=5`.
- Add `eval.pass_hat_k` and `eval.repeat` to the `eval.run` span.

### Files
| File | Change |
|---|---|
| `evals/run_evals.py` | `--repeat`; pass^k aggregation from `case_groups()`; report section. |
| `evals/metrics.py` | `compute_pass_hat_k(...)` helper. |
| `Makefile` | `eval-passk` target. |
| `docs/features/23.4-multi-run-passk.md`, `docs/testing/23.4-*_testing.md` | new. |

### New deps
None (multi-run is in `pydantic-evals`).

### Acceptance criteria
- [ ] `--repeat K` runs each case K times.
- [ ] Report shows `pass^k` and a flakiness list.
- [ ] `eval.pass_hat_k` / `eval.repeat` on the span.
- [ ] `pass_hat_k <= accuracy` invariant holds (unit-tested).
- [ ] ruff / pyright / pytest / pre-commit green.

### Test plan
- Unit-test `compute_pass_hat_k` on synthetic grouped results (all-pass, mixed,
  all-fail) — no Groq.
- Test the invariant `pass^k ≤ accuracy`.

### Risks
- Real run cost: k× Groq calls. Mitigate with semaphore/`max_concurrency` and a small
  default (k=1); document free-tier impact.

### MANUAL steps
None.

---

## Phase 5 — Judge with "Unknown" output ✅

**Status:** ✅ delivered. Docs: [feature](../features/23.5-judge-unknown.md) ·
[testing](../testing/23.5-judge-unknown_testing.md). `JudgeScore.verdict` +
`judge_unknown_rate` (means over assessable only); verdict carried as a report label;
`--judge-sample N` → `evals/calibration/*.jsonl` (gitignored). Live-smoke verified.

**PR scope:** let the judge abstain to reduce hallucinated scores; leave a seam for
human calibration.

### Goal
A judge forced to score always invents a number. Allowing "Unknown" raises trust and
exposes cases that need human eyes.

### Design
- Extend `JudgeScore` with an abstain path. Option A (chosen): add
  `verdict: Literal["assessable", "unknown"]` plus keep numeric fields; when
  `unknown`, scores are ignored by aggregation and the case is counted in an
  **`unknown_rate`** metric. Add an optional `reason: str` for the judge's rationale
  (used by the spot-check export).
- Update `_JUDGE_SYSTEM_PROMPT` rubric: explicit instruction to return `unknown` when it
  cannot fairly assess (e.g., reply depends on data the judge can't see) instead of
  guessing.
- **Human calibration seam:** `--judge-sample N` exports N judged cases (email, reply,
  scores, reason) to `evals/calibration/<timestamp>.jsonl` for offline human spot-check.
  No automated scoring of the human labels yet — just the artifact.
- Metrics: report `unknown_rate`; exclude `unknown` from judge means.

### Files
| File | Change |
|---|---|
| `evals/schemas.py` | `JudgeScore.verdict` + optional `reason`. |
| `evals/judge.py` | rubric update for the abstain option. |
| `evals/metrics.py` | `unknown_rate`; exclude unknowns from means. |
| `evals/run_evals.py` | `--judge-sample N` export; report `unknown_rate`. |
| `docs/features/23.5-judge-unknown.md`, `docs/testing/23.5-*_testing.md` | new. |

### New deps
None.

### Acceptance criteria
- [ ] Judge can return `unknown`; such cases excluded from means and counted in
      `unknown_rate`.
- [ ] `--judge-sample N` writes a valid JSONL artifact.
- [ ] Backward-compatible: existing judged metrics unchanged when no unknowns.
- [ ] ruff / pyright / pytest / pre-commit green.

### Test plan
- Unit-test metrics with mixed `assessable`/`unknown` `JudgeScore`s (means exclude
  unknowns; `unknown_rate` correct).
- Test the sample export writes parseable JSONL (mock judge, no Groq).

### Risks
- Judge over-abstaining (high `unknown_rate`) — surface the rate prominently; rubric
  tuned to abstain only when genuinely unable.

### MANUAL steps
- **You:** periodically spot-check the `evals/calibration/*.jsonl` artifact to validate
  judge quality (human-in-the-loop). This is an ongoing manual review, not a code gate.

---

## Phase 6 — Online evals on live `/triage` ✅

**Status:** ✅ delivered. Docs: [feature](../features/23.6-online-evals.md) ·
[testing](../testing/23.6-online-evals_testing.md). `Agent(capabilities=[OnlineEvaluation])`
confirmed on pydantic-ai 1.104; 3 cheap evaluators (output non-empty, language match,
confidence range); off by default + `online_eval_*` settings; live-smoke verified
(enabled, `/triage` output + latency unchanged). `pydantic-evals` is now a runtime dep.

**PR scope:** attach cheap, non-blocking evaluators to the production triage agent.

### Goal
Catch quality drift in production (empty outputs, wrong language, out-of-range
confidence) without a separate eval run and without degrading `/triage`.

### Design
- Attach `OnlineEvaluation` to the triage `Agent` via `capabilities=[...]`
  (`from pydantic_evals.online_capability import OnlineEvaluation`).
- **Cheap evaluators only** (no LLM calls): `OutputNotEmpty` (draft non-empty),
  `LanguageMatches` (heuristic: input vs output language, e.g. langid-free cheap check
  / character-set heuristic), `ConfidenceInRange` (0 ≤ confidence ≤ 1, and optionally a
  sane lower band).
- `OnlineEvalConfig(default_sample_rate=settings.online_eval_sample_rate)` and a
  concurrency cap so production latency is unaffected; the capability dispatches
  evaluators **asynchronously after the run** (non-blocking).
- `config.py`: `online_eval_enabled: bool = False`, `online_eval_sample_rate: float =
  0.05`, `online_eval_max_concurrency: int = 2`. Disabled by default; opt-in per env.
- Results surface as OTel `gen_ai.evaluation.result` events in Logfire.

### Files
| File | Change |
|---|---|
| `email_triage/services/llm.py` | wire `capabilities=[OnlineEvaluation(...)]` when enabled. |
| `email_triage/evals_online.py` | new — the 3 cheap evaluators + config builder. |
| `email_triage/config.py` | `online_eval_*` settings. |
| `pyproject.toml` | move `pydantic-evals` to **main** deps (now imported by the app), or add a runtime extra — decide in PR. |
| `tests/test_online_evals.py` | new. |
| `docs/features/23.6-online-evals.md`, `docs/testing/23.6-*_testing.md` | new. |

### New deps
- Promote `pydantic-evals>=1.107.0` to a runtime dependency (it now runs in-process).
- **Verify** installed `pydantic-ai-slim` supports `Agent(capabilities=[...])`; if not,
  bump `pydantic-ai-slim` (record the exact minimum version in the PR).

### Acceptance criteria
- [ ] With `online_eval_enabled=False` (default), `/triage` behaves exactly as today.
- [ ] With it enabled, the 3 evaluators run on a sampled fraction, asynchronously, with
      no measurable latency regression (TTFT smoke unchanged).
- [ ] Evaluator functions are pure and unit-tested without Groq.
- [ ] ruff / pyright / pytest / pre-commit green.

### Test plan
- Unit-test each evaluator directly (empty vs non-empty, matching vs mismatched
  language, in/out-of-range confidence).
- Test the capability is only attached when enabled (feature-flag test).
- Test `/triage` still returns correct output with online evals enabled (mock LLM).

### Risks
- **`Agent(capabilities=...)` support** in installed `pydantic-ai-slim` 1.104 is
  unconfirmed — Phase 0 flagged this. First task in the PR: verify; bump if needed.
- Production latency: keep sample_rate low + async dispatch + concurrency cap; verify
  with `make ttft`.
- `pydantic-evals` becoming a runtime dep increases the image — acceptable; note it.

### MANUAL steps
- **You:** set `ONLINE_EVAL_ENABLED=true` (and tune `ONLINE_EVAL_SAMPLE_RATE`) in the
  deploy env when ready. Code ships disabled-by-default and fully tested.

---

## Phase 7 — Balance dataset + document provenance ✅

**Status:** ✅ delivered. Docs: [feature](../features/23.7-dataset-balance.md) ·
[testing](../testing/23.7-dataset-balance_testing.md). `EvalCase.source` required;
regression 5×5=25, capability balanced to 4×5=20 (+5 `synth-*`); all 45 `synthetic`
(0 real — no production corpus yet); `Source` line + `--filter source=`.

**PR scope:** equalize per-category counts per suite and record each case's origin.

### Goal
Remove category imbalance (currently 8/9/8/7/8) that skews macro-F1, and make
real-vs-synthetic provenance auditable.

### Design
- Add `source: Literal["real", "synthetic"]` to `EvalCase` (backfill all existing
  cases; default documented). Optionally add `provenance_note`.
- Rebalance each suite to an equal per-category count; add cases as needed (synthetic,
  clearly labeled) to fill gaps. **Categories themselves are NOT touched.**
- Document the count matrix (category × suite × source) in the feature doc.

### Files
| File | Change |
|---|---|
| `evals/schemas.py` | `EvalCase.source` (+ optional note). |
| `evals/datasets/*.jsonl` | rebalanced, `source` on every case. |
| `evals/run_evals.py` | optional `--by-source` breakdown in report. |
| `docs/features/23.7-dataset-balance.md`, `docs/testing/23.7-*_testing.md` | new. |

### New deps
None.

### Acceptance criteria
- [ ] Every case has a valid `source`.
- [ ] Each suite is balanced per category (documented matrix).
- [ ] Loader/validation rejects a case missing `source` or category.
- [ ] ruff / pyright / pytest / pre-commit green.

### Test plan
- Test schema rejects missing/invalid `source`.
- Test a balance-assertion helper (per-category counts equal within a suite).

### Risks
- Synthetic cases can leak distributional bias — label them and keep capability/
  regression separation so synthetic noise doesn't pollute the regression gate.

### MANUAL steps
- Optional: review synthetic additions for realism before merge.

---

## Design decisions (cross-cutting)

| Decision | Discarded alternative | Reason |
|---|---|---|
| Resolve prompt once in lifespan, inject via `Depends` | `.get()` per request | Avoids any per-request remote/lookup cost; matches the constraint. |
| Code `default=` is canonical source of truth | Logfire UI is source of truth | Critical path must survive Logfire outage; code review stays the gate for categories. |
| Keep custom console report **and** `report.print()` | Drop custom report | ECE + reliability diagram + misclassified table are domain-specific and not in the framework table. |
| Reuse `JudgeAgent` inside a custom `Evaluator` | Framework `LLMJudge` | Task requirement; keeps our strict rubric + Groq/$0 model. |
| `pydantic-evals` dev-only until Phase 6 | Runtime dep from the start | Stays offline until online evals genuinely need it in-process. |
| pass^k = "all k runs correct" | pass@k (any of k) | We want reliability (stricter), not best-of-k. |
| Online evals off by default, low sample_rate | Always on | Protect `/triage` latency and free-tier budget; opt-in per env. |
| Judge `verdict=unknown` over forced score | Always emit 1–5 | Reduces hallucinated scores; exposes cases for human calibration. |

## Global risks / open questions

- **`pydantic-ai-slim` `capabilities=` support** (Phase 6) — must verify/bump.
- **Logfire span duplication** (framework vs manual `eval.run`) — reconcile in Phase 2.
- **Real Groq cost** for multi-run/judge — mitigated by concurrency caps + small
  defaults; all in offline `make eval*`, never in pytest.
- **Judge over-abstain** — monitor `unknown_rate`.

## Consolidated MANUAL steps (yours)

1. **Phase 1 — Logfire UI:** create prompt `prompt__email_triage_system`, add first
   version (current `SYSTEM_PROMPT`), promote `production` label.
2. **Phase 3 (optional):** review the capability/regression split before merge.
3. **Phase 5 — ongoing:** spot-check `evals/calibration/*.jsonl` judge samples.
4. **Phase 6 — deploy env:** set `ONLINE_EVAL_ENABLED=true` + tune sample rate when ready.
5. **Phase 7 (optional):** review synthetic dataset additions.

> Every phase ships and is fully tested with its fallback **before** any of the above;
> none of these manual steps block code delivery.

## Execution protocol (Stage B — after your approval)

Per phase, in order, one PR at a time:
1. `uv run ruff format` + `uv run ruff check --fix`
2. `uv run pyright` (strict) → green
3. add/update tests, `uv run pytest` (no real Groq)
4. `uv run pre-commit run --all-files` (no `--no-verify`)
5. write `docs/features/23.N-*.md` + `docs/testing/23.N-*_testing.md`
6. show the phase diff summary and **wait for your OK** before the next phase.

## Done when (umbrella)
- [ ] All 7 phases merged, each with feature + testing docs.
- [ ] `docs/exec-plans/README.md` updated with entry #23.
- [ ] Final checklist delivered: acceptance criteria per phase + ruff/pyright/pytest/
      pre-commit status + outstanding manual steps.
