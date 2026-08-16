"""Triage tuning copilot (Plan 44): orchestrator loop, draft-only writes, isolation, RBAC.

No network: the orchestrator runs on a pydantic-ai ``FunctionModel`` that scripts the tool
sequence; diagnosis and the draft classifier are fakes. Draft edits run against a seeded SQLite
so the tools are exercised for real (only Groq/Logfire are stubbed)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from email_triage.auth.session import create_access_token
from email_triage.config import Settings
from email_triage.db import engine as db_engine_module
from email_triage.db.base import Base
from email_triage.db.models import Membership, Tenant, User
from email_triage.db.repos.categories import CategoryRepo
from email_triage.db.repos.examples import ExampleRepo
from email_triage.db.repos.prompts import PromptVersionRepo
from email_triage.deps import get_settings
from email_triage.main import app
from email_triage.routers.tuning import get_tuning_runner
from email_triage.schemas import TraceDiagnosis, TriageRequest
from email_triage.services.prompt_studio import PromptStudioService
from email_triage.services.triage_config import TriageConfigService
from email_triage.services.tuning import TuningRunner, build_tuning_agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_SECRET = "tuning-test-secret-32-bytes-pad!!"
_TRACE = "a" * 32


# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeDiagnosis:
    async def diagnose(self, tenant_id: str, trace_id: str) -> TraceDiagnosis:
        return TraceDiagnosis(
            root_cause="the model over-picks 'refunds' on billing emails",
            evidence=[],
            confidence=0.6,
            suggested_fix_kind="add_counter_example",
            target_slug="refunds",
            rationale="a billing notice was classified as refunds",
        )


class FakeClassifier:
    """Returns a canned prediction per email subject (default 'unknown')."""

    def __init__(self, by_subject: dict[str, str]) -> None:
        self.by_subject = by_subject

    async def classify(self, prompt: str, allowed_slugs: frozenset[str], req: TriageRequest) -> str:
        return self.by_subject.get(req.subject, "unknown")


def _steps(messages: list[ModelMessage]) -> int:
    return sum(1 for m in messages for p in m.parts if isinstance(p, ToolReturnPart))


def _driver(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """diagnose → add_counter_example('refunds') → run_check → recommendation."""
    step = _steps(messages)
    if step == 0:
        return ModelResponse(parts=[ToolCallPart(tool_name="diagnose", args={"focus": "why"})])
    if step == 1:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="add_counter_example",
                    args={
                        "slug": "refunds",
                        "subject": "Invoice A-42",
                        "body": "Payment due 28/02.",
                    },
                )
            ]
        )
    if step == 2:
        return ModelResponse(parts=[ToolCallPart(tool_name="run_check", args={"note": "after"})])
    return ModelResponse(
        parts=[
            TextPart(
                "Added a counter-example to refunds; the flagged email now classifies "
                "correctly with no regressions. Recommend publishing."
            )
        ]
    )


def _driver_bad_slug(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    step = _steps(messages)
    if step == 0:
        return ModelResponse(parts=[ToolCallPart(tool_name="diagnose", args={"focus": "why"})])
    if step == 1:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="add_counter_example",
                    args={"slug": "does-not-exist", "subject": "S", "body": "B"},
                )
            ]
        )
    return ModelResponse(parts=[TextPart("Could not find that category.")])


_TARGET = TriageRequest(
    subject="Refund my order please", sender="c@x.com", body="I want my money back"
)


# ── Fixture: seeded SQLite (categories incl. 'refunds') + client ────────────────


def _settings() -> Settings:
    # logfire_read_token=None so the un-overridden runner resolves to None → 503.
    return Settings(  # type: ignore[call-arg]
        groq_api_key="x",
        api_key="x",
        database_url=None,
        session_secret=_SECRET,
        bcrypt_rounds=4,
        logfire_read_token=None,
    )


def _bearer(user_id: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(_SECRET, user_id)}"}


@pytest.fixture()
async def tuned(tmp_path: Any) -> AsyncGenerator[SimpleNamespace]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/tune.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    db_engine_module._session_factory = factory  # type: ignore[attr-defined]

    async with factory() as session, session.begin():
        owner = User(email="owner@acme.com", display_name="Owner", email_verified=True)
        member = User(email="member@acme.com", display_name="Member", email_verified=True)
        session.add_all([owner, member])
        await session.flush()
        team = Tenant(name="Acme", type="team", domain=None)
        session.add(team)
        await session.flush()
        session.add_all(
            [
                Membership(user_id=owner.id, tenant_id=team.id, role="owner"),
                Membership(user_id=member.id, tenant_id=team.id, role="member"),
            ]
        )
        await TriageConfigService().seed_defaults(session, team.id)
        ids = SimpleNamespace(owner=owner.id, member=member.id, team=team.id)

    ids.factory = factory
    app.dependency_overrides[get_settings] = _settings
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ids.client = client
        yield ids
    app.dependency_overrides.clear()
    db_engine_module._session_factory = None  # type: ignore[attr-defined]
    await engine.dispose()


def _runner(driver: Any, classifier: FakeClassifier) -> TuningRunner:
    return TuningRunner(
        agent=build_tuning_agent(FunctionModel(driver)),
        diagnosis=FakeDiagnosis(),
        classifier=classifier,
    )


async def _run(tuned: SimpleNamespace, runner: TuningRunner, *, expected: str = "refunds") -> Any:
    return await runner.run(
        factory=tuned.factory,
        tenant_id=tuned.team,
        user_id=tuned.owner,
        trace_id=_TRACE,
        email=_TARGET,
        expected_slug=expected,
    )


# ── Service loop ────────────────────────────────────────────────────────────────


async def test_tuning_fixes_target_edits_draft_and_never_publishes(tuned: SimpleNamespace) -> None:
    runner = _runner(_driver, FakeClassifier({"Refund my order please": "refunds"}))
    proposal = await _run(tuned, runner)

    assert proposal.diagnosis is not None
    assert proposal.diagnosis.suggested_fix_kind == "add_counter_example"
    assert proposal.changes == ["added counter-example to 'refunds'"]
    assert proposal.score_after is not None and proposal.score_after.target_fixed is True
    assert proposal.gate_passed is True
    assert proposal.cycles == 1

    async with tuned.factory() as s:
        # never published
        assert await PromptVersionRepo().active(s, tuned.team) is None
        # the counter-example landed in the draft (a negative example on 'refunds')
        cat = await CategoryRepo().get_by_slug(s, tuned.team, "refunds")
        assert cat is not None
        exs = await ExampleRepo().list_for_category(s, tuned.team, cat.id)
        assert any(e.kind == "negative" for e in exs)


async def test_tuning_gate_fails_when_target_not_fixed(tuned: SimpleNamespace) -> None:
    runner = _runner(_driver, FakeClassifier({"Refund my order please": "shipments"}))  # wrong
    proposal = await _run(tuned, runner)
    assert proposal.score_after is not None and proposal.score_after.target_fixed is False
    assert proposal.gate_passed is False


async def test_holdout_regression_blocks_gate(tuned: SimpleNamespace) -> None:
    # Seed a positive few-shot → it becomes a hold-out regression guard.
    async with tuned.factory() as s, s.begin():
        cat = await CategoryRepo().get_by_slug(s, tuned.team, "shipments")
        assert cat is not None
        await PromptStudioService().add_example(
            s, tuned.team, cat.id, "positive", "Where is my package", "tracking?", "Soon!", None
        )
    # Target fixed (refunds) but the hold-out 'Where is my package' is misclassified.
    classifier = FakeClassifier(
        {"Refund my order please": "refunds", "Where is my package": "refunds"}
    )
    proposal = await _run(tuned, _runner(_driver, classifier))
    assert proposal.score_after is not None
    assert proposal.score_after.target_fixed is True
    assert proposal.score_after.regressions >= 1
    assert proposal.gate_passed is False


async def test_bad_slug_is_rejected_with_no_write(tuned: SimpleNamespace) -> None:
    runner = _runner(_driver_bad_slug, FakeClassifier({}))
    proposal = await _run(tuned, runner)
    assert proposal.changes == []  # the failed tool recorded nothing
    async with tuned.factory() as s:
        cat = await CategoryRepo().get_by_slug(s, tuned.team, "refunds")
        assert cat is not None
        assert await ExampleRepo().list_for_category(s, tuned.team, cat.id) == []


# ── Endpoint RBAC + guard ───────────────────────────────────────────────────────


def _body() -> dict[str, Any]:
    return {
        "trace_id": _TRACE,
        "email": {"subject": "Refund my order please", "sender": "c@x.com", "body": "money back"},
        "expected_category": "refunds",
    }


async def test_tune_endpoint_not_configured_returns_503(tuned: SimpleNamespace) -> None:
    # No runner override → real provider sees no read token → None → 503.
    resp = await tuned.client.post(
        f"/workspaces/{tuned.team}/tune", headers=_bearer(tuned.owner), json=_body()
    )
    assert resp.status_code == 503


async def test_tune_endpoint_member_forbidden(tuned: SimpleNamespace) -> None:
    app.dependency_overrides[get_tuning_runner] = lambda: SimpleNamespace()  # never reached
    resp = await tuned.client.post(
        f"/workspaces/{tuned.team}/tune", headers=_bearer(tuned.member), json=_body()
    )
    assert resp.status_code == 403
    assert "prompt:publish" in resp.json()["detail"]


async def test_tune_endpoint_owner_happy(tuned: SimpleNamespace) -> None:
    runner = _runner(_driver, FakeClassifier({"Refund my order please": "refunds"}))
    app.dependency_overrides[get_tuning_runner] = lambda: runner
    resp = await tuned.client.post(
        f"/workspaces/{tuned.team}/tune", headers=_bearer(tuned.owner), json=_body()
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["gate_passed"] is True
    assert data["changes"] == ["added counter-example to 'refunds'"]
