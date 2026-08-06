"""Trace-debug chat (Plan 31): SQL isolation, agent guardrail, and endpoint RBAC.

No network: the Logfire client is a fake that records SQL, and the agent runs on
pydantic-ai's ``TestModel`` (which calls every tool once), so we never touch Groq or
Logfire. The HTTP tests mirror ``test_workspaces_api`` (ASGITransport + seeded SQLite)."""

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
from email_triage.routers.traces import get_trace_chat_service
from email_triage.services.trace_agent import (
    LogfireQueryError,
    TraceChatService,
    build_trace_agent,
    ensure_trace_id,
    recent_org_sql,
    trace_spans_sql,
)
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_SECRET = "traces-test-secret-32-bytes-pad!!"
_TENANT = "11111111-1111-1111-1111-111111111111"
_TRACE = "a" * 32


# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeLogfireClient:
    """Records every SQL it's asked to run and returns canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else [{"span_name": "triage.sync", "level": 9}]
        self.queries: list[str] = []

    async def query(self, sql: str) -> list[dict[str, Any]]:
        self.queries.append(sql)
        return self.rows


# ── Unit: SQL builders always carry the tenant predicate ────────────────────────


def test_spans_sql_binds_tenant_and_trace() -> None:
    sql = trace_spans_sql(_TENANT, _TRACE)
    assert f"attributes->>'tenant_id' = '{_TENANT}'" in sql
    assert f"trace_id = '{_TRACE}'" in sql


def test_recent_sql_binds_tenant_and_caps_limit() -> None:
    sql = recent_org_sql(_TENANT, limit=999)
    assert f"attributes->>'tenant_id' = '{_TENANT}'" in sql
    assert "LIMIT 50" in sql  # clamped


def test_invalid_trace_id_rejected() -> None:
    with pytest.raises(LogfireQueryError):
        ensure_trace_id("not-a-trace")
    with pytest.raises(LogfireQueryError):
        trace_spans_sql(_TENANT, "xyz")


def test_invalid_tenant_id_rejected() -> None:
    with pytest.raises(LogfireQueryError):
        trace_spans_sql("'; DROP TABLE records; --", _TRACE)


# ── Agent guardrail: every query the agent issues is tenant-scoped ──────────────


async def test_agent_only_ever_queries_own_tenant() -> None:
    fake = FakeLogfireClient()
    svc = TraceChatService(build_trace_agent(TestModel()), fake)

    reply = await svc.chat(_TENANT, _TRACE, "why was this slow?", [])

    assert isinstance(reply, str)
    assert fake.queries, "the agent should have queried Logfire"
    # Structural isolation: not one query can omit the tenant predicate.
    assert all(f"attributes->>'tenant_id' = '{_TENANT}'" in q for q in fake.queries)


async def test_owns_trace_false_when_no_rows() -> None:
    empty = FakeLogfireClient(rows=[])
    svc = TraceChatService(build_trace_agent(TestModel()), empty)
    assert await svc.owns_trace(_TENANT, _TRACE) is False


def test_tools_take_a_parameter_for_groq() -> None:
    # Regression: Groq sends `null` (not `{}`) as arguments for a zero-parameter tool, which
    # fails pydantic-ai's object-schema validation and exhausts retries. Every tool must take
    # at least one parameter beyond `ctx`.
    import inspect

    from email_triage.services.trace_agent import get_trace_spans, search_recent_org_traces

    for fn in (get_trace_spans, search_recent_org_traces):
        params = [p for p in inspect.signature(fn).parameters if p != "ctx"]
        assert params, f"{fn.__name__} must take >=1 param (Groq null-args quirk)"


async def test_agent_failure_becomes_logfire_query_error() -> None:
    # A model/tool blow-up must surface as our actionable error (→ 503), never a raw 500.
    class BoomAgent:
        async def run(self, *a: Any, **k: Any) -> Any:
            raise ValueError("model exploded")

    svc = TraceChatService(BoomAgent(), FakeLogfireClient())  # type: ignore[arg-type]
    with pytest.raises(LogfireQueryError):
        await svc.chat(_TENANT, _TRACE, "hi", [])


# ── Endpoint RBAC + guard ───────────────────────────────────────────────────────


def _settings_no_token() -> Settings:
    # Force logfire_read_token=None so a real value in the dev .env can't leak in and
    # flip the "not configured" (503) path.
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
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/traces.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    db_engine_module._session_factory = factory  # type: ignore[attr-defined]

    async with factory() as session, session.begin():
        owner = User(email="owner@acme.com", display_name="Owner", email_verified=True)
        admin = User(email="admin@acme.com", display_name="Admin", email_verified=True)
        member = User(email="member@acme.com", display_name="Member", email_verified=True)
        outsider = User(email="out@evil.com", display_name="Out", email_verified=True)
        session.add_all([owner, admin, member, outsider])
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
        ids = SimpleNamespace(
            owner=owner.id, admin=admin.id, member=member.id, outsider=outsider.id, team=team.id
        )

    app.dependency_overrides[get_settings] = _settings_no_token
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ids.client = client
        yield ids
    app.dependency_overrides.clear()
    db_engine_module._session_factory = None  # type: ignore[attr-defined]
    await engine.dispose()


def _override_service(service: Any) -> None:
    app.dependency_overrides[get_trace_chat_service] = lambda: service


def _body(**kw: Any) -> dict[str, Any]:
    return {"trace_id": _TRACE, "message": "why?", **kw}


async def test_unauthenticated_401(tw: SimpleNamespace) -> None:
    resp = await tw.client.post(f"/workspaces/{tw.team}/traces/chat", json=_body())
    assert resp.status_code == 401


async def test_member_forbidden(tw: SimpleNamespace) -> None:
    _override_service(SimpleNamespace())  # never reached; scope check fails first
    resp = await tw.client.post(
        f"/workspaces/{tw.team}/traces/chat", headers=_bearer(tw.member), json=_body()
    )
    assert resp.status_code == 403
    assert "traces:read" in resp.json()["detail"]


async def test_outsider_forbidden_idor(tw: SimpleNamespace) -> None:
    _override_service(SimpleNamespace())
    resp = await tw.client.post(
        f"/workspaces/{tw.team}/traces/chat", headers=_bearer(tw.outsider), json=_body()
    )
    assert resp.status_code == 403


async def test_not_configured_returns_503(tw: SimpleNamespace) -> None:
    # No override → real provider sees no read token (settings) → None → 503.
    resp = await tw.client.post(
        f"/workspaces/{tw.team}/traces/chat", headers=_bearer(tw.owner), json=_body()
    )
    assert resp.status_code == 503


@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_owner_and_admin_get_reply(tw: SimpleNamespace, role: str) -> None:
    class FakeService:
        async def owns_trace(self, tenant_id: str, trace_id: str) -> bool:
            assert tenant_id == str(tw.team)  # tenant comes from membership, not body
            return True

        async def chat(
            self, tenant_id: str, trace_id: str, message: str, history: list[Any]
        ) -> str:
            return "The triage took 1.2s; category=refunds, confidence 0.95."

    _override_service(FakeService())
    resp = await tw.client.post(
        f"/workspaces/{tw.team}/traces/chat", headers=_bearer(getattr(tw, role)), json=_body()
    )
    assert resp.status_code == 200, resp.text
    assert "refunds" in resp.json()["reply"]


async def test_foreign_trace_returns_404(tw: SimpleNamespace) -> None:
    class FakeService:
        async def owns_trace(self, tenant_id: str, trace_id: str) -> bool:
            return False  # trace belongs to another org / doesn't exist

        async def chat(self, *a: Any, **k: Any) -> str:  # pragma: no cover
            raise AssertionError("chat must not run when ownership fails")

    _override_service(FakeService())
    resp = await tw.client.post(
        f"/workspaces/{tw.team}/traces/chat", headers=_bearer(tw.owner), json=_body()
    )
    assert resp.status_code == 404


async def test_bad_trace_id_shape_maps_to_422(tw: SimpleNamespace) -> None:
    class FakeService:
        async def owns_trace(self, tenant_id: str, trace_id: str) -> bool:
            raise LogfireQueryError("invalid trace id (expected 32 hex chars)")

        async def chat(self, *a: Any, **k: Any) -> str:  # pragma: no cover
            raise AssertionError

    _override_service(FakeService())
    resp = await tw.client.post(
        f"/workspaces/{tw.team}/traces/chat",
        headers=_bearer(tw.owner),
        json=_body(trace_id="zzzz"),
    )
    assert resp.status_code == 422
