import json
import time
from collections.abc import AsyncGenerator
from typing import Annotated

import httpx
import logfire
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from email_triage.db.repos.triage import persist_triage_log
from email_triage.deps import TenantDep, get_settings, get_triage_service, limiter, verify_api_key
from email_triage.observability import (
    CONFIDENCE,
    ERRORS_TOTAL,
    LLM_LATENCY_MS,
    REQUEST_BODY_CHARS,
    REQUESTS_TOTAL,
    RESPONSE_DRAFT_CHARS,
    STREAM_TTFT_MS,
)
from email_triage.schemas import (
    AnyStreamingResponse,
    AnyTriageResponse,
    DynamicTriageResponse,
    TriageRequest,
)
from email_triage.services.llm import LLMError, LLMService
from email_triage.services.prompt_compiler import UNKNOWN_SLUG

router = APIRouter(
    prefix="/triage",
    tags=["triage"],
    dependencies=[Depends(verify_api_key)],
)

LLMDep = Annotated[LLMService, Depends(get_triage_service)]

_log = structlog.get_logger()


def _log_triage_result(req: TriageRequest, result: AnyTriageResponse) -> None:
    _log.info(
        "triage.result",
        category=str(result.category),
        confidence=result.confidence,
        sender=str(req.sender),
    )


@router.post("", response_model=DynamicTriageResponse)
@limiter.limit("20/minute")  # type: ignore[reportUnknownMemberType]
async def triage(
    request: Request,
    req: TriageRequest,
    llm: LLMDep,
    tenant: TenantDep,
    background_tasks: BackgroundTasks,
) -> AnyTriageResponse:
    with logfire.span("triage.sync") as span:
        span.set_attribute("endpoint", "sync")
        span.set_attribute("tenant_id", str(tenant.tenant_id))
        span.set_attribute("triage.dynamic", llm.allowed_slugs is not None)
        span.set_attribute("email.subject_chars", len(req.subject))
        span.set_attribute("email.body_chars", len(req.body))
        REQUEST_BODY_CHARS.record(len(req.body))
        t_llm = time.perf_counter()
        try:
            # Baggage tags the child spans (pydantic-ai / httpx) with tenant_id too, so a
            # per-org trace query (Plan 31) sees the whole tree, not just this root (Plan 33).
            with logfire.set_baggage(tenant_id=str(tenant.tenant_id)):
                result = await llm.triage(req)
        except (LLMError, httpx.HTTPStatusError, httpx.RequestError) as exc:
            ERRORS_TOTAL.add(1, {"endpoint": "sync", "status_code": "503"})
            span.set_attribute("error.kind", "llm_unavailable")
            raise HTTPException(status_code=503, detail="LLM service unavailable") from exc
        llm_latency_ms = (time.perf_counter() - t_llm) * 1000
        LLM_LATENCY_MS.record(llm_latency_ms, {"endpoint": "sync"})
        REQUESTS_TOTAL.add(1, {"endpoint": "sync", "category": str(result.category)})
        CONFIDENCE.record(result.confidence)
        RESPONSE_DRAFT_CHARS.record(len(result.draft_reply))
        span.set_attribute("triage.result.category", str(result.category))
        span.set_attribute("triage.result.confidence", result.confidence)
        # Surface the trace id so the UI can anchor the trace-debug chat (Plan 31) to
        # this request. Same 032x formatting the middleware uses for log correlation.
        span_ctx = span.get_span_context()
        if span_ctx is not None:
            result.trace_id = format(span_ctx.trace_id, "032x")
        background_tasks.add_task(_log_triage_result, req, result)
        background_tasks.add_task(
            persist_triage_log,
            req,
            result,
            getattr(request.state, "request_id", ""),
            llm_latency_ms,
            "sync",
            get_settings().groq_model,
            tenant.tenant_id,
        )
        return result


@router.post("/stream")
@limiter.limit("20/minute")  # type: ignore[reportUnknownMemberType]
async def triage_stream(
    request: Request, req: TriageRequest, llm: LLMDep, tenant: TenantDep
) -> StreamingResponse:
    t_start = time.perf_counter()

    # Manually manage the span so it stays open through the generator's lifecycle.
    span_ctx = logfire.span("triage.stream")
    span = span_ctx.__enter__()
    span.set_attribute("endpoint", "stream")
    # Root gets tenant_id explicitly (was missing on this endpoint); baggage below carries
    # it to the child spans created when the stream starts (Plan 33).
    span.set_attribute("tenant_id", str(tenant.tenant_id))
    span.set_attribute("email.subject_chars", len(req.subject))
    span.set_attribute("email.body_chars", len(req.body))
    REQUEST_BODY_CHARS.record(len(req.body))

    # Dynamic services carry the tenant's allowed slug set; coerce a hallucinated
    # slug to "unknown" so the SSE never surfaces a category that doesn't exist.
    allowed = llm.allowed_slugs

    def _coerce(category: object) -> str:
        cat = str(category)
        return UNKNOWN_SLUG if allowed is not None and cat not in allowed else cat

    stream_cm = llm.triage_stream(req)
    try:
        # The model-request / httpx child spans are created here, at __aenter__ (no yields
        # involved), so baggage set around it safely tags them with tenant_id (Plan 33).
        with logfire.set_baggage(tenant_id=str(tenant.tenant_id)):
            stream = await stream_cm.__aenter__()
    except LLMError as exc:
        ERRORS_TOTAL.add(1, {"endpoint": "stream", "status_code": "503"})
        span.set_attribute("error.kind", "llm_unavailable")
        span_ctx.__exit__(type(exc), exc, exc.__traceback__)
        raise HTTPException(status_code=503, detail="LLM service unavailable") from exc

    async def gen() -> AsyncGenerator[str]:
        emitted_text = ""
        emitted_meta = False
        first_emitted = False
        final: AnyStreamingResponse | None = None
        exc_info: tuple[type[BaseException] | None, BaseException | None, object] = (
            None,
            None,
            None,
        )
        try:
            async for partial in stream.stream_output(debounce_by=None):
                final = partial
                has_meta = partial.category is not None and partial.confidence is not None
                if not emitted_meta and has_meta:
                    meta = {"category": _coerce(partial.category), "confidence": partial.confidence}
                    chunk = f"event: meta\ndata: {json.dumps(meta)}\n\n"
                    if not first_emitted:
                        ttft_ms = (time.perf_counter() - t_start) * 1000
                        STREAM_TTFT_MS.record(ttft_ms)
                        span.set_attribute("triage.stream.ttft_ms", ttft_ms)
                        first_emitted = True
                    yield chunk
                    emitted_meta = True
                if len(partial.draft_reply) > len(emitted_text):
                    delta = partial.draft_reply[len(emitted_text) :]
                    chunk = f"data: {json.dumps(delta)}\n\n"
                    if not first_emitted:
                        ttft_ms = (time.perf_counter() - t_start) * 1000
                        STREAM_TTFT_MS.record(ttft_ms)
                        span.set_attribute("triage.stream.ttft_ms", ttft_ms)
                        first_emitted = True
                    yield chunk
                    emitted_text = partial.draft_reply
            yield "event: done\ndata: [DONE]\n\n"
        except BaseException as exc:
            exc_info = (type(exc), exc, exc.__traceback__)
            raise
        finally:
            # Nested try/finally guarantees span_ctx.__exit__ runs even if
            # stream_cm.__aexit__ raises (e.g. CancelledError on client disconnect).
            try:
                await stream_cm.__aexit__(*exc_info)
            finally:
                if (
                    final is not None
                    and final.category is not None
                    and final.confidence is not None
                ):
                    final_category = _coerce(final.category)
                    REQUESTS_TOTAL.add(1, {"endpoint": "stream", "category": final_category})
                    CONFIDENCE.record(final.confidence)
                    RESPONSE_DRAFT_CHARS.record(len(final.draft_reply))
                    span.set_attribute("triage.result.category", final_category)
                    span.set_attribute("triage.result.confidence", final.confidence)
                    _log.info(
                        "triage.stream.result",
                        category=final_category,
                        confidence=final.confidence,
                        sender=str(req.sender),
                    )
                span_ctx.__exit__(*exc_info)

    return StreamingResponse(gen(), media_type="text/event-stream")
