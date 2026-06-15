from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.db.engine import get_session_factory
from email_triage.db.models import TriageLog
from email_triage.schemas import TriageRequest, TriageResponse

_log = structlog.get_logger()


class TriageLogRepo:
    async def insert_log(
        self,
        session: AsyncSession,
        req: TriageRequest,
        result: TriageResponse,
        request_id: str,
        latency_ms: float,
        endpoint: str,
        model_id: str,
        tenant_id: uuid.UUID | None,
    ) -> None:
        session.add(
            TriageLog(
                request_id=request_id,
                tenant_id=tenant_id,
                subject_chars=len(req.subject),
                body_chars=len(req.body),
                category=result.category.value,
                confidence=result.confidence,
                draft_chars=len(result.draft_reply),
                latency_ms=latency_ms,
                endpoint=endpoint,
                model_id=model_id,
            )
        )


async def persist_triage_log(
    req: TriageRequest,
    result: TriageResponse,
    request_id: str,
    latency_ms: float,
    endpoint: str,
    model_id: str,
    tenant_id: uuid.UUID | None = None,
) -> None:
    """Fire-and-forget DB write for background tasks. No-op if DB is not configured."""
    factory = get_session_factory()
    if factory is None:
        return
    try:
        async with factory() as session, session.begin():
            repo = TriageLogRepo()
            await repo.insert_log(
                session, req, result, request_id, latency_ms, endpoint, model_id, tenant_id
            )
    except Exception:
        _log.exception("triage_log.db_write_failed")
