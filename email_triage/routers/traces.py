"""Trace-debug chat endpoint (Plan 31).

`POST /workspaces/{tid}/traces/chat` — owner/admin only (`traces:read`). Answers a natural
-language question about one triage's traces, scoped to the caller's organization. The
`tenant_id` comes from the authenticated membership (never the body), and the anchored
`trace_id` is verified to belong to that tenant before the agent runs.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException

from email_triage.deps import SettingsDep, TracesReadDep
from email_triage.schemas import TraceChatRequest, TraceChatResponse
from email_triage.services.trace_agent import (
    LogfireQueryError,
    TraceChatService,
    build_trace_chat_service,
)

router = APIRouter(prefix="/workspaces/{tid}/traces", tags=["traces"])

_log = structlog.get_logger()


@lru_cache(maxsize=1)
def _cached_service(
    groq_model: str, groq_api_key: str, read_token: str, base_url: str | None
) -> TraceChatService:
    # Hashable args → one service per config; avoids leaking an httpx client per request.
    return build_trace_chat_service(
        groq_model=groq_model,
        groq_api_key=groq_api_key,
        read_token=read_token,
        base_url=base_url,
    )


def get_trace_chat_service(settings: SettingsDep) -> TraceChatService | None:
    """Resolve the trace-chat service, or None when the read token isn't configured.

    None → the endpoint answers 503 (feature not set up) instead of failing obscurely.
    Overridden in tests with a fake service (no Groq, no Logfire network).
    """
    if not settings.logfire_read_token:
        return None
    return _cached_service(
        settings.groq_model,
        settings.groq_api_key,
        settings.logfire_read_token,
        settings.logfire_read_base_url,
    )


TraceChatServiceDep = Annotated[TraceChatService | None, Depends(get_trace_chat_service)]


@router.post("/chat", response_model=TraceChatResponse)
async def traces_chat(
    body: TraceChatRequest,
    ctx: TracesReadDep,
    service: TraceChatServiceDep,
) -> TraceChatResponse:
    if service is None:
        raise HTTPException(status_code=503, detail="Trace debugging is not configured")

    tenant_id = str(ctx.tenant_id)
    try:
        owns = await service.owns_trace(tenant_id, body.trace_id)
    except LogfireQueryError as exc:
        # Bad trace-id shape → client error; anything else → Logfire unavailable.
        detail = str(exc)
        status = 422 if "trace id" in detail else 503
        raise HTTPException(status_code=status, detail=detail) from exc

    if not owns:
        # Trace unknown or not this org's — identical response either way (no leak).
        raise HTTPException(status_code=404, detail="Trace not found for this workspace")

    history = [(m.role, m.content) for m in body.history]
    try:
        reply = await service.chat(tenant_id, body.trace_id, body.message, history)
    except LogfireQueryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return TraceChatResponse(reply=reply)
