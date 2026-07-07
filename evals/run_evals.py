from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import logfire
from email_triage.config import Settings
from email_triage.db.engine import init_db
from email_triage.db.repos.evals import persist_eval_run
from email_triage.schemas import TriageRequest, TriageResponse
from email_triage.services.llm import LLMService
from pydantic_evals.evaluators import Evaluator
from pydantic_evals.reporting import ReportCase

from evals.dataset_loader import build_dataset, load_cases, load_suite, suite_version
from evals.evaluators import CategoryCorrect, JudgeQuality, judge_score_from_case, set_judge
from evals.judge import JudgeAgent
from evals.metrics import EvalReport, compute_pass_hat_k, compute_report
from evals.schemas import CaseMeta, EvalCase, EvalResult

# Kept modest so bursts stay under Groq's free-tier TPM limit; 429s that still
# slip through are retried with backoff by the shared Groq client (services/groq.py).
_MAX_CONCURRENCY = 3

# Per-suite accuracy gates. regression must stay near-perfect; capability is harder and
# trend-tracked; "all" / custom datasets use the plan-13 headline target.
SUITE_THRESHOLDS: dict[str, float] = {
    "regression": 0.95,
    "capability": 0.70,
    "all": 0.85,
}
_DEFAULT_THRESHOLD = 0.85
# A run where too many cases errored is inconclusive: accuracy is computed only over
# survivors, so without this guard a mostly-errored run could pass the gate vacuously.
_MAX_ERROR_RATE = 0.2


def passes_threshold(accuracy: float, threshold: float) -> bool:
    return accuracy >= threshold


def passes_gate(accuracy: float, threshold: float, error_rate: float) -> bool:
    """The gate requires both enough accuracy AND few enough errored cases."""
    return passes_threshold(accuracy, threshold) and error_rate <= _MAX_ERROR_RATE


# ── ANSI helpers ─────────────────────────────────────────────────────────────
_B = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_RST = "\033[0m"

_W = 66  # report body width


def _bar(value: float, width: int = 22) -> str:
    filled = round(value * width)
    return f"{_GREEN}{'█' * filled}{_DIM}{'░' * (width - filled)}{_RST}"


def _c_acc(acc: float) -> str:
    col = _GREEN if acc >= 0.90 else (_YELLOW if acc >= 0.75 else _RED)
    return f"{col}{acc * 100:.1f} %{_RST}"


def _c_f1(f1: float) -> str:
    col = _GREEN if f1 >= 0.90 else (_YELLOW if f1 >= 0.75 else _RED)
    return f"{col}{f1:.3f}{_RST}"


def _c_ece(ece: float) -> str:
    if ece < 0.05:
        return f"{_GREEN}{ece:.3f}  ✓ well-calibrated{_RST}"
    if ece < 0.10:
        return f"{_YELLOW}{ece:.3f}  ~ acceptable{_RST}"
    return f"{_RED}{ece:.3f}  ✗ poorly calibrated{_RST}"


def _sec(title: str) -> str:
    line = "─" * (_W - len(title) - 1)
    return f"\n{_B}{title} {line}{_RST}"


# ── Report printer ────────────────────────────────────────────────────────────


def print_report(
    results: list[EvalResult],
    report: EvalReport,
    dataset_label: str,
    model_id: str,
    dataset_ver: str,
    elapsed: float,
) -> None:
    border = "═" * _W
    now = datetime.now(UTC).strftime("%Y-%m-%d  %H:%M UTC")

    print(f"\n{_B}╔{border}╗{_RST}")
    title = f"Email Triage Eval  ·  {now}"
    pad = (_W - len(title)) // 2
    print(f"{_B}║{' ' * pad}{title}{' ' * (_W - len(title) - pad)}║{_RST}")
    print(f"{_B}╚{border}╝{_RST}")

    n_cases = len(results)
    n_errors = sum(1 for r in results if r.error)
    print(
        f"  {_DIM}Dataset{_RST}  {dataset_label}"
        f"  {_DIM}(v {dataset_ver}){_RST}  ·  {n_cases} cases  {elapsed:.1f}s"
    )
    print(f"  {_DIM}Model  {_RST}  {model_id}")
    n_real = sum(1 for r in results if r.case.source == "real")
    n_synth = sum(1 for r in results if r.case.source == "synthetic")
    print(f"  {_DIM}Source {_RST}  real {n_real}  ·  synthetic {n_synth}")
    if n_errors:
        print(f"  {_YELLOW}⚠  {n_errors} case(s) errored and were excluded from metrics{_RST}")

    # Classification
    print(_sec("CLASSIFICATION"))
    correct = sum(1 for r in results if r.is_correct)
    acc = report["accuracy"]
    print(f"  Accuracy   {_c_acc(acc)}  {_bar(acc)}  ({correct} / {n_cases})")
    print(f"  Macro-F1   {_c_f1(report['macro_f1'])}")
    print()
    print(f"  {'Category':<14} {'P':>5}   {'R':>5}   {'F1':>5}   {'Support':>7}")
    print(f"  {'─' * 46}")
    for cat, m in report["per_category"].items():
        print(
            f"  {cat:<14} {m['precision']:>5.2f}   {m['recall']:>5.2f}   "
            f"{_c_f1(m['f1'])}   {m['support']:>7}"
        )

    # Calibration
    print(_sec("CALIBRATION"))
    print(f"  ECE  {_c_ece(report['ece'])}")
    print()
    if report["calibration_bins"]:
        print(f"  {'Conf range':<12} {'Acc':>5}  {'Gap':>6}  {'Count':>5}")
        for b in report["calibration_bins"]:
            gap = abs(b["gap"])
            gap_col = _GREEN if gap < 0.05 else (_YELLOW if gap < 0.10 else _RED)
            bar_len = min(int(abs(b["gap"]) * 60), 12)
            bar_char = "▲" if b["gap"] > 0 else "▼"
            bar = bar_char * bar_len
            print(
                f"  {b['label']:<12} {b['accuracy']:>5.2f}  {gap_col}{b['gap']:>+6.2f}{_RST}"
                f"  {b['count']:>5}  {_DIM}{bar}{_RST}"
            )

    # Judge
    if report["judge_unknown_rate"] is not None:
        print(_sec("LLM JUDGE"))
        jd = report["judge_detail"]
        if jd is not None:
            print(f"  Overall          {jd['mean_overall']:.1f} / 5")
            print(f"  Relevance        {jd['mean_relevance']:.1f} / 5")
            lm_pct = jd["language_match_pct"] * 100
            lm_col = _GREEN if lm_pct >= 95 else _YELLOW
            print(f"  Language match   {lm_col}{lm_pct:.1f} %{_RST}")
            print(f"  Tone             {jd['mean_tone']:.1f} / 5")
            print(f"  Correctness      {jd['mean_correctness']:.1f} / 5")
        ur_pct = report["judge_unknown_rate"] * 100
        ur_col = _GREEN if ur_pct < 10 else (_YELLOW if ur_pct < 25 else _RED)
        print(f"  Unknown rate     {ur_col}{ur_pct:.1f} %{_RST}  {_DIM}(excluded from means){_RST}")

    # Misclassified
    wrong = [r for r in results if not r.is_correct and not r.error]
    if wrong:
        print(_sec("MISCLASSIFIED CASES"))
        for r in wrong:
            conf_col = _RED if r.confidence < 0.70 else _YELLOW
            print(
                f"  {_DIM}{r.case.id:<16}{_RST}"
                f"  expected={_GREEN}{r.case.expected_category:<12}{_RST}"
                f"  predicted={_RED}{r.predicted_category:<12}{_RST}"
                f"  conf={conf_col}{r.confidence:.2f}{_RST}"
            )

    print(f"\n  {_DIM}Logfire  https://logfire.pydantic.dev/{_RST}")
    print(f"{_B}{'═' * (_W + 2)}{_RST}\n")


# ── Core logic ────────────────────────────────────────────────────────────────


CALIBRATION_DIR = Path(__file__).parent / "calibration"


def _dataset_version(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def export_calibration_sample(results: list[EvalResult], n: int, out_dir: Path) -> Path:
    """Write the first ``n`` judged cases (email, reply, judge verdict/scores/reason) to a
    timestamped JSONL for offline human spot-check. ``human_verdict`` is left null for the
    reviewer to fill — this is the seam for human calibration, not automated scoring."""
    judged = [r for r in results if r.judge_score is not None][:n]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in judged:
            js = r.judge_score
            assert js is not None  # filtered above
            fh.write(
                json.dumps(
                    {
                        "case_id": r.case.id,
                        "subject": r.case.subject,
                        "body": r.case.body,
                        "draft_reply": r.draft_reply,
                        "judge_verdict": js.verdict,
                        "judge_overall": js.overall,
                        "judge_relevance": js.relevance,
                        "judge_tone": js.tone,
                        "judge_correctness": js.correctness,
                        "judge_language_match": js.language_match,
                        "judge_reason": js.reason,
                        "human_verdict": None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return path


def results_from_report(
    report_cases: list[ReportCase[TriageRequest, TriageResponse, CaseMeta]],
    cases_by_id: dict[str, EvalCase],
) -> list[EvalResult]:
    """Adapt framework report cases → existing ``EvalResult`` list so ``metrics.py``
    (accuracy / macro-F1 / ECE / reliability / judge means) keeps working unchanged.

    A case whose task raised is dropped from ``report.cases`` by the framework; those
    are re-added below with ``error`` set so they are counted/warned but excluded from
    metrics, matching the previous behavior."""
    results: list[EvalResult] = []
    present: set[str] = set()
    for rc in report_cases:
        # With repeat>1 the framework names runs "<id> [i/k]" and puts the stable id in
        # source_case_name; at repeat=1 source_case_name is None and name is the id.
        case_id = rc.source_case_name or rc.name
        present.add(case_id)
        out = rc.output
        case = cases_by_id[case_id]
        results.append(
            EvalResult(
                case=case,
                predicted_category=out.category.value,
                confidence=out.confidence,
                draft_reply=out.draft_reply,
                is_correct=out.category.value == case.expected_category,
                judge_score=judge_score_from_case(rc),
            )
        )
    for case_id, case in cases_by_id.items():
        if case_id not in present:
            results.append(
                EvalResult(
                    case=case,
                    predicted_category="status",
                    confidence=0.0,
                    draft_reply="",
                    is_correct=False,
                    error="task failed",
                )
            )
    return results


async def run(
    suite: str,
    dataset_path: Path | None,
    filters: dict[str, str],
    use_judge: bool,
    check: bool,
    repeat: int,
    judge_sample: int,
) -> None:
    if dataset_path is not None:
        cases = load_cases(dataset_path, filters)
        dataset_label = str(dataset_path)
        dv = _dataset_version(dataset_path)
        threshold = _DEFAULT_THRESHOLD
    else:
        cases = load_suite(suite, filters)
        dataset_label = f"suite:{suite}"
        dv = suite_version(suite)
        threshold = SUITE_THRESHOLDS[suite]

    if not cases:
        print("No cases matched the given filters.", file=sys.stderr)
        sys.exit(1)

    settings = Settings()  # type: ignore[call-arg]
    logfire.configure(send_to_logfire="if-token-present", service_name="email-triage-eval")

    if settings.database_url:
        init_db(settings.database_url)

    llm = LLMService(api_key=settings.groq_api_key, model=settings.groq_model)
    judge = JudgeAgent(api_key=settings.groq_api_key) if use_judge else None
    set_judge(judge)

    evaluators: list[Evaluator[TriageRequest, TriageResponse, CaseMeta]] = [CategoryCorrect()]
    if use_judge:
        evaluators.append(JudgeQuality())
    dataset = build_dataset(cases, evaluators)
    cases_by_id = {c.id: c for c in cases}

    async def task(req: TriageRequest) -> TriageResponse:
        return await llm.triage(req)

    with logfire.span(
        "eval.run",
        dataset_version=dv,
        model_id=settings.groq_model,
        n_cases=len(cases),
        suite=suite if dataset_path is None else "custom",
    ) as span:
        t0 = time.perf_counter()
        # Framework emits per-case spans (nested under eval.run) and an experiment tree
        # in Logfire — these replace the old manual eval.case loop.
        eval_report = await dataset.evaluate(
            task, max_concurrency=_MAX_CONCURRENCY, progress=False, repeat=repeat
        )
        elapsed = time.perf_counter() - t0

        results = results_from_report(list(eval_report.cases), cases_by_id)
        report = compute_report(results)

        # pass^k: per-case all-runs-correct, computed from the run groups.
        per_case_runs: dict[str, list[bool]] = {
            group.name: [
                rc.output.category.value == cases_by_id[group.name].expected_category
                for rc in group.runs
            ]
            for group in (eval_report.case_groups() or [])
        }
        passk = compute_pass_hat_k(per_case_runs, repeat)

        error_rate = sum(1 for r in results if r.error) / len(results) if results else 0.0
        span.set_attribute("eval.accuracy", report["accuracy"])
        span.set_attribute("eval.macro_f1", report["macro_f1"])
        span.set_attribute("eval.ece", report["ece"])
        span.set_attribute("eval.threshold", threshold)
        span.set_attribute("eval.error_rate", error_rate)
        span.set_attribute("eval.passed", passes_gate(report["accuracy"], threshold, error_rate))
        span.set_attribute("eval.repeat", repeat)
        if repeat > 1:
            span.set_attribute("eval.pass_hat_k", passk["pass_hat_k"])
        if report["mean_judge_score"] is not None:
            span.set_attribute("eval.mean_judge_score", report["mean_judge_score"])

        # Persist run + cases to DB (no-op if DATABASE_URL not configured)
        cases_payload: list[dict[str, object]] = [
            {
                "case_id": r.case.id,
                "expected_category": r.case.expected_category,
                "predicted_category": r.predicted_category,
                "is_correct": r.is_correct,
                "confidence": r.confidence,
                "judge_overall": r.judge_score.overall if r.judge_score else None,
                "judge_language_match": r.judge_score.language_match if r.judge_score else None,
            }
            for r in results
        ]
        await persist_eval_run(
            dv,
            settings.groq_model,
            len(cases),
            report["accuracy"],
            report["macro_f1"],
            report["ece"],
            report["mean_judge_score"],
            cases_payload,
        )

    print_report(results, report, dataset_label, settings.groq_model, dv, elapsed)
    # Framework's standard per-case / assertions table, complementing our calibration
    # and reliability sections above.
    eval_report.print(include_input=False, include_output=False)

    if repeat > 1:
        print(_sec(f"PASS^{repeat}  (per-case, all {repeat} runs correct)"))
        phk = passk["pass_hat_k"]
        phk_col = _GREEN if phk >= 0.90 else (_YELLOW if phk >= 0.75 else _RED)
        print(f"  pass^{repeat}   {phk_col}{phk * 100:.1f} %{_RST}  {_bar(phk)}")
        if passk["flaky"]:
            print(f"\n  {_YELLOW}Flaky (correct on some but not all runs){_RST}")
            for case_id in passk["flaky"]:
                runs = per_case_runs[case_id]
                print(f"    {_DIM}{case_id:<16}{_RST}  {sum(runs)}/{len(runs)} correct")

    if judge_sample > 0 and use_judge:
        path = export_calibration_sample(results, judge_sample, CALIBRATION_DIR)
        print(f"  {_DIM}Calibration sample → {path}{_RST}\n")

    ok = passes_gate(report["accuracy"], threshold, error_rate)
    gate_col = _GREEN if ok else _RED
    print(
        f"\n  GATE  accuracy {report['accuracy']:.3f} vs {threshold:.2f}"
        f"  ·  errors {error_rate:.0%} (max {_MAX_ERROR_RATE:.0%})"
        f"  →  {gate_col}{'PASS' if ok else 'FAIL'}{_RST}\n"
    )
    if check and not ok:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Email Triage Accuracy Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--suite",
        choices=["regression", "capability", "all"],
        default="all",
        help="Which suite to run (default: all). Ignored if --dataset is given.",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip LLM judge — run classification metrics only (2× faster)",
    )
    parser.add_argument(
        "--filter",
        metavar="KEY=VALUE",
        action="append",
        default=[],
        help="Filter dataset cases (e.g. --filter difficulty=hard). Repeatable.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Override the suite with a single JSONL file (uses the default threshold).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if accuracy is below the suite threshold (CI gate).",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="K",
        help="Run each case K times and report pass^k (default: 1).",
    )
    parser.add_argument(
        "--judge-sample",
        type=int,
        default=0,
        metavar="N",
        help="Export the first N judged cases to evals/calibration/ for human spot-check.",
    )
    args = parser.parse_args()

    if args.repeat < 1:
        print("--repeat must be >= 1.", file=sys.stderr)
        sys.exit(1)
    if args.judge_sample < 0:
        print("--judge-sample must be >= 0.", file=sys.stderr)
        sys.exit(1)

    filters: dict[str, str] = {}
    for f in args.filter:
        if "=" not in f:
            print(f"Invalid filter '{f}'. Expected KEY=VALUE.", file=sys.stderr)
            sys.exit(1)
        k, v = f.split("=", 1)
        filters[k] = v

    asyncio.run(
        run(
            args.suite,
            args.dataset,
            filters,
            use_judge=not args.no_judge,
            check=args.check,
            repeat=args.repeat,
            judge_sample=args.judge_sample,
        )
    )


if __name__ == "__main__":
    main()
