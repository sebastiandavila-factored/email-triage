"""Tests for Triage Studio F1 — per-workspace categories.

Two layers:
- Service (``TriageConfigService``) against a real SQLite session: rules +
  seeding, no mocks.
- HTTP (``/workspaces/{tid}/categories``) via httpx ASGITransport: scope
  enforcement and object-level authorization (IDOR), same harness as
  ``test_workspaces_api``.
"""

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
from email_triage.db.repos.tenants import TenantRepo
from email_triage.deps import get_settings
from email_triage.main import app
from email_triage.services.triage_config import (
    DEFAULT_CATEGORIES,
    TriageConfigError,
    TriageConfigService,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Service tests ─────────────────────────────────────────────────────────────


async def _mk_tenant(session: AsyncSession) -> Tenant:
    return await TenantRepo().create_team(session, "Acme")


async def test_seed_defaults_creates_legacy_five(db_session: AsyncSession) -> None:
    tenant = await _mk_tenant(db_session)
    await TriageConfigService().seed_defaults(db_session, tenant.id)
    rows = await CategoryRepo().list_for_tenant(db_session, tenant.id)
    assert [c.slug for c in rows] == [slug for slug, _, _ in DEFAULT_CATEGORIES]
    assert [c.sort_order for c in rows] == list(range(len(DEFAULT_CATEGORIES)))


async def test_seed_defaults_is_idempotent(db_session: AsyncSession) -> None:
    tenant = await _mk_tenant(db_session)
    svc = TriageConfigService()
    await svc.seed_defaults(db_session, tenant.id)
    await svc.seed_defaults(db_session, tenant.id)
    rows = await CategoryRepo().list_for_tenant(db_session, tenant.id)
    assert len(rows) == len(DEFAULT_CATEGORIES)


async def test_create_category_assigns_next_sort_order(db_session: AsyncSession) -> None:
    tenant = await _mk_tenant(db_session)
    svc = TriageConfigService()
    await svc.seed_defaults(db_session, tenant.id)
    created = await svc.create_category(
        db_session, tenant.id, "returns", "Returns", "Return-related questions"
    )
    assert created.sort_order == len(DEFAULT_CATEGORIES)  # appended after the seed


async def test_create_reserved_slug_rejected(db_session: AsyncSession) -> None:
    tenant = await _mk_tenant(db_session)
    with pytest.raises(TriageConfigError) as exc:
        await TriageConfigService().create_category(
            db_session, tenant.id, "unknown", "Unknown", "x"
        )
    assert exc.value.status_code == 422


@pytest.mark.parametrize("bad", ["Has Space", "with-dash", "emoji😀", "x" * 51])
async def test_create_invalid_slug_rejected(db_session: AsyncSession, bad: str) -> None:
    tenant = await _mk_tenant(db_session)
    with pytest.raises(TriageConfigError) as exc:
        await TriageConfigService().create_category(db_session, tenant.id, bad, "Name", "desc")
    assert exc.value.status_code == 422


async def test_slug_is_normalised_to_lowercase(db_session: AsyncSession) -> None:
    tenant = await _mk_tenant(db_session)
    created = await TriageConfigService().create_category(
        db_session, tenant.id, "  Returns  ", "Returns", "desc"
    )
    assert created.slug == "returns"  # trimmed + lowercased, not rejected


async def test_create_duplicate_slug_rejected(db_session: AsyncSession) -> None:
    tenant = await _mk_tenant(db_session)
    svc = TriageConfigService()
    await svc.create_category(db_session, tenant.id, "returns", "Returns", "desc")
    with pytest.raises(TriageConfigError) as exc:
        await svc.create_category(db_session, tenant.id, "returns", "Returns 2", "desc")
    assert exc.value.status_code == 409


async def test_update_edits_display_copy(db_session: AsyncSession) -> None:
    tenant = await _mk_tenant(db_session)
    svc = TriageConfigService()
    cat = await svc.create_category(db_session, tenant.id, "returns", "Returns", "old")
    updated = await svc.update_category(
        db_session, tenant.id, cat.id, name="Returns & Exchanges", description="new"
    )
    assert updated.name == "Returns & Exchanges"
    assert updated.description == "new"
    assert updated.slug == "returns"  # slug immutable


async def test_cannot_deactivate_last_active(db_session: AsyncSession) -> None:
    tenant = await _mk_tenant(db_session)
    svc = TriageConfigService()
    only = await svc.create_category(db_session, tenant.id, "returns", "Returns", "desc")
    with pytest.raises(TriageConfigError) as exc:
        await svc.update_category(db_session, tenant.id, only.id, is_active=False)
    assert exc.value.status_code == 409


async def test_can_deactivate_when_another_stays_active(db_session: AsyncSession) -> None:
    tenant = await _mk_tenant(db_session)
    svc = TriageConfigService()
    a = await svc.create_category(db_session, tenant.id, "a", "A", "desc")
    await svc.create_category(db_session, tenant.id, "b", "B", "desc")
    updated = await svc.update_category(db_session, tenant.id, a.id, is_active=False)
    assert updated.is_active is False


async def test_cannot_delete_last_active(db_session: AsyncSession) -> None:
    tenant = await _mk_tenant(db_session)
    svc = TriageConfigService()
    only = await svc.create_category(db_session, tenant.id, "returns", "Returns", "desc")
    with pytest.raises(TriageConfigError) as exc:
        await svc.delete_category(db_session, tenant.id, only.id)
    assert exc.value.status_code == 409


async def test_delete_one_of_two(db_session: AsyncSession) -> None:
    tenant = await _mk_tenant(db_session)
    svc = TriageConfigService()
    a = await svc.create_category(db_session, tenant.id, "a", "A", "desc")
    await svc.create_category(db_session, tenant.id, "b", "B", "desc")
    await svc.delete_category(db_session, tenant.id, a.id)
    rows = await CategoryRepo().list_for_tenant(db_session, tenant.id)
    assert [c.slug for c in rows] == ["b"]


async def test_category_of_other_tenant_is_not_found(db_session: AsyncSession) -> None:
    t1 = await TenantRepo().create_team(db_session, "T1")
    t2 = await TenantRepo().create_team(db_session, "T2")
    svc = TriageConfigService()
    cat = await svc.create_category(db_session, t1.id, "a", "A", "desc")
    # Looked up under the wrong tenant → 404, never leaks the row.
    with pytest.raises(TriageConfigError) as exc:
        await svc.update_category(db_session, t2.id, cat.id, name="hijack")
    assert exc.value.status_code == 404


# ── HTTP / RBAC tests ─────────────────────────────────────────────────────────

_SECRET = "cfg-test-secret-32-bytes-padding!"


def _cfg_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        groq_api_key="x", api_key="x", database_url=None, session_secret=_SECRET, bcrypt_rounds=4
    )


def _bearer(user_id: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(_SECRET, user_id)}"}


@pytest.fixture()
async def cfg(tmp_path: Any) -> AsyncGenerator[SimpleNamespace]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/cfg.db")
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
        other = Tenant(name="Other", type="team", domain=None)
        session.add_all([team, other])
        await session.flush()
        session.add_all(
            [
                Membership(user_id=owner.id, tenant_id=team.id, role="owner"),
                Membership(user_id=admin.id, tenant_id=team.id, role="admin"),
                Membership(user_id=member.id, tenant_id=team.id, role="member"),
            ]
        )
        await TriageConfigService().seed_defaults(session, team.id)
        await TriageConfigService().seed_defaults(session, other.id)
        # A category living in the *other* workspace, for the IDOR test.
        foreign = await TriageConfigService().create_category(
            session, other.id, "foreign", "Foreign", "desc"
        )
        ids = SimpleNamespace(
            owner=owner.id,
            admin=admin.id,
            member=member.id,
            outsider=outsider.id,
            team=team.id,
            other=other.id,
            foreign=foreign.id,
        )

    app.dependency_overrides[get_settings] = _cfg_settings
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ids.client = client
        yield ids
    app.dependency_overrides.clear()
    db_engine_module._session_factory = None  # type: ignore[attr-defined]
    await engine.dispose()


async def test_member_can_list(cfg: SimpleNamespace) -> None:
    resp = await cfg.client.get(f"/workspaces/{cfg.team}/categories", headers=_bearer(cfg.member))
    assert resp.status_code == 200
    assert len(resp.json()) == len(DEFAULT_CATEGORIES)


async def test_active_filter(cfg: SimpleNamespace) -> None:
    resp = await cfg.client.get(
        f"/workspaces/{cfg.team}/categories?active=true", headers=_bearer(cfg.member)
    )
    assert resp.status_code == 200
    assert all(c["is_active"] for c in resp.json())


async def test_member_cannot_create(cfg: SimpleNamespace) -> None:
    resp = await cfg.client.post(
        f"/workspaces/{cfg.team}/categories",
        headers=_bearer(cfg.member),
        json={"slug": "returns", "name": "Returns", "description": "desc"},
    )
    assert resp.status_code == 403
    assert "triage:configure" in resp.json()["detail"]


@pytest.mark.parametrize("actor", ["owner", "admin"])
async def test_configurers_can_create(cfg: SimpleNamespace, actor: str) -> None:
    resp = await cfg.client.post(
        f"/workspaces/{cfg.team}/categories",
        headers=_bearer(getattr(cfg, actor)),
        json={"slug": f"returns_{actor}", "name": "Returns", "description": "desc"},
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == f"returns_{actor}"


async def test_create_duplicate_returns_409(cfg: SimpleNamespace) -> None:
    resp = await cfg.client.post(
        f"/workspaces/{cfg.team}/categories",
        headers=_bearer(cfg.owner),
        json={"slug": "status", "name": "Dup", "description": "desc"},  # status seeded already
    )
    assert resp.status_code == 409


async def test_create_reserved_returns_422(cfg: SimpleNamespace) -> None:
    resp = await cfg.client.post(
        f"/workspaces/{cfg.team}/categories",
        headers=_bearer(cfg.owner),
        json={"slug": "unknown", "name": "Unknown", "description": "desc"},
    )
    assert resp.status_code == 422


async def test_outsider_forbidden_idor(cfg: SimpleNamespace) -> None:
    resp = await cfg.client.get(f"/workspaces/{cfg.team}/categories", headers=_bearer(cfg.outsider))
    assert resp.status_code == 403


async def test_cross_tenant_category_not_found(cfg: SimpleNamespace) -> None:
    # owner of `team` tries to edit a category that lives in `other` → 404.
    resp = await cfg.client.patch(
        f"/workspaces/{cfg.team}/categories/{cfg.foreign}",
        headers=_bearer(cfg.owner),
        json={"name": "hijacked"},
    )
    assert resp.status_code == 404


async def test_delete_then_last_active_guard(cfg: SimpleNamespace) -> None:
    # Deactivate all but one, then deleting the last active must 409.
    listing = await cfg.client.get(f"/workspaces/{cfg.team}/categories", headers=_bearer(cfg.owner))
    cats = listing.json()
    for c in cats[1:]:
        r = await cfg.client.patch(
            f"/workspaces/{cfg.team}/categories/{c['id']}",
            headers=_bearer(cfg.owner),
            json={"is_active": False},
        )
        assert r.status_code == 200
    resp = await cfg.client.delete(
        f"/workspaces/{cfg.team}/categories/{cats[0]['id']}", headers=_bearer(cfg.owner)
    )
    assert resp.status_code == 409
