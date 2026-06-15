"""Tests for the database persistence layer (Plan 14)."""

from __future__ import annotations

import uuid

import pytest
from email_triage.db.models import EvalCase, EvalRun, TriageLog
from email_triage.db.repos.evals import EvalRepo
from email_triage.db.repos.triage import TriageLogRepo
from email_triage.schemas import Category, TriageRequest, TriageResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture()
def triage_req() -> TriageRequest:
    return TriageRequest(
        subject="Where is my order?",
        body="I ordered 3 days ago and have not received tracking info.",
        sender="customer@example.com",
    )


@pytest.fixture()
def triage_result() -> TriageResponse:
    return TriageResponse(
        category=Category.STATUS,
        confidence=0.93,
        draft_reply="Thank you for reaching out. We are looking into your order status.",
    )


async def test_insert_triage_log(
    db_session: AsyncSession,
    triage_req: TriageRequest,
    triage_result: TriageResponse,
) -> None:
    repo = TriageLogRepo()
    tenant_id = uuid.uuid4()
    await repo.insert_log(
        db_session,
        triage_req,
        triage_result,
        request_id="req-abc",
        latency_ms=420.0,
        endpoint="sync",
        model_id="llama-3.3-70b-versatile",
        tenant_id=tenant_id,
    )
    await db_session.flush()

    row = await db_session.scalar(select(TriageLog))
    assert row is not None
    assert row.request_id == "req-abc"
    assert row.tenant_id == tenant_id
    assert row.category == "status"
    assert abs(row.confidence - 0.93) < 1e-6
    assert row.latency_ms is not None and abs(row.latency_ms - 420.0) < 1e-6
    assert row.endpoint == "sync"
    assert row.model_id == "llama-3.3-70b-versatile"
    assert row.subject_chars == len(triage_req.subject)
    assert row.body_chars == len(triage_req.body)


async def test_insert_eval_run_and_cases(db_session: AsyncSession) -> None:
    repo = EvalRepo()
    run_id = await repo.insert_run(
        db_session,
        dataset_version="a3f2b1c9",
        model_id="llama-3.3-70b-versatile",
        n_cases=10,
        accuracy=0.90,
        macro_f1=0.88,
        ece=0.042,
        mean_judge_score=4.2,
    )
    await db_session.flush()
    assert isinstance(run_id, uuid.UUID)

    cases: list[dict[str, object]] = [
        {
            "case_id": "status-001",
            "expected_category": "status",
            "predicted_category": "status",
            "is_correct": True,
            "confidence": 0.95,
            "judge_overall": 5,
            "judge_language_match": True,
        },
        {
            "case_id": "refunds-001",
            "expected_category": "refunds",
            "predicted_category": "status",
            "is_correct": False,
            "confidence": 0.61,
        },
    ]
    await repo.insert_cases(db_session, run_id, cases)
    await db_session.flush()

    run = await db_session.scalar(select(EvalRun))
    assert run is not None
    assert run.n_cases == 10
    assert abs(run.accuracy - 0.90) < 1e-6
    assert abs(run.ece - 0.042) < 1e-6
    assert run.mean_judge_score is not None and abs(run.mean_judge_score - 4.2) < 1e-6

    case_rows = (await db_session.scalars(select(EvalCase))).all()
    assert len(case_rows) == 2
    correct = next(c for c in case_rows if c.case_id == "status-001")
    assert correct.is_correct is True
    assert correct.judge_overall == 5
    assert correct.judge_language_match is True

    wrong = next(c for c in case_rows if c.case_id == "refunds-001")
    assert wrong.is_correct is False
    assert wrong.judge_overall is None


async def test_eval_case_cascade_delete(db_session: AsyncSession) -> None:
    repo = EvalRepo()
    run_id = await repo.insert_run(
        db_session,
        dataset_version="deadbeef",
        model_id="llama-3.3-70b-versatile",
        n_cases=1,
        accuracy=1.0,
        macro_f1=1.0,
        ece=0.0,
        mean_judge_score=None,
    )
    await repo.insert_cases(
        db_session,
        run_id,
        [
            {
                "case_id": "prices-001",
                "expected_category": "prices",
                "predicted_category": "prices",
                "is_correct": True,
                "confidence": 0.99,
            }
        ],
    )
    await db_session.flush()

    run = await db_session.scalar(select(EvalRun))
    assert run is not None
    await db_session.delete(run)
    await db_session.flush()

    remaining = (await db_session.scalars(select(EvalCase))).all()
    assert remaining == [], "EvalCase rows should be deleted with the parent EvalRun"
