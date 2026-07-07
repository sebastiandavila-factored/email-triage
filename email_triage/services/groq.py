"""Shared Groq model factory with rate-limit-aware retries.

Groq's free tier enforces a tokens-per-minute (TPM) limit; bursty eval runs
hit HTTP 429. This wires the underlying httpx client with a tenacity transport
that retries 429s (and transient 5xx / network blips), honoring the server's
suggested wait — Groq returns a `retry-after` — with an exponential fallback.

Both the triage service and the eval judge build their models through here, so
every LLM call across every eval suite inherits the same resilience.
"""

from __future__ import annotations

import httpx
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from tenacity import retry_if_exception, stop_after_attempt, wait_exponential

_MAX_ATTEMPTS = 6
_MAX_WAIT_S = 30.0
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def _is_retryable(exc: BaseException) -> bool:
    # Retry rate limits and transient server/network errors; let 4xx client
    # errors (400/401/403) fail fast instead of burning attempts.
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return isinstance(exc, httpx.TransportError)


def _retrying_async_client() -> httpx.AsyncClient:
    config: RetryConfig = {
        "retry": retry_if_exception(_is_retryable),
        # Honor Groq's `retry-after`; if absent, back off exponentially.
        "wait": wait_retry_after(
            fallback_strategy=wait_exponential(multiplier=1, max=_MAX_WAIT_S),
            max_wait=_MAX_WAIT_S,
        ),
        "stop": stop_after_attempt(_MAX_ATTEMPTS),
        "reraise": True,
    }
    transport = AsyncTenacityTransport(
        config=config,
        validate_response=lambda r: r.raise_for_status(),  # 4xx/5xx → HTTPStatusError
    )
    return httpx.AsyncClient(transport=transport)


def build_groq_model(model: str, api_key: str) -> GroqModel:
    """A GroqModel whose HTTP client retries rate-limit (429) responses."""
    provider = GroqProvider(api_key=api_key, http_client=_retrying_async_client())
    return GroqModel(model, provider=provider)
