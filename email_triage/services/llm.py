from contextlib import asynccontextmanager
from typing import Final

from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.settings import ModelSettings

from email_triage.observability import LLM_ERRORS_TOTAL, LLM_IN_FLIGHT
from email_triage.schemas import StreamingTriageResponse, TriageRequest, TriageResponse

DEFAULT_MODEL: Final = "llama-3.3-70b-versatile"

SYSTEM_PROMPT: Final = """You are an email triage system for an e-commerce support inbox.

Classify the user's email into EXACTLY ONE category:
- status: question about the status of an order
- refunds: question about refund eligibility or process
- availability: question about product availability or stock
- shipments: question about shipping times, costs or methods
- prices: question about prices, discounts or promotions

Write a polite, brief and professional reply in the same language as the email.
Estimate your confidence between 0 and 1."""


class LLMError(RuntimeError):
    """Raised when the LLM backend returns an error or unexpected output."""


class LLMService:
    """Pydantic AI wrapper for Groq. Same public interface as the httpx version."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        groq_model = GroqModel(model, provider=GroqProvider(api_key=api_key))
        self._agent: Agent[None, TriageResponse] = Agent(
            groq_model,
            output_type=TriageResponse,
            system_prompt=SYSTEM_PROMPT,
            model_settings=ModelSettings(temperature=0.2),
        )

    async def triage(self, req: TriageRequest) -> TriageResponse:
        user_msg = f"Subject: {req.subject}\nFrom: {req.sender}\n\n{req.body}"
        LLM_IN_FLIGHT.add(1)
        try:
            result = await self._agent.run(user_msg)
        except Exception as exc:
            LLM_ERRORS_TOTAL.add(1, {"error_class": type(exc).__name__})
            raise LLMError(str(exc)) from exc
        finally:
            LLM_IN_FLIGHT.add(-1)
        return result.output

    @asynccontextmanager
    async def triage_stream(self, req: TriageRequest):  # type: ignore[return]
        user_msg = f"Subject: {req.subject}\nFrom: {req.sender}\n\n{req.body}"
        LLM_IN_FLIGHT.add(1)
        try:
            async with self._agent.run_stream(
                user_msg,
                output_type=PromptedOutput(StreamingTriageResponse),
            ) as result:
                yield result
        except Exception as exc:
            LLM_ERRORS_TOTAL.add(1, {"error_class": type(exc).__name__})
            raise LLMError(str(exc)) from exc
        finally:
            LLM_IN_FLIGHT.add(-1)

    async def aclose(self) -> None:
        pass  # Pydantic AI manages its own client lifecycle; placeholder for Day 6 lifespan
