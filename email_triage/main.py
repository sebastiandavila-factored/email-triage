from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import logfire
import structlog
from fastapi import FastAPI
from logfire import SamplingOptions, ScrubbingOptions, ScrubMatch
from logfire.sampling import TailSamplingSpanInfo
from slowapi import _rate_limit_exceeded_handler  # type: ignore[reportPrivateImportUsage]
from slowapi.errors import RateLimitExceeded

from email_triage.db.engine import close_db, init_db
from email_triage.deps import get_llm_service, get_settings, limiter
from email_triage.middleware import RequestIdMiddleware
from email_triage.routers import auth, health, triage

_settings = get_settings()


def _scrub(match: ScrubMatch) -> str | None:
    sensitive = {
        "sender",
        "groq_api_key",
        "api_key",
        "x-api-key",
        "authorization",
        "database_url",
        "google_client_secret",
        "session_secret",
    }
    if match.path and str(match.path[-1]).lower() in sensitive:
        return "[REDACTED]"
    return None


def _tail_sampler(span_info: TailSamplingSpanInfo) -> float:
    if span_info.level in ("error", "warning"):
        return 1.0
    duration_s = (span_info.span.end_time or 0) - (span_info.span.start_time or 0)
    if duration_s > 5_000_000_000:  # 5 s in nanoseconds
        return 1.0
    return _settings.logfire_sample_rate


logfire.configure(
    service_name="email-triage",
    send_to_logfire="if-token-present",
    environment=_settings.logfire_environment,
    scrubbing=ScrubbingOptions(
        extra_patterns=["sender"],
        callback=_scrub,
    ),
    sampling=SamplingOptions(
        head=_settings.logfire_sample_rate,
        tail=_tail_sampler,
    ),
)
logfire.instrument_pydantic_ai()
logfire.instrument_pydantic()
logfire.instrument_system_metrics()
logfire.instrument_httpx()

_log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    llm = get_llm_service()
    if settings.database_url:
        init_db(settings.database_url)
        _log.info("db.connected")
    _log.info("startup", groq_model=settings.groq_model)
    yield
    await llm.aclose()
    await close_db()
    _log.info("shutdown")


app = FastAPI(
    title="Email Triage API",
    summary="Classify support emails and draft replies in <3 seconds.",
    version="0.1.0",
    description=(
        "AI-powered triage layer for e-commerce support inboxes. "
        "Powered by Groq + Pydantic AI. "
        "Three endpoints: `/triage`, `/triage/stream`, `/health`. "
        "Auth via `X-API-Key` header."
    ),
    contact={
        "name": "Seba Davila",
        "email": "sebastian.davila@factored.ai",
    },
    license_info={"name": "MIT"},
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(RequestIdMiddleware)

# CORS is only needed when the browser calls the API from a different origin
# (prod: Vercel frontend → Render API). No allow_credentials: auth travels in
# the Authorization/X-Api-Key headers, not cookies. Added last → outermost, so
# preflight OPTIONS is answered before the rest of the stack runs.
if _settings.cors_origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "x-api-key", "content-type"],
    )

app.include_router(health.router)
app.include_router(triage.router)
app.include_router(auth.router)

logfire.instrument_fastapi(app)
