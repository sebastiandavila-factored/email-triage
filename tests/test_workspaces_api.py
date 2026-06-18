"""HTTP-level tests for the /workspaces router (Plan 21): scope enforcement and
object-level authorization (IDOR). Uses httpx.ASGITransport so the app and the
seeded DB share one event loop, with a file-backed SQLite so the endpoints'
own sessions see the seeded rows."""

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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_WS_SECRET = "ws-test-secret-32-bytes-padding!!"


def _ws_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        groq_api_key="x", api_key="x", database_url=None, session_secret=_WS_SECRET, bcrypt_rounds=4
    )


def _bearer(user_id: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(_WS_SECRET, user_id)}"}


@pytest.fixture()
async def ws(tmp_path: Any) -> AsyncGenerator[SimpleNamespace]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/ws.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    db_engine_module._session_factory = factory  # type: ignore[attr-defined]

    async with factory() as session, session.begin():
        owner = User(email="owner@acme.com", display_name="Owner", email_verified=True)
        member = User(email="member@acme.com", display_name="Member", email_verified=True)
        outsider = User(email="out@evil.com", display_name="Out", email_verified=True)
        session.add_all([owner, member, outsider])
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
        ids = SimpleNamespace(owner=owner.id, member=member.id, outsider=outsider.id, team=team.id)

    app.dependency_overrides[get_settings] = _ws_settings
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ids.client = client
        yield ids
    app.dependency_overrides.clear()
    db_engine_module._session_factory = None  # type: ignore[attr-defined]
    await engine.dispose()


async def test_unauthenticated_returns_401(ws: SimpleNamespace) -> None:
    resp = await ws.client.get(f"/workspaces/{ws.team}/members")
    assert resp.status_code == 401


async def test_non_member_forbidden_idor(ws: SimpleNamespace) -> None:
    # Outsider is authenticated but not a member of this workspace → 403, never 200.
    resp = await ws.client.get(f"/workspaces/{ws.team}/members", headers=_bearer(ws.outsider))
    assert resp.status_code == 403
    assert "member" in resp.json()["detail"].lower()


async def test_member_lacks_manage_scope(ws: SimpleNamespace) -> None:
    resp = await ws.client.post(
        f"/workspaces/{ws.team}/invitations",
        headers=_bearer(ws.member),
        json={"email": "new@acme.com", "role": "member"},
    )
    assert resp.status_code == 403
    assert "workspace:manage" in resp.json()["detail"]


async def test_owner_lists_members(ws: SimpleNamespace) -> None:
    resp = await ws.client.get(f"/workspaces/{ws.team}/members", headers=_bearer(ws.owner))
    assert resp.status_code == 200, resp.text
    roles = {m["email"]: m["role"] for m in resp.json()}
    assert roles == {"owner@acme.com": "owner", "member@acme.com": "member"}


async def test_owner_creates_invitation(ws: SimpleNamespace) -> None:
    resp = await ws.client.post(
        f"/workspaces/{ws.team}/invitations",
        headers=_bearer(ws.owner),
        json={"email": "invitee@acme.com", "role": "member"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "#token=" in body["link"]


async def test_owner_creates_and_lists_team(ws: SimpleNamespace) -> None:
    created = await ws.client.post(
        "/workspaces", headers=_bearer(ws.owner), json={"name": "Second Team"}
    )
    assert created.status_code == 200, created.text
    assert created.json()["role"] == "owner"

    listed = await ws.client.get("/workspaces", headers=_bearer(ws.owner))
    names = {w["name"] for w in listed.json()}
    assert {"Acme", "Second Team"} <= names
