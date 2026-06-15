# 13. Accuracy Evaluation — Golden Dataset + Metrics + LLM Judge

**Status:** ✅ delivered
**Estimate:** 3 hrs

## Intent

The product classifies emails into 5 categories and generates draft replies, but there is no mechanism to measure how well it does either task. Without quality metrics it is impossible to know whether a change to the model, prompt, or temperature improved or degraded accuracy. This plan creates offline evaluation infrastructure:

- A **golden dataset** of 40 hand-labeled cases covering all categories, languages, and difficulty levels.
- **Classification metrics**: accuracy, per-category precision / recall / F1, macro-F1, and a 5×5 confusion matrix.
- **Confidence calibration**: Expected Calibration Error (ECE) and an ASCII reliability diagram.
- An **LLM-as-judge** agent that scores the quality of each generated draft reply.
- **Logfire integration** that persists every eval run as a span tree, enabling regression detection over time in the Logfire UI.
- A clean **CLI report** (box-drawing + ANSI colors) printed after every run.
- `make eval` / `make eval-quick` targets so the workflow matches the rest of the project.

All documentation, code comments, and CLI output produced by this plan are written in **English**.

## Scope

**Included:**
- `evals/` directory with dataset, schemas, metrics, judge, and runner.
- `make eval` (full run: classification + judge) and `make eval-quick` (classification only).
- Logfire `eval.run` root span + `eval.case` child spans with all aggregate and per-case attributes.
- CLAUDE.md rule: all future docs and code text must be in English.
- `docs/exec-plans/README.md` update.

**Out of scope:**
- Running evals in CI (requires real API calls; offline-only for now).
- A web UI for browsing eval results (Logfire UI covers this).
- Eval of the streaming endpoint (only the sync `/triage` path is evaluated).
- Adding new categories (contract is frozen in `schemas.py`).

## Concrete changes

| File | Change |
|---|---|
| `evals/schemas.py` | `EvalCase`, `EvalResult`, `JudgeScore` — Pydantic models. |
| `evals/dataset.jsonl` | 40 golden cases (8 per category). JSONL, one object per line. |
| `evals/metrics.py` | `compute_report()` → accuracy, F1 per category, macro-F1, ECE (10 bins), reliability diagram ASCII. Pure Python, no new deps. |
| `evals/judge.py` | Pydantic AI agent using `llama-3.3-70b-versatile` via Groq. Emits `JudgeScore` (relevance, language_match, tone, correctness, overall). |
| `evals/run_evals.py` | Async runner with `asyncio.gather` + semaphore(5). CLI flags: `--no-judge`, `--filter key=val`, `--dataset PATH`. Prints CLI report and logs to Logfire. |
| `Makefile` | Add `eval` and `eval-quick` targets. |
| `CLAUDE.md` | Add language rule to "Límites del agente" section. |
| `docs/exec-plans/README.md` | Add entry #13. |
| `docs/features/13-evals.md` | Feature doc. |
| `docs/testing/13-evals_testing.md` | Testing doc. |

No files under `src/` are modified. The runner imports `LLMService` directly from the installed package.

## Dataset design

Format — one JSON object per line:

```jsonl
{"id": "status-001", "subject": "Where is my order?", "sender": "eval@test.com", "body": "I placed order #12345 five days ago and have not received any update.", "expected_category": "status", "language": "en", "difficulty": "easy", "notes": "Clear status inquiry with order number"}
```

**Fields:** `id`, `subject`, `sender` (always `eval@test.com`), `body`, `expected_category`, `language` (`es`|`en`), `difficulty` (`easy`|`medium`|`hard`), `notes`.

**Distribution (40 total):**

| Group | Count | Criteria |
|---|---|---|
| Clear cases | 25 | 5 per category, unambiguous, difficulty=easy |
| Ambiguous / edge | 5 | Multi-intent or borderline between two categories, difficulty=hard |
| English language | 5 | Spread across categories, difficulty=easy or medium |
| Tone / length variants | 5 | Very short, very long, informal, angry — tests robustness |

Language split: ~70 % Spanish / 30 % English.

**Ambiguous cases (examples):**
- "My package arrived but I want to return it because the price dropped" → `refunds` (intent is return, not status)
- "Do you ship for free if I spend over $50?" → `prices` (discount condition, not shipping method)
- "My tracking shows delivered but I never received it" → `status` (order state, not shipping cost)

## Metrics

### Classification

```
accuracy  = correct / total
precision = TP / (TP + FP)          # per category
recall    = TP / (TP + FN)          # per category
f1        = 2 × P × R / (P + R)     # per category
macro_f1  = mean(f1 per category)
```

### Confidence calibration — ECE

Split predictions into 10 equal-width confidence bins [0.0, 0.1), [0.1, 0.2), …, [0.9, 1.0].
For each non-empty bin *b*:

```
ECE = Σ_b  (|b| / n) × |accuracy(b) − confidence(b)|
```

ECE < 0.05 → well-calibrated. ECE > 0.10 → over- or under-confident; consider temperature tuning.

### Reliability diagram

ASCII chart printed below the calibration table. Each row is a bin; bar length represents the gap between confidence and accuracy. Ideal model: all gaps near zero.

## LLM judge

A second Pydantic AI agent, completely independent from the triage agent. Uses the same Groq model and API key — no new credentials.

```python
class JudgeScore(BaseModel):
    relevance: int = Field(ge=1, le=5)    # Does the reply address the email?
    language_match: bool                   # Same language as input?
    tone: int = Field(ge=1, le=5)         # Professional and courteous?
    correctness: int = Field(ge=1, le=5)  # No false or invented claims?
    overall: int = Field(ge=1, le=5)      # Global quality score
```

**Judge input:** email subject + body + generated `draft_reply`. The judge does **not** see the expected category — it evaluates reply quality independently of classification.

**Judge system prompt (abbreviated):**
> You are an expert evaluator of customer support replies for an e-commerce store. Given an incoming email and a draft reply, score the reply on four dimensions (1–5). Be strict: a score of 5 means the reply is perfect with no room for improvement.

## CLI report

Box-drawing characters + ANSI codes. No `rich` dependency.

```
╔══════════════════════════════════════════════════════════════╗
║         Email Triage Eval  ·  2026-06-04  08:32 UTC         ║
╚══════════════════════════════════════════════════════════════╝
  Dataset  evals/dataset.jsonl  (v a3f2b1c9)  ·  40 cases
  Model    llama-3.3-70b-versatile  ·  temperature=0.2

CLASSIFICATION ─────────────────────────────────────────────────
  Accuracy   92.5 %  ████████████████████░  (37 / 40)
  Macro-F1    0.913

  Category        P       R      F1    Support
  ─────────────────────────────────────────────
  status        0.90    1.00   0.95       8
  refunds       0.88    0.88   0.88       8
  availability  1.00    0.88   0.93       8
  shipments     0.88    0.88   0.88       8
  prices        1.00    1.00   1.00       8

CALIBRATION  ───────────────────────────────────────────────────
  ECE  0.041  ✓ well-calibrated

  Confidence  Accuracy  Gap    Count
  0.5–0.6       0.60   +0.05    5   ██
  0.7–0.8       0.80   +0.05    8   ████
  0.8–0.9       0.87   +0.02   15   ███████
  0.9–1.0       0.92   -0.01   12   ██████

LLM JUDGE  ─────────────────────────────────────────────────────
  Overall         4.3 / 5
  Relevance       4.4 / 5
  Language match  97.5 %
  Tone            4.5 / 5
  Correctness     4.1 / 5

MISCLASSIFIED CASES  ───────────────────────────────────────────
  edge-002  expected=refunds    predicted=status    conf=0.71
  hard-004  expected=shipments  predicted=status    conf=0.65
  hard-007  expected=prices     predicted=refunds   conf=0.58

  Logfire  https://logfire.pydantic.dev/org/email-triage/...
══════════════════════════════════════════════════════════════
```

## Logfire integration

The runner configures Logfire independently (same `LOGFIRE_TOKEN` env var used by the API server).

**Root span `eval.run`:**

| Attribute | Value |
|---|---|
| `eval.dataset_version` | SHA256[:8] of the JSONL file |
| `eval.model_id` | Groq model string |
| `eval.n_cases` | Total cases run |
| `eval.accuracy` | Float 0–1 |
| `eval.macro_f1` | Float 0–1 |
| `eval.ece` | Float 0–1 |
| `eval.mean_judge_score` | Float 1–5 (omitted with `--no-judge`) |

**Child span `eval.case` (one per case):**

| Attribute | Value |
|---|---|
| `eval.case_id` | e.g. `status-003` |
| `eval.expected_category` | Ground truth |
| `eval.predicted_category` | Model output |
| `eval.is_correct` | bool |
| `eval.confidence` | Float 0–1 |
| `eval.judge.overall` | Int 1–5 |
| `eval.judge.language_match` | bool |

In Logfire UI: filter spans by `eval.run`, chart `eval.accuracy` or `eval.macro_f1` over time to detect regressions after prompt or model changes.

## Makefile additions

```makefile
eval: ## Run full eval suite (classification + LLM judge). Reads .env
	@export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
	uv run python evals/run_evals.py

eval-quick: ## Run eval — classification only, no LLM judge (2× faster)
	@export $$(grep -v '^#' .env | xargs) 2>/dev/null; \
	uv run python evals/run_evals.py --no-judge
```

## Design decisions

| Decision | Discarded alternative | Reason |
|---|---|---|
| Pure Python metrics | scikit-learn | Avoids a heavy dep; accuracy, F1, and ECE are ~50 lines of math |
| Same Groq model as judge | Stronger model (Claude / GPT-4) | $0 cost; assessing grammar, language, and basic relevance does not require frontier reasoning |
| JSONL for dataset | CSV, YAML | Industry standard for LLM eval datasets; one case per line enables `grep`, `wc -l`, and clean git diffs |
| Logfire for run persistence | Local JSON file | Already in the stack; enables temporal queries and regression charts without new infrastructure |
| Semaphore(5) concurrency | Sequential or unlimited | Groq free-tier RPM; 5 simultaneous calls keeps the full eval under 60 s without hitting limits |
| `--no-judge` flag | Judge always active | Judge doubles LLM call count; fast iteration on prompt changes should not cost double |
| `make eval` / `make eval-quick` | Direct `uv run python …` | Matches existing project UX; `make help` auto-documents every target |
| ANSI codes without `rich` | `rich` library | Report is simple enough to hand-roll; avoids a new dep |

## Risks

- **Groq rate limits during eval run**: with semaphore(5) and 40 cases this is unlikely on free tier. If hit, reduce to semaphore(3) or add a retry with exponential backoff.
- **Judge variance**: the same judge model used for triage may be biased toward its own outputs. Mitigation: the judge system prompt is deliberately strict and uses a 1–5 scale with rubric guidance.
- **Dataset label disagreement**: two humans might label an edge case differently. Mitigation: `notes` field documents the rationale; edge cases are flagged with `difficulty=hard` so they can be filtered out of headline accuracy if needed.
- **Logfire free-tier span volume**: 40 cases × 2 calls each = 80 spans per run. Well within free limits.

## Execution order

1. **Schemas + dataset** (30 min): `evals/schemas.py`, `evals/dataset.jsonl` with all 40 cases.
2. **Metrics** (30 min): `evals/metrics.py` — accuracy, F1, ECE, reliability diagram.
3. **LLM judge** (30 min): `evals/judge.py` with `JudgeScore` output type.
4. **Runner + CLI report** (45 min): `evals/run_evals.py` — concurrency, Logfire, pretty print.
5. **Makefile + CLAUDE.md** (15 min): add targets; add English language rule.
6. **Docs** (20 min): feature doc, testing doc, update exec-plans/README.
7. **Close** (15 min): `make check` (ruff + pyright + existing tests); `make eval-quick` smoke test.

## Done when

- [ ] `evals/dataset.jsonl` has exactly 40 cases covering all 5 categories, both languages, and all 3 difficulty levels
- [ ] `make eval-quick` runs end-to-end without errors and prints the CLI report
- [ ] `make eval` adds LLM judge scores to the report
- [ ] Accuracy ≥ 85 % on the golden dataset
- [ ] ECE < 0.10
- [ ] `eval.run` span visible in Logfire UI with `eval.accuracy`, `eval.macro_f1`, `eval.ece` attributes set
- [ ] `eval.case` child spans visible with `eval.is_correct` and `eval.confidence` for each case
- [ ] `make check` passes (ruff + pyright + all 9 existing tests green)
- [ ] `docs/features/13-evals.md` and `docs/testing/13-evals_testing.md` created
- [ ] `docs/exec-plans/README.md` updated with entry #13
- [ ] CLAUDE.md updated with English language rule
