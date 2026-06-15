# Testing Guide — 13. Accuracy Evaluation

## Prerequisites

- `.env` with `GROQ_API_KEY` set (same key used by the API server).
- `uv sync` completed.
- Server does **not** need to be running — the eval runner calls `LLMService` directly.

## TC-01 — Quick run (classification only)

**Goal:** Verify the runner completes without errors and prints a valid report.

```bash
make eval-quick
```

**Expected:**
- Exits with code 0.
- Prints the full CLI report with box-drawing border.
- `Accuracy` line shows a percentage and correct count (e.g. `92.5 %  (37 / 40)`).
- `Macro-F1` is between 0.00 and 1.00.
- `ECE` is between 0.00 and 1.00 with a calibration label.
- `CLASSIFICATION` section shows all 5 categories with P, R, F1 values.
- No `⚠ errored` warning (all 40 cases succeed).
- Completes in under 60 seconds.

**Quality gate:** Accuracy ≥ 85 %. If below, review misclassified cases and consider prompt tuning.

---

## TC-02 — Full run with LLM judge

**Goal:** Verify judge scores are computed and appended to the report.

```bash
make eval
```

**Expected:**
- Everything from TC-01, plus:
- `LLM JUDGE` section appears in the report with Overall, Relevance, Language match, Tone, and Correctness scores.
- All scores are between 1.0 and 5.0 (or 0–100 % for language match).
- Language match ≥ 90 % (the model should reply in the same language as the input for most cases).

---

## TC-03 — Filter by difficulty

**Goal:** Verify the `--filter` flag works and only hard cases are evaluated.

```bash
uv run python -m evals.run_evals --no-judge --filter difficulty=hard
```

**Expected:**
- Report header shows `10 cases` (5 edge + 5 tone-002/004 which are hard/medium... actually 5 edge + tone-002 = 6 hard cases).
- Wait — check: `difficulty=hard` should match `edge-001` through `edge-005` (5) and `tone-002` (1) = 6 cases.
- Exits with code 0.

> To check exact count: `grep '"difficulty": "hard"' evals/dataset.jsonl | wc -l`

---

## TC-04 — Logfire span verification

**Goal:** Verify that eval runs appear in Logfire UI with the correct attributes.

1. Run `make eval-quick` with `LOGFIRE_TOKEN` set in `.env`.
2. Open https://logfire.pydantic.dev and navigate to the project.
3. Filter spans by name `eval.run`.
4. Verify the span has these attributes:
   - `eval.dataset_version` — 8-character hex string.
   - `eval.model_id` — `llama-3.3-70b-versatile`.
   - `eval.n_cases` — `40`.
   - `eval.accuracy` — float in [0, 1].
   - `eval.macro_f1` — float in [0, 1].
   - `eval.ece` — float in [0, 1].
5. Expand the span to see 40 `eval.case` child spans.
6. Verify each child has `eval.case_id`, `eval.expected_category`, `eval.predicted_category`, `eval.is_correct`, `eval.confidence`.

---

## TC-05 — Misclassified cases review

**Goal:** Qualitatively review which cases the model gets wrong.

1. Run `make eval-quick` and look at the `MISCLASSIFIED CASES` section.
2. For each misclassified case, read the `notes` field in `evals/dataset.jsonl` to understand why.
3. If a clear case (difficulty=easy) is misclassified, the system prompt likely needs tuning.
4. If only hard/edge cases are misclassified, that is expected behavior.

---

## TC-06 — Regression check after prompt change

**Goal:** Confirm eval catches quality regressions.

1. Modify `SYSTEM_PROMPT` in `src/email_triage/services/llm.py` to be intentionally vague (e.g. remove category definitions).
2. Run `make eval-quick`.
3. Verify accuracy drops significantly (expected: < 50 %).
4. Restore the original prompt.
5. Run `make eval-quick` again — accuracy should return to ≥ 85 %.

---

## TC-07 — Dataset integrity check

**Goal:** Verify the dataset has exactly 40 cases and all required fields.

```bash
wc -l evals/dataset.jsonl
# Expected: 40

python3 -c "
import json
from pathlib import Path
cases = [json.loads(l) for l in Path('evals/dataset.jsonl').read_text().splitlines()]
categories = {c['expected_category'] for c in cases}
assert categories == {'status','refunds','availability','shipments','prices'}, f'Missing categories: {categories}'
assert len(cases) == 40, f'Expected 40 cases, got {len(cases)}'
langs = [c['language'] for c in cases]
assert 'en' in langs, 'No English cases found'
print(f'OK — {len(cases)} cases, categories: {sorted(categories)}')
"
```

---

## Known limitations

- The eval runner calls the real Groq API — it is not free. At ~40 calls, it is well within the free tier, but avoid running it in tight loops.
- Confidence scores from Groq may vary slightly across runs due to `temperature=0.2`. ECE can fluctuate ±0.02 between runs.
- The LLM judge uses the same model as the triage agent, which may introduce a slight self-assessment bias.
