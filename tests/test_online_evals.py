"""Phase 6 — online evals. The cheap evaluators are pure and tested directly (no Groq);
the capability builder is tested via settings; /triage is unaffected when enabled."""

from dataclasses import dataclass
from typing import Any, cast

from email_triage.config import Settings
from email_triage.evals_online import (
    ConfidenceInRange,
    LanguageMatches,
    OutputNotEmpty,
    build_online_capability,
    looks_spanish,
)
from email_triage.schemas import Category, TriageResponse
from fastapi.testclient import TestClient
from pydantic_evals.evaluators import EvaluatorContext

from tests.conftest import TEST_API_KEY

_EvalCtx = EvaluatorContext[object, TriageResponse, object]


@dataclass
class _Ctx:
    """Minimal stand-in for EvaluatorContext — the evaluators only read .inputs/.output."""

    inputs: Any
    output: TriageResponse


def _ctx(inputs: object, output: TriageResponse) -> _EvalCtx:
    return cast(_EvalCtx, _Ctx(inputs, output))


def _resp(draft: str = "Gracias por tu mensaje", confidence: float = 0.9) -> TriageResponse:
    return TriageResponse(category=Category.STATUS, draft_reply=draft, confidence=confidence)


def test_output_not_empty() -> None:
    assert OutputNotEmpty().evaluate(_ctx("x", _resp("hola"))) is True
    assert OutputNotEmpty().evaluate(_ctx("x", _resp("   "))) is False


def test_confidence_in_range() -> None:
    assert ConfidenceInRange().evaluate(_ctx("x", _resp(confidence=0.0))) is True
    assert ConfidenceInRange().evaluate(_ctx("x", _resp(confidence=1.0))) is True
    # Pydantic clamps construction to [0,1], so test the predicate directly out of range.
    bad = _resp()
    object.__setattr__(bad, "confidence", 1.5)
    assert ConfidenceInRange().evaluate(_ctx("x", bad)) is False


def test_looks_spanish_heuristic() -> None:
    assert looks_spanish("¿Dónde está mi pedido?") is True
    assert looks_spanish("gracias por su envío") is True
    assert looks_spanish("Where is my order tracking") is False


def test_language_matches() -> None:
    # Spanish input + Spanish reply → match
    assert LanguageMatches().evaluate(_ctx("¿Dónde está mi pedido?", _resp("Su pedido va"))) is True
    # Spanish input + English reply → mismatch
    assert (
        LanguageMatches().evaluate(_ctx("¿Dónde está mi pedido?", _resp("Your order ships")))
        is False
    )


def test_build_capability_disabled() -> None:
    # Explicit kwargs outrank the repo .env (which may enable online evals).
    settings = Settings(  # type: ignore[call-arg]
        groq_api_key="k", api_key="k", database_url=None, online_eval_enabled=False
    )
    assert build_online_capability(settings) is None


def test_build_capability_enabled() -> None:
    settings = Settings(  # type: ignore[call-arg]
        groq_api_key="k",
        api_key="k",
        database_url=None,
        online_eval_enabled=True,
        online_eval_sample_rate=0.1,
        online_eval_max_concurrency=3,
    )
    capability = build_online_capability(settings)
    assert capability is not None


def test_triage_unaffected_with_online_evals(client: TestClient) -> None:
    # The mock LLM service is used via dependency override, so this proves the request
    # path and response shape are unchanged regardless of online-eval wiring.
    payload = {
        "subject": "Refund",
        "sender": "customer@test.com",
        "body": "I want my money back for order 1.",
    }
    response = client.post("/triage", json=payload, headers={"X-Api-Key": TEST_API_KEY})
    assert response.status_code == 200
    assert response.json()["category"] == "refunds"
