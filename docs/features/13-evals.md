# 13. Accuracy Evaluation

**Status:** 📋 proposed (see [exec plan](../exec-plans/13-evals.md))

## What this is

An offline evaluation harness for measuring the accuracy of the email triage classifier and the quality of its generated draft replies. It runs against the real LLM — no mocking — so results reflect actual production behavior.

## How to run

```bash
make eval-quick    # classification metrics only (~30s, 40 LLM calls)
make eval          # full run including LLM judge (~60s, 80 LLM calls)

# Filter by difficulty
make eval-quick FILTER="--filter difficulty=hard"

# Custom dataset path
uv run python -m evals.run_evals --dataset path/to/dataset.jsonl --no-judge
```

## Dataset (`evals/dataset.jsonl`)

40 hand-labeled cases covering all 5 triage categories. One JSON object per line.

| Group | Count | Description |
|---|---|---|
| Clear cases | 25 | 5 per category, unambiguous, Spanish, difficulty=easy |
| Ambiguous / edge | 5 | Multi-intent or borderline, difficulty=hard |
| English language | 5 | One per category, tests multilingual support |
| Tone / length variants | 5 | Very short, angry, informal, very long formal, English frustrated |

**Case schema:**

```json
{
  "id": "status-001",
  "subject": "¿Cuándo llega mi pedido?",
  "sender": "eval@test.com",
  "body": "Hice el pedido #4521 hace 5 días y no he recibido ninguna actualización.",
  "expected_category": "status",
  "language": "es",
  "difficulty": "easy",
  "notes": "Clear status inquiry with order number"
}
```

## Metrics

### Classification

| Metric | Description | Target |
|---|---|---|
| Accuracy | % correct categories | ≥ 85 % |
| Macro-F1 | Average F1 across all 5 categories | ≥ 0.80 |
| Per-category F1 | Precision, recall, F1 per class | Surfaced in report |
| Confusion matrix | 5×5 matrix (expected vs predicted) | For qualitative analysis |

### Confidence calibration — ECE

Expected Calibration Error: measures how aligned confidence scores are with actual accuracy. A well-calibrated model that says "90 % confident" should be correct ~90 % of the time.

| ECE range | Interpretation |
|---|---|
| < 0.05 | Well-calibrated ✓ |
| 0.05–0.10 | Acceptable |
| > 0.10 | Poorly calibrated — consider adjusting temperature |

### LLM Judge (full run only)

A second Pydantic AI agent (same Groq model) evaluates each generated draft reply on:

| Dimension | Scale | What it measures |
|---|---|---|
| Relevance | 1–5 | Does the reply address the email? |
| Language match | bool | Same language as input? |
| Tone | 1–5 | Professional and courteous? |
| Correctness | 1–5 | No false or invented claims? |
| Overall | 1–5 | Global quality score |

The judge does **not** see the expected category — it evaluates reply quality independently.

## Logfire integration

Every eval run creates an `eval.run` span with aggregate metrics and 40 child `eval.case` spans. This enables tracking accuracy over time in Logfire UI:

- Filter spans by `eval.run` → chart `eval.accuracy` across runs
- Detect regressions after prompt or model changes

## CLI report sample

```
╔══════════════════════════════════════════════════════════════════╗
║         Email Triage Eval  ·  2026-06-04  10:15 UTC             ║
╚══════════════════════════════════════════════════════════════════╝
  Dataset  evals/dataset.jsonl  (v a3f2b1c9)  ·  40 cases  28.4s
  Model    llama-3.3-70b-versatile

CLASSIFICATION ────────────────────────────────────────────────────
  Accuracy   92.5 %  ████████████████████░░  (37 / 40)
  Macro-F1   0.913
  ...

CALIBRATION ───────────────────────────────────────────────────────
  ECE  0.041  ✓ well-calibrated
  ...

MISCLASSIFIED CASES ───────────────────────────────────────────────
  edge-002          expected=prices       predicted=shipments  conf=0.71
  ...
```

## File structure

```
evals/
├── __init__.py
├── dataset.jsonl      # 40 golden cases
├── schemas.py         # EvalCase, EvalResult, JudgeScore
├── metrics.py         # compute_report(), ECE, calibration bins
├── judge.py           # JudgeAgent — Pydantic AI judge
└── run_evals.py       # CLI runner — entry point for make targets
```
