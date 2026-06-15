from __future__ import annotations

from typing import TypedDict

from evals.schemas import EvalResult

CATEGORIES = ["status", "refunds", "availability", "shipments", "prices"]


class CategoryMetrics(TypedDict):
    precision: float
    recall: float
    f1: float
    support: int


class CalibrationBin(TypedDict):
    label: str
    accuracy: float
    confidence: float
    gap: float
    count: int


class JudgeDetail(TypedDict):
    mean_overall: float
    mean_relevance: float
    mean_tone: float
    mean_correctness: float
    language_match_pct: float


class EvalReport(TypedDict):
    accuracy: float
    macro_f1: float
    per_category: dict[str, CategoryMetrics]
    confusion_matrix: list[list[int]]
    ece: float
    mean_confidence: float
    calibration_bins: list[CalibrationBin]
    mean_judge_score: float | None
    judge_detail: JudgeDetail | None


def compute_report(results: list[EvalResult]) -> EvalReport:
    valid = [r for r in results if r.error is None]
    total = len(valid)
    if total == 0:
        raise ValueError("No valid results to compute metrics from.")

    correct = sum(1 for r in valid if r.is_correct)
    accuracy = correct / total

    cat_to_idx = {c: i for i, c in enumerate(CATEGORIES)}
    matrix: list[list[int]] = [[0] * 5 for _ in range(5)]
    for r in valid:
        expected_idx = cat_to_idx.get(r.case.expected_category, 0)
        predicted_idx = cat_to_idx.get(r.predicted_category, 0)
        matrix[expected_idx][predicted_idx] += 1

    per_category: dict[str, CategoryMetrics] = {}
    for i, cat in enumerate(CATEGORIES):
        tp = matrix[i][i]
        fp = sum(matrix[j][i] for j in range(5)) - tp
        fn = sum(matrix[i][j] for j in range(5)) - tp
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        support = sum(matrix[i])
        per_category[cat] = CategoryMetrics(
            precision=precision, recall=recall, f1=f1, support=support
        )

    macro_f1 = sum(m["f1"] for m in per_category.values()) / len(per_category)
    mean_confidence = sum(r.confidence for r in valid) / total
    ece, calibration_bins = _compute_ece(valid, n_bins=10)

    judge_results = [r for r in valid if r.judge_score is not None]
    mean_judge_score: float | None = None
    judge_detail: JudgeDetail | None = None
    if judge_results:
        n = len(judge_results)

        def _js(attr: str) -> float:
            return sum(getattr(r.judge_score, attr) for r in judge_results if r.judge_score) / n  # type: ignore[union-attr]

        mean_judge_score = _js("overall")
        judge_detail = JudgeDetail(
            mean_overall=mean_judge_score,
            mean_relevance=_js("relevance"),
            mean_tone=_js("tone"),
            mean_correctness=_js("correctness"),
            language_match_pct=sum(
                1 for r in judge_results if r.judge_score and r.judge_score.language_match
            )
            / n,
        )

    return EvalReport(
        accuracy=accuracy,
        macro_f1=macro_f1,
        per_category=per_category,
        confusion_matrix=matrix,
        ece=ece,
        mean_confidence=mean_confidence,
        calibration_bins=calibration_bins,
        mean_judge_score=mean_judge_score,
        judge_detail=judge_detail,
    )


def _compute_ece(results: list[EvalResult], n_bins: int = 10) -> tuple[float, list[CalibrationBin]]:
    bins: list[CalibrationBin] = []
    ece = 0.0
    n = len(results)
    if n == 0:
        return 0.0, []

    for b in range(n_bins):
        low = b / n_bins
        high = (b + 1) / n_bins
        # The last bin is closed on the right so confidence == 1.0 is counted
        # instead of being silently dropped (it still inflates the denominator).
        if b == n_bins - 1:
            bucket = [r for r in results if low <= r.confidence <= high]
        else:
            bucket = [r for r in results if low <= r.confidence < high]
        if not bucket:
            continue
        bin_acc = sum(1 for r in bucket if r.is_correct) / len(bucket)
        bin_conf = sum(r.confidence for r in bucket) / len(bucket)
        gap = bin_acc - bin_conf
        ece += (len(bucket) / n) * abs(gap)
        bins.append(
            CalibrationBin(
                label=f"{low:.1f}–{high:.1f}",
                accuracy=bin_acc,
                confidence=bin_conf,
                gap=gap,
                count=len(bucket),
            )
        )

    return ece, bins


def reliability_diagram(bins: list[CalibrationBin], bar_width: int = 20) -> str:
    """Return an ASCII reliability diagram string from calibration bins."""
    if not bins:
        return "  (no calibration data)"
    lines: list[str] = ["  Conf range   Acc    Gap    Bar"]
    for b in bins:
        filled = round(abs(b["gap"]) * bar_width * 5)
        bar = ("+" if b["gap"] >= 0 else "-") * min(filled, bar_width)
        lines.append(f"  {b['label']:<12} {b['accuracy']:.2f}  {b['gap']:+.2f}  {bar}")
    return "\n".join(lines)
