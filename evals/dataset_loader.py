"""Load the JSONL golden dataset into a typed ``pydantic_evals.Dataset``."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from email_triage.schemas import TriageRequest, TriageResponse
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator

from evals.schemas import CaseMeta, EvalCase

TriageDataset = Dataset[TriageRequest, TriageResponse, CaseMeta]
TriageEvaluator = Evaluator[TriageRequest, TriageResponse, CaseMeta]

DATASETS_DIR = Path(__file__).parent / "datasets"

# Two purpose-built suites (disjoint; union = the full golden set).
#   regression — locked, unambiguous core cases that must always pass (strict gate).
#   capability — harder/ambiguous/multilingual/tone cases; trend-tracked (loose gate).
#   all        — both, for a single full run.
SUITE_FILES: dict[str, list[str]] = {
    "regression": ["regression.jsonl"],
    "capability": ["capability.jsonl"],
    "all": ["regression.jsonl", "capability.jsonl"],
}


def suite_paths(suite: str) -> list[Path]:
    return [DATASETS_DIR / name for name in SUITE_FILES[suite]]


def load_suite(suite: str, filters: dict[str, str]) -> list[EvalCase]:
    """Load all cases in a named suite (concatenating its files)."""
    cases: list[EvalCase] = []
    for path in suite_paths(suite):
        cases.extend(load_cases(path, filters))
    return cases


def suite_version(suite: str) -> str:
    """SHA256[:8] over the suite's files, stable across the suite's contents."""
    digest = hashlib.sha256()
    for path in suite_paths(suite):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:8]


def load_cases(path: Path, filters: dict[str, str]) -> list[EvalCase]:
    """Parse the JSONL dataset into ``EvalCase`` rows, applying simple equality filters."""
    cases: list[EvalCase] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        data: dict[str, object] = json.loads(line)
        case = EvalCase.model_validate(data)
        if all(str(getattr(case, k, None)) == v for k, v in filters.items()):
            cases.append(case)
    return cases


def build_dataset(
    cases: Sequence[EvalCase],
    evaluators: Sequence[TriageEvaluator],
) -> TriageDataset:
    """Build a ``Dataset`` whose inputs are ``TriageRequest`` and whose metadata carries
    the ground-truth category + provenance. ``expected_output`` is left unset because it
    is typed as the task output (``TriageResponse``); the category lives in metadata."""
    eval_cases = [
        Case(
            name=c.id,
            inputs=TriageRequest(subject=c.subject, sender=c.sender, body=c.body),
            metadata=CaseMeta(
                expected_category=c.expected_category,
                language=c.language,
                difficulty=c.difficulty,
                notes=c.notes,
                source=c.source,
            ),
        )
        for c in cases
    ]
    return Dataset(name="email-triage", cases=eval_cases, evaluators=list(evaluators))
