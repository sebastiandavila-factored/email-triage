from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import Final

from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.settings import ModelSettings

from email_triage.config import DEFAULT_GROQ_MODEL
from email_triage.observability import LLM_ERRORS_TOTAL, LLM_IN_FLIGHT
from email_triage.schemas import (
    AnyTriageResponse,
    DynamicStreamingTriageResponse,
    DynamicTriageResponse,
    StreamingTriageResponse,
    TriageRequest,
    TriageResponse,
)
from email_triage.services.groq import build_groq_model
from email_triage.services.prompt_compiler import UNKNOWN_SLUG, render_email

# Re-exported under the local name; the actual value lives in config (one source
# of truth). Only used when a caller omits `model=` — the real path always passes
# settings.groq_model.
DEFAULT_MODEL: Final = DEFAULT_GROQ_MODEL

SYSTEM_PROMPT: Final = """You are an email triage system for an e-commerce support inbox.

Classify the user's email into EXACTLY ONE category:
- status: question about the status of an order
- refunds: question about refund eligibility or process
- availability: question about product availability or stock
- shipments: question about shipping times, costs or methods
- prices: question about prices, discounts or promotions

Write a polite, brief and professional reply in the same language as the email.
Estimate your confidence between 0 and 1."""

# Output types for each path. Legacy pins ``category`` to the frozen enum; dynamic
# widens it to ``str`` (arbitrary tenant slug), validated post-hoc against
# ``allowed_slugs``.
_OutputType = type[TriageResponse] | type[DynamicTriageResponse]
_StreamingOutputType = type[StreamingTriageResponse] | type[DynamicStreamingTriageResponse]


class LLMError(RuntimeError):
    """Raised when the LLM backend returns an error or unexpected output."""


class LLMService:
    """Pydantic AI wrapper for Groq. One instance per (tenant, taxonomy version);
    the legacy singleton uses the enum output type and the static SYSTEM_PROMPT."""

    # Class-level default so test doubles that skip __init__ still expose it (the
    # stream router reads llm.allowed_slugs to coerce hallucinated slugs).
    allowed_slugs: frozenset[str] | None = None

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        system_prompt: str = SYSTEM_PROMPT,
        capabilities: Sequence[AbstractCapability[None]] | None = None,
        output_type: _OutputType = TriageResponse,
        streaming_output_type: _StreamingOutputType = StreamingTriageResponse,
        allowed_slugs: frozenset[str] | None = None,
    ) -> None:
        groq_model = build_groq_model(model, api_key)
        # allowed_slugs != None marks the dynamic path: the email is sent wrapped in
        # <email> tags (the compiled prompt references them) and the category is
        # coerced against the allowed set.
        self.allowed_slugs = allowed_slugs
        self._streaming_output_type = streaming_output_type
        self._agent: Agent[None, AnyTriageResponse] = Agent(
            groq_model,
            output_type=output_type,
            system_prompt=system_prompt,
            model_settings=ModelSettings(temperature=0.2),
            capabilities=capabilities,
        )

    def _user_message(self, req: TriageRequest) -> str:
        if self.allowed_slugs is not None:
            return render_email(req.subject, str(req.sender), req.body)
        return f"Subject: {req.subject}\nFrom: {req.sender}\n\n{req.body}"

    async def triage(self, req: TriageRequest) -> AnyTriageResponse:
        LLM_IN_FLIGHT.add(1)
        try:
            result = await self._agent.run(self._user_message(req))
        except Exception as exc:
            LLM_ERRORS_TOTAL.add(1, {"error_class": type(exc).__name__})
            raise LLMError(str(exc)) from exc
        finally:
            LLM_IN_FLIGHT.add(-1)
        out = result.output
        # Post-hoc guard: the model may emit a slug that no longer exists → unknown.
        if (
            isinstance(out, DynamicTriageResponse)
            and self.allowed_slugs is not None
            and out.category not in self.allowed_slugs
        ):
            out.category = UNKNOWN_SLUG
        return out

    @asynccontextmanager
    async def triage_stream(self, req: TriageRequest):  # type: ignore[return]
        LLM_IN_FLIGHT.add(1)
        try:
            async with self._agent.run_stream(
                self._user_message(req),
                output_type=PromptedOutput(self._streaming_output_type),
            ) as result:
                yield result
        except Exception as exc:
            LLM_ERRORS_TOTAL.add(1, {"error_class": type(exc).__name__})
            raise LLMError(str(exc)) from exc
        finally:
            LLM_IN_FLIGHT.add(-1)

    async def aclose(self) -> None:
        pass  # Pydantic AI manages its own client lifecycle; placeholder for lifespan
