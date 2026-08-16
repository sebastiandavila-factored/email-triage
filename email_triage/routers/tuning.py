"""Triage tuning copilot endpoint (Plan 44).

`POST /workspaces/{tid}/tune` — owner/admin only (`prompt:publish`). Runs the orchestrator that
diagnoses a flagged triage, edits the workspace **draft** to fix it, and re-checks against a small
check-set. Returns a `TuningProposal`; **the human publishes** via the Studio flow (Plan 26).

`tenant_id`/`user_id` come from the authenticated membership (never the body). The flagged email and
its intended category come from the body — the trace itself doesn't carry the email content.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from email_triage.db.engine import get_session_factory
from email_triage.deps import PublishPromptDep, SettingsDep
from email_triage.schemas import TuneRequest, TuningProposal
from email_triage.services.prompt_studio import PromptStudioError
from email_triage.services.trace_agent import LogfireQueryError
from email_triage.services.triage_config import TriageConfigError
from email_triage.services.tuning import TuningError, TuningRunner, build_tuning_runner

router = APIRouter(prefix="/workspaces/{tid}", tags=["tuning"])


@lru_cache(maxsize=1)
def _cached_runner(
    groq_model: str, groq_api_key: str, read_token: str, base_url: str | None
) -> TuningRunner:
    return build_tuning_runner(
        groq_model=groq_model,
        groq_api_key=groq_api_key,
        read_token=read_token,
        base_url=base_url,
    )


def get_tuning_runner(settings: SettingsDep) -> TuningRunner | None:
    """Resolve the tuning runner, or None when Logfire (diagnosis) isn't configured (→ 503).

    Overridden in tests with a fake runner (no Groq, no Logfire, no real classifier)."""
    if not settings.logfire_read_token:
        return None
    return _cached_runner(
        settings.groq_model,
        settings.groq_api_key,
        settings.logfire_read_token,
        settings.logfire_read_base_url,
    )


TuningRunnerDep = Annotated[TuningRunner | None, Depends(get_tuning_runner)]


@router.post("/tune", response_model=TuningProposal)
async def tune(body: TuneRequest, ctx: PublishPromptDep, runner: TuningRunnerDep) -> TuningProposal:
    if runner is None:
        raise HTTPException(status_code=503, detail="Trace diagnosis is not configured")
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    try:
        return await runner.run(
            factory=factory,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            trace_id=body.trace_id,
            email=body.email,
            expected_slug=body.expected_category,
        )
    except (PromptStudioError, TriageConfigError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except LogfireQueryError as exc:
        detail = str(exc)
        status = 422 if "trace id" in detail else 503
        raise HTTPException(status_code=status, detail=detail) from exc
    except TuningError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
