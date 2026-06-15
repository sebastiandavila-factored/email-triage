import logging
import time
import uuid

import structlog
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars
from structlog.types import EventDict, WrappedLogger


def _add_trace_context(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


structlog.configure(
    processors=[
        merge_contextvars,
        structlog.stdlib.add_log_level,
        _add_trace_context,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

_log = structlog.get_logger()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        # Expose the id to handlers (e.g. triage_logs.request_id) — the response
        # header alone is not visible to the route that produces the log.
        request.state.request_id = request_id

        clear_contextvars()
        bind_contextvars(request_id=request_id)

        _log.info("request.start", method=request.method, path=request.url.path)

        response = await call_next(request)

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        _log.info("request.end", status=response.status_code, elapsed_ms=elapsed_ms)

        response.headers["X-Request-Id"] = request_id
        return response
