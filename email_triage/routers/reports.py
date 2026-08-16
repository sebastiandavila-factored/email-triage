"""Voice report endpoint (Plan 41).

`POST /reports/voice` — summarize the caller-supplied triaged inbox items and write a spoken
briefing script. The items are whatever the client already has on screen (from a prior sync), so
this is decoupled from Gmail. Script-only in v1 (`audio_url` stays null).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends

from email_triage.deps import SettingsDep, WriteTriageDep
from email_triage.schemas import VoiceReport, VoiceReportRequest
from email_triage.services.voice_report import VoiceReportRunner, build_voice_report_runner

router = APIRouter(tags=["reports"])


@lru_cache(maxsize=1)
def _cached_runner(groq_model: str, groq_api_key: str) -> VoiceReportRunner:
    return build_voice_report_runner(groq_model=groq_model, groq_api_key=groq_api_key)


def get_voice_report_runner(settings: SettingsDep) -> VoiceReportRunner:
    """Groq is always configured, so the runner is always available (no 503 path).

    Overridden in tests with a ``TestModel``-backed runner (no Groq)."""
    return _cached_runner(settings.groq_model, settings.groq_api_key)


VoiceReportRunnerDep = Annotated[VoiceReportRunner, Depends(get_voice_report_runner)]


@router.post("/reports/voice", response_model=VoiceReport)
async def voice_report(
    body: VoiceReportRequest,
    ctx: WriteTriageDep,  # noqa: ARG001 — auth gate (triage:write); tenant not needed here
    runner: VoiceReportRunnerDep,
) -> VoiceReport:
    return await runner.run(body.items)
