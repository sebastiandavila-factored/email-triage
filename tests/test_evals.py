"""Phase 2 — pydantic-evals migration. No Groq: a mock task + stub judge exercise the
evaluators, the report→EvalResult adapter, judge reconstruction, and metrics end-to-end.
Tests are sync so ``evaluate_sync`` can own its event loop."""

import json
from collections import Counter
from pathlib import Path

import pytest
from email_triage.schemas import Category, TriageRequest, TriageResponse
from evals.dataset_loader import build_dataset, load_suite
from evals.evaluators import (
    CategoryCorrect,
    JudgeQuality,
    judge_score_from_case,
    set_judge,
)
from evals.judge import JudgeAgent
from evals.metrics import compute_pass_hat_k, compute_report
from evals.run_evals import (
    export_calibration_sample,
    passes_gate,
    passes_threshold,
    results_from_report,
)
from evals.schemas import CaseMeta, EvalCase, EvalResult, JudgeScore
from pydantic import ValidationError
from pydantic_evals.evaluators import Evaluator

_FIXED_JUDGE = JudgeScore(relevance=4, language_match=True, tone=5, correctness=4, overall=4)


class StubJudge(JudgeAgent):
    def __init__(self) -> None:
        pass

    async def evaluate(self, subject: str, body: str, draft_reply: str) -> JudgeScore:
        return _FIXED_JUDGE


def _case(case_id: str, expected: str) -> EvalCase:
    return EvalCase(
        id=case_id,
        subject="subject",
        sender="eval@test.com",
        body="body",
        expected_category=expected,  # type: ignore[arg-type]
        language="es",
        difficulty="easy",
        source="synthetic",
    )


def _mock_task(req: TriageRequest) -> TriageResponse:
    # Always predicts refunds, conf 0.9 — caller controls correctness via expected_category.
    return TriageResponse(category=Category.REFUNDS, draft_reply="ok", confidence=0.9)


def test_suite_sizes() -> None:
    assert len(load_suite("regression", {})) == 25
    assert len(load_suite("capability", {})) == 22
    assert len(load_suite("all", {})) == 47


def test_regression_suite_is_category_balanced() -> None:
    counts = Counter(c.expected_category for c in load_suite("regression", {}))
    assert set(counts.values()) == {5}, counts


def test_capability_suite_has_minimum_support() -> None:
    # Capability is the trend suite: it guarantees >= 4 per category but may carry extra
    # hard/ambiguous cases (e.g. the status cases moved out of the regression gate).
    counts = Counter(c.expected_category for c in load_suite("capability", {}))
    assert len(counts) == 5
    assert min(counts.values()) >= 4, counts


def test_every_case_has_valid_source() -> None:
    cases = load_suite("all", {})
    assert all(c.source in ("real", "synthetic") for c in cases)


def test_loader_rejects_case_missing_source() -> None:
    with pytest.raises(ValidationError):
        EvalCase.model_validate(
            {
                "id": "x",
                "subject": "s",
                "sender": "eval@test.com",
                "body": "b",
                "expected_category": "status",
                "language": "es",
                "difficulty": "easy",
            }
        )


def test_all_suite_covers_every_category() -> None:
    cases = load_suite("all", {})
    assert {c.expected_category for c in cases} == {
        "status",
        "refunds",
        "availability",
        "shipments",
        "prices",
    }


def test_load_suite_applies_filters() -> None:
    hard = load_suite("capability", {"difficulty": "hard"})
    assert hard
    assert all(c.difficulty == "hard" for c in hard)


def test_passes_threshold() -> None:
    assert passes_threshold(0.95, 0.95)
    assert passes_threshold(1.0, 0.85)
    assert not passes_threshold(0.80, 0.85)


def test_passes_gate_requires_low_error_rate() -> None:
    # Perfect accuracy on survivors must NOT pass if too many cases errored.
    assert passes_gate(1.0, 0.95, error_rate=0.0)
    assert not passes_gate(1.0, 0.95, error_rate=0.5)  # vacuous pass blocked
    assert not passes_gate(0.80, 0.85, error_rate=0.0)  # accuracy too low


def test_build_dataset_carries_inputs_and_metadata() -> None:
    cases = [_case("a", "refunds")]
    dataset = build_dataset(cases, [CategoryCorrect()])
    case = dataset.cases[0]
    assert case.name == "a"
    assert isinstance(case.inputs, TriageRequest)
    assert case.metadata is not None
    assert case.metadata["expected_category"] == "refunds"


def test_end_to_end_metrics_and_judge_reconstruction() -> None:
    cases = [_case("a", "refunds"), _case("b", "status")]
    set_judge(StubJudge())
    evaluators: list[Evaluator[TriageRequest, TriageResponse, CaseMeta]] = [
        CategoryCorrect(),
        JudgeQuality(),
    ]
    dataset = build_dataset(cases, evaluators)
    report = dataset.evaluate_sync(_mock_task, progress=False)

    results = results_from_report(list(report.cases), {c.id: c for c in cases})
    assert len(results) == 2
    metrics = compute_report(results)
    assert metrics["accuracy"] == 0.5  # one refunds (correct), one status (wrong)

    for r in results:
        assert r.judge_score is not None
        assert r.judge_score.overall == 4
        assert r.judge_score.language_match is True


def test_no_judge_yields_none_scores() -> None:
    cases = [_case("a", "refunds")]
    set_judge(None)
    dataset = build_dataset(cases, [CategoryCorrect()])
    report = dataset.evaluate_sync(_mock_task, progress=False)
    results = results_from_report(list(report.cases), {c.id: c for c in cases})
    assert results[0].judge_score is None


def test_judge_score_from_case_none_without_judge() -> None:
    cases = [_case("a", "refunds")]
    set_judge(None)
    dataset = build_dataset(cases, [CategoryCorrect()])
    report = dataset.evaluate_sync(_mock_task, progress=False)
    assert judge_score_from_case(report.cases[0]) is None


def test_compute_pass_hat_k_all_mixed_none() -> None:
    runs = {
        "all_pass": [True, True, True],
        "flaky": [True, False, True],
        "all_fail": [False, False, False],
    }
    result = compute_pass_hat_k(runs, repeat=3)
    assert result["pass_hat_k"] == 1 / 3  # only all_pass counts
    assert result["flaky"] == ["flaky"]  # all_fail is not flaky (consistently wrong)
    assert result["repeat"] == 3


def test_compute_pass_hat_k_missing_run_counts_against() -> None:
    # A case with fewer correct runs than `repeat` (e.g. one run errored) does not pass.
    result = compute_pass_hat_k({"a": [True, True]}, repeat=3)
    assert result["pass_hat_k"] == 0.0
    assert result["flaky"] == ["a"]


def test_compute_pass_hat_k_empty() -> None:
    result = compute_pass_hat_k({}, repeat=5)
    assert result["pass_hat_k"] == 0.0
    assert result["flaky"] == []


def test_pass_hat_k_never_exceeds_accuracy() -> None:
    # Invariant: pass^k (all runs correct) <= per-run accuracy.
    runs = {
        "a": [True, True, True],
        "b": [True, False, True],
        "c": [False, False, True],
    }
    passk = compute_pass_hat_k(runs, repeat=3)
    flat = [r for case_runs in runs.values() for r in case_runs]
    accuracy = sum(flat) / len(flat)
    assert passk["pass_hat_k"] <= accuracy


def test_multi_run_integration_groups_by_case() -> None:
    # repeat=3 with a deterministic mock task → every run correct → pass^3 == 1.0.
    cases = [_case("a", "refunds"), _case("b", "refunds")]
    set_judge(None)
    dataset = build_dataset(cases, [CategoryCorrect()])
    report = dataset.evaluate_sync(_mock_task, repeat=3, progress=False)

    cases_by_id = {c.id: c for c in cases}
    per_case_runs = {
        group.name: [
            rc.output.category.value == cases_by_id[group.name].expected_category
            for rc in group.runs
        ]
        for group in (report.case_groups() or [])
    }
    passk = compute_pass_hat_k(per_case_runs, repeat=3)
    assert passk["pass_hat_k"] == 1.0
    assert passk["flaky"] == []
    assert all(len(runs) == 3 for runs in per_case_runs.values())


def _result(case_id: str, expected: str, judge: JudgeScore | None) -> EvalResult:
    return EvalResult(
        case=_case(case_id, expected),
        predicted_category=expected,
        confidence=0.9,
        draft_reply="reply",
        is_correct=True,
        judge_score=judge,
    )


_ASSESSABLE = JudgeScore(relevance=4, language_match=True, tone=4, correctness=4, overall=4)


def test_judge_score_assessable_requires_all_scores() -> None:
    with pytest.raises(ValidationError):
        JudgeScore(verdict="assessable", relevance=4)  # missing the rest


def test_judge_score_unknown_allows_empty() -> None:
    js = JudgeScore(verdict="unknown", reason="cannot tell")
    assert js.overall is None
    assert js.language_match is None


def test_unknown_excluded_from_means_but_counted() -> None:
    results = [
        _result("a", "refunds", _ASSESSABLE),
        _result("b", "status", JudgeScore(verdict="unknown", reason="x")),
    ]
    report = compute_report(results)
    assert report["judge_unknown_rate"] == 0.5
    assert report["mean_judge_score"] == 4.0  # only the assessable case
    assert report["judge_detail"] is not None


def test_all_unknown_yields_no_means() -> None:
    results = [_result("a", "refunds", JudgeScore(verdict="unknown"))]
    report = compute_report(results)
    assert report["judge_unknown_rate"] == 1.0
    assert report["mean_judge_score"] is None
    assert report["judge_detail"] is None


def test_no_judge_unknown_rate_is_none() -> None:
    report = compute_report([_result("a", "refunds", None)])
    assert report["judge_unknown_rate"] is None


def test_export_calibration_sample(tmp_path: Path) -> None:
    results = [
        _result("a", "refunds", _ASSESSABLE.model_copy(update={"reason": "good"})),
        _result("b", "status", JudgeScore(verdict="unknown", reason="cant tell")),
        _result("c", "prices", None),  # no judge → excluded
    ]
    path = export_calibration_sample(results, 5, tmp_path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2  # only judged cases
    assert rows[0]["judge_verdict"] == "assessable"
    assert rows[1]["judge_verdict"] == "unknown"
    assert all(row["human_verdict"] is None for row in rows)


def test_dropped_case_becomes_error_result() -> None:
    # A case present in cases_by_id but absent from report.cases (task failed/dropped)
    # is re-added as an error result, excluded from metrics by compute_report.
    cases = [_case("a", "refunds")]
    set_judge(None)
    dataset = build_dataset(cases, [CategoryCorrect()])
    report = dataset.evaluate_sync(_mock_task, progress=False)

    cases_by_id = {"a": cases[0], "ghost": _case("ghost", "status")}
    results = results_from_report(list(report.cases), cases_by_id)
    errored = [r for r in results if r.error]
    assert len(errored) == 1
    assert errored[0].case.id == "ghost"
