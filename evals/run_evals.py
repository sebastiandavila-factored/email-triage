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
from email_triage.schemas import TriageRequest
from email_triage.services.llm import LLMService

from evals.judge import JudgeAgent
from evals.metrics import EvalReport, compute_report
from evals.schemas import EvalCase, EvalResult

DATASET_DEFAULT = Path(__file__).parent / "dataset.jsonl"
_SEMAPHORE_LIMIT = 5

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
    dataset_path: Path,
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
        f"  {_DIM}Dataset{_RST}  {dataset_path}"
        f"  {_DIM}(v {dataset_ver}){_RST}  ·  {n_cases} cases  {elapsed:.1f}s"
    )
    print(f"  {_DIM}Model  {_RST}  {model_id}")
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
    if report["judge_detail"] is not None:
        jd = report["judge_detail"]
        print(_sec("LLM JUDGE"))
        print(f"  Overall          {jd['mean_overall']:.1f} / 5")
        print(f"  Relevance        {jd['mean_relevance']:.1f} / 5")
        lm_pct = jd["language_match_pct"] * 100
        lm_col = _GREEN if lm_pct >= 95 else _YELLOW
        print(f"  Language match   {lm_col}{lm_pct:.1f} %{_RST}")
        print(f"  Tone             {jd['mean_tone']:.1f} / 5")
        print(f"  Correctness      {jd['mean_correctness']:.1f} / 5")

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


def _load_dataset(path: Path, filters: dict[str, str]) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data: dict[str, object] = json.loads(line)
        case = EvalCase.model_validate(data)
        if all(str(getattr(case, k, None)) == v for k, v in filters.items()):
            cases.append(case)
    return cases


def _dataset_version(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


async def _run_case(
    case: EvalCase,
    llm: LLMService,
    judge: JudgeAgent | None,
    sem: asyncio.Semaphore,
) -> EvalResult:
    async with sem:
        try:
            req = TriageRequest(subject=case.subject, sender=case.sender, body=case.body)
            response = await llm.triage(req)
            is_correct = response.category.value == case.expected_category

            judge_score = None
            if judge is not None:
                judge_score = await judge.evaluate(case, response.draft_reply)

            return EvalResult(
                case=case,
                predicted_category=response.category.value,
                confidence=response.confidence,
                draft_reply=response.draft_reply,
                is_correct=is_correct,
                judge_score=judge_score,
            )
        except Exception as exc:
            return EvalResult(
                case=case,
                predicted_category="status",
                confidence=0.0,
                draft_reply="",
                is_correct=False,
                error=str(exc),
            )


async def run(
    dataset_path: Path,
    filters: dict[str, str],
    use_judge: bool,
) -> None:
    cases = _load_dataset(dataset_path, filters)
    if not cases:
        print("No cases matched the given filters.", file=sys.stderr)
        sys.exit(1)

    settings = Settings()  # type: ignore[call-arg]
    logfire.configure(send_to_logfire="if-token-present", service_name="email-triage-eval")

    if settings.database_url:
        init_db(settings.database_url)

    llm = LLMService(api_key=settings.groq_api_key, model=settings.groq_model)
    judge = JudgeAgent(api_key=settings.groq_api_key) if use_judge else None
    sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)
    dv = _dataset_version(dataset_path)

    with logfire.span(
        "eval.run",
        dataset_version=dv,
        model_id=settings.groq_model,
        n_cases=len(cases),
    ) as span:
        t0 = time.perf_counter()
        raw_results = await asyncio.gather(*[_run_case(c, llm, judge, sem) for c in cases])
        elapsed = time.perf_counter() - t0

        results: list[EvalResult] = list(raw_results)
        report = compute_report(results)

        span.set_attribute("eval.accuracy", report["accuracy"])
        span.set_attribute("eval.macro_f1", report["macro_f1"])
        span.set_attribute("eval.ece", report["ece"])
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

        # Log individual case spans
        for r in results:
            with logfire.span("eval.case") as case_span:
                case_span.set_attribute("eval.case_id", r.case.id)
                case_span.set_attribute("eval.expected_category", r.case.expected_category)
                case_span.set_attribute("eval.predicted_category", r.predicted_category)
                case_span.set_attribute("eval.is_correct", r.is_correct)
                case_span.set_attribute("eval.confidence", r.confidence)
                if r.judge_score is not None:
                    js = r.judge_score
                    case_span.set_attribute("eval.judge.overall", js.overall)
                    case_span.set_attribute("eval.judge.language_match", js.language_match)

    print_report(results, report, dataset_path, settings.groq_model, dv, elapsed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Email Triage Accuracy Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        default=DATASET_DEFAULT,
        help=f"Path to dataset JSONL (default: {DATASET_DEFAULT})",
    )
    args = parser.parse_args()

    filters: dict[str, str] = {}
    for f in args.filter:
        if "=" not in f:
            print(f"Invalid filter '{f}'. Expected KEY=VALUE.", file=sys.stderr)
            sys.exit(1)
        k, v = f.split("=", 1)
        filters[k] = v

    asyncio.run(run(args.dataset, filters, use_judge=not args.no_judge))


if __name__ == "__main__":
    main()
