"""Trace diagnosis (Plan 43): structured verdict, SQL isolation, endpoint RBAC.

No network: the Logfire client is a fake that records SQL, and the agent runs on
pydantic-ai's ``TestModel`` (which calls every tool once and synthesizes the structured
output), so we never touch Groq or Logfire. HTTP tests mirror ``test_traces_chat``."""

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
from email_triage.deps import get_settings
from email_triage.main import app
from email_triage.routers.traces import get_trace_diagnosis_service
from email_triage.schemas import TraceDiagnosis
from email_triage.services.trace_agent import (
    LogfireQueryError,
    TraceDiagnosisService,
    build_diagnosis_agent,
)
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_SECRET = "traces-test-secret-32-bytes-pad!!"
_TENANT = "11111111-1111-1111-1111-111111111111"
_TRACE = "a" * 32


class FakeLogfireClient:
    """Records every SQL it's asked to run and returns canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else [{"span_name": "triage.sync", "level": 9}]
        self.queries: list[str] = []

    async def query(self, sql: str) -> list[dict[str, Any]]:
        self.queries.append(sql)
        return self.rows


# ── Service: structured output, isolation, loop signal, error mapping ───────────


async def test_diagnose_returns_structured_verdict() -> None:
    svc = TraceDiagnosisService(build_diagnosis_agent(TestModel()), FakeLogfireClient())
    diag = await svc.diagnose(_TENANT, _TRACE)
    assert isinstance(diag, TraceDiagnosis)
    assert 0.0 <= diag.confidence <= 1.0
    assert diag.suggested_fix_kind in {
        "add_counter_example",
        "tweak_category",
        "adjust_examples",
        "none",
    }


async def test_diagnosis_agent_queries_are_tenant_scoped_and_looped() -> None:
    fake = FakeLogfireClient()
    svc = TraceDiagnosisService(build_diagnosis_agent(TestModel()), fake)

    await svc.diagnose(_TENANT, _TRACE)

    # Loop signal (for Plan 42): the agent calls more than one curated tool.
    assert len(fake.queries) >= 2, "the agent should issue multiple tool queries"
    # Structural isolation: not one query can omit the tenant predicate.
    assert all(f"attributes->>'tenant_id' = '{_TENANT}'" in q for q in fake.queries)


async def test_diagnosis_owns_trace_false_when_no_rows() -> None:
    svc = TraceDiagnosisService(build_diagnosis_agent(TestModel()), FakeLogfireClient(rows=[]))
    assert await svc.owns_trace(_TENANT, _TRACE) is False


async def test_diagnosis_owns_trace_rejects_bad_trace_id() -> None:
    svc = TraceDiagnosisService(build_diagnosis_agent(TestModel()), FakeLogfireClient())
    with pytest.raises(LogfireQueryError):
        await svc.owns_trace(_TENANT, "not-a-trace")


async def test_diagnosis_agent_failure_becomes_logfire_query_error() -> None:
    class BoomAgent:
        async def run(self, *a: Any, **k: Any) -> Any:
            raise ValueError("model exploded")

    svc = TraceDiagnosisService(BoomAgent(), FakeLogfireClient())  # type: ignore[arg-type]
    with pytest.raises(LogfireQueryError):
        await svc.diagnose(_TENANT, _TRACE)


# ── Endpoint RBAC + guard ───────────────────────────────────────────────────────


def _settings_no_token() -> Settings:
    # Force logfire_read_token=None so a real value in the dev .env can't flip the 503 path.
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
async def tw(tmp_path: Any) -> AsyncGenerator[SimpleNamespace]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/diagnose.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    db_engine_module._session_factory = factory  # type: ignore[attr-defined]

    async with factory() as session, session.begin():
        owner = User(email="owner@acme.com", display_name="Owner", email_verified=True)
        admin = User(email="admin@acme.com", display_name="Admin", email_verified=True)
        member = User(email="member@acme.com", display_name="Member", email_verified=True)
        session.add_all([owner, admin, member])
        await session.flush()
        team = Tenant(name="Acme", type="team", domain=None)
        session.add(team)
        await session.flush()
        session.add_all(
            [
                Membership(user_id=owner.id, tenant_id=team.id, role="owner"),
                Membership(user_id=admin.id, tenant_id=team.id, role="admin"),
                Membership(user_id=member.id, tenant_id=team.id, role="member"),
            ]
        )
        ids = SimpleNamespace(owner=owner.id, admin=admin.id, member=member.id, team=team.id)

    app.dependency_overrides[get_settings] = _settings_no_token
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ids.client = client
        yield ids
    app.dependency_overrides.clear()
    db_engine_module._session_factory = None  # type: ignore[attr-defined]
    await engine.dispose()


def _override_service(service: Any) -> None:
    app.dependency_overrides[get_trace_diagnosis_service] = lambda: service


def _url(tw: SimpleNamespace, trace_id: str = _TRACE) -> str:
    return f"/workspaces/{tw.team}/traces/{trace_id}/diagnose"


async def test_diagnose_unauthenticated_401(tw: SimpleNamespace) -> None:
    resp = await tw.client.post(_url(tw))
    assert resp.status_code == 401


async def test_diagnose_member_forbidden(tw: SimpleNamespace) -> None:
    _override_service(SimpleNamespace())  # never reached; scope check fails first
    resp = await tw.client.post(_url(tw), headers=_bearer(tw.member))
    assert resp.status_code == 403
    assert "traces:read" in resp.json()["detail"]


async def test_diagnose_not_configured_returns_503(tw: SimpleNamespace) -> None:
    # No override → real provider sees no read token → None → 503.
    resp = await tw.client.post(_url(tw), headers=_bearer(tw.owner))
    assert resp.status_code == 503


@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_diagnose_owner_and_admin_get_verdict(tw: SimpleNamespace, role: str) -> None:
    class FakeService:
        async def owns_trace(self, tenant_id: str, trace_id: str) -> bool:
            assert tenant_id == str(tw.team)  # tenant comes from membership, not path spoofing
            return True

        async def diagnose(self, tenant_id: str, trace_id: str) -> TraceDiagnosis:
            return TraceDiagnosis(
                root_cause="slow LLM step",
                evidence=[],
                confidence=0.9,
                suggested_fix_kind="none",
                target_slug=None,
                rationale="1.2s spent in the groq call",
            )

    _override_service(FakeService())
    resp = await tw.client.post(_url(tw), headers=_bearer(getattr(tw, role)))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["root_cause"] == "slow LLM step"
    assert body["suggested_fix_kind"] == "none"


async def test_diagnose_foreign_trace_returns_404(tw: SimpleNamespace) -> None:
    class FakeService:
        async def owns_trace(self, tenant_id: str, trace_id: str) -> bool:
            return False  # trace belongs to another org / doesn't exist

        async def diagnose(self, *a: Any, **k: Any) -> TraceDiagnosis:  # pragma: no cover
            raise AssertionError("diagnose must not run when ownership fails")

    _override_service(FakeService())
    resp = await tw.client.post(_url(tw), headers=_bearer(tw.owner))
    assert resp.status_code == 404


async def test_diagnose_bad_trace_id_maps_to_422(tw: SimpleNamespace) -> None:
    class FakeService:
        async def owns_trace(self, tenant_id: str, trace_id: str) -> bool:
            raise LogfireQueryError("invalid trace id (expected 32 hex chars)")

        async def diagnose(self, *a: Any, **k: Any) -> TraceDiagnosis:  # pragma: no cover
            raise AssertionError

    _override_service(FakeService())
    resp = await tw.client.post(_url(tw, trace_id="zzzz"), headers=_bearer(tw.owner))
    assert resp.status_code == 422
