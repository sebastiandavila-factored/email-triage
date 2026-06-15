from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.db.engine import get_session_factory
from email_triage.db.models import EvalCase, EvalRun

_log = structlog.get_logger()


class EvalRepo:
    async def insert_run(
        self,
        session: AsyncSession,
        dataset_version: str,
        model_id: str,
        n_cases: int,
        accuracy: float,
        macro_f1: float,
        ece: float,
        mean_judge_score: float | None,
    ) -> uuid.UUID:
        run = EvalRun(
            dataset_version=dataset_version,
            model_id=model_id,
            n_cases=n_cases,
            accuracy=accuracy,
            macro_f1=macro_f1,
            ece=ece,
            mean_judge_score=mean_judge_score,
        )
        session.add(run)
        await session.flush()
        return run.id

    async def insert_cases(
        self,
        session: AsyncSession,
        run_id: uuid.UUID,
        cases: list[dict[str, object]],
    ) -> None:
        for c in cases:
            session.add(
                EvalCase(
                    run_id=run_id,
                    case_id=c["case_id"],
                    expected_category=c["expected_category"],
                    predicted_category=c["predicted_category"],
                    is_correct=c["is_correct"],
                    confidence=c["confidence"],
                    judge_overall=c.get("judge_overall"),
                    judge_language_match=c.get("judge_language_match"),
                )
            )


async def persist_eval_run(
    dataset_version: str,
    model_id: str,
    n_cases: int,
    accuracy: float,
    macro_f1: float,
    ece: float,
    mean_judge_score: float | None,
    cases: list[dict[str, object]],
) -> None:
    """Write an eval run + all case results to DB. No-op if DB is not configured."""
    factory = get_session_factory()
    if factory is None:
        return
    try:
        async with factory() as session, session.begin():
            repo = EvalRepo()
            run_id = await repo.insert_run(
                session,
                dataset_version,
                model_id,
                n_cases,
                accuracy,
                macro_f1,
                ece,
                mean_judge_score,
            )
            await repo.insert_cases(session, run_id, cases)
        _log.info("eval_run.persisted", run_id=str(run_id), n_cases=n_cases)
    except Exception:
        _log.exception("eval_run.db_write_failed")
