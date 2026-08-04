"""Tests for Triage Studio F3 — few-shot examples, template overrides, and the
draft→preview→publish/eval-gate/rollback workflow.

Three layers: pure compiler (few-shot), service rules against a SQLite session
(no LLM — the eval-gate is injected), and HTTP scope enforcement via httpx.
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
from email_triage.services.prompt_compiler import (
    CategorySpec,
    ExampleSpec,
    TemplateOverrides,
    compile_system_prompt,
)
from email_triage.services.prompt_studio import (
    GateMetrics,
    PromptStudioError,
    PromptStudioService,
)
from email_triage.services.triage_config import TriageConfigService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Compiler: few-shot + overrides ────────────────────────────────────────────

_CATS = [CategorySpec("refunds", "Refunds", "Money back")]


def test_examples_injected_into_examples_block() -> None:
    ex = [ExampleSpec("refunds", "positive", "Where is my money", "I want a refund", "Sure!")]
    prompt = compile_system_prompt(_CATS, examples=ex)
    assert "<examples>" in prompt and "<example>" in prompt
    assert "category: refunds" in prompt
    assert "reply: Sure!" in prompt
    # The example's email is delimited like the real input; no ceremony sub-tags.
    assert "Subject: Where is my money" in prompt
    assert "<classification>" not in prompt


def test_no_examples_means_no_examples_block() -> None:
    assert compile_system_prompt(_CATS) == compile_system_prompt(_CATS, examples=[])
    assert "<examples>" not in compile_system_prompt(_CATS)


def test_overrides_replace_default_blocks() -> None:
    ov = TemplateOverrides(role="CUSTOM ROLE", tone="Be extremely formal.")
    prompt = compile_system_prompt(_CATS, overrides=ov)
    assert "CUSTOM ROLE" in prompt
    assert "- Tone: Be extremely formal." in prompt
    assert "<style>" not in prompt


# ── Service rules (SQLite session, no LLM) ────────────────────────────────────


async def _tenant_with_categories(session: AsyncSession) -> Any:
    tenant = await TenantRepo().create_team(session, "Acme")
    await TriageConfigService().seed_defaults(session, tenant.id)
    return tenant


async def _first_category(session: AsyncSession, tenant_id: Any) -> Any:
    rows = await CategoryRepo().list_for_tenant(session, tenant_id)
    return rows[0]


async def test_add_example_happy(db_session: AsyncSession) -> None:
    tenant = await _tenant_with_categories(db_session)
    cat = await _first_category(db_session, tenant.id)
    ex = await PromptStudioService().add_example(
        db_session, tenant.id, cat.id, "positive", "subj", "body", None, None
    )
    assert ex.kind == "positive" and ex.category_id == cat.id


async def test_add_example_invalid_kind(db_session: AsyncSession) -> None:
    tenant = await _tenant_with_categories(db_session)
    cat = await _first_category(db_session, tenant.id)
    with pytest.raises(PromptStudioError) as exc:
        await PromptStudioService().add_example(
            db_session, tenant.id, cat.id, "neutral", "s", "b", None, None
        )
    assert exc.value.status_code == 422


async def test_add_example_unknown_category(db_session: AsyncSession) -> None:
    import uuid

    tenant = await _tenant_with_categories(db_session)
    with pytest.raises(PromptStudioError) as exc:
        await PromptStudioService().add_example(
            db_session, tenant.id, uuid.uuid4(), "positive", "s", "b", None, None
        )
    assert exc.value.status_code == 404


async def test_compile_draft_includes_examples_and_overrides(db_session: AsyncSession) -> None:
    tenant = await _tenant_with_categories(db_session)
    cat = await _first_category(db_session, tenant.id)
    svc = PromptStudioService()
    await svc.add_example(db_session, tenant.id, cat.id, "positive", "subj", "body", "reply", None)
    await svc.save_draft(db_session, tenant.id, TemplateOverrides(tone="Be warm."), None)
    draft = await svc.compile_draft(db_session, tenant.id)
    assert "<examples>" in draft.prompt
    assert "- Tone: Be warm." in draft.prompt
    assert "unknown" in draft.allowed_slugs


async def test_publish_creates_active_version_and_increments(db_session: AsyncSession) -> None:
    tenant = await _tenant_with_categories(db_session)
    svc = PromptStudioService()
    v1 = await svc.publish(db_session, tenant.id, None)
    v2 = await svc.publish(db_session, tenant.id, None)
    assert v1.version == 1 and v2.version == 2
    active = await svc.versions.active(db_session, tenant.id)
    assert active is not None and active.version == 2  # only the latest is active


async def test_publish_requires_active_category(db_session: AsyncSession) -> None:
    tenant = await TenantRepo().create_team(db_session, "Empty")  # no seed → no categories
    with pytest.raises(PromptStudioError) as exc:
        await PromptStudioService().publish(db_session, tenant.id, None)
    assert exc.value.status_code == 409


async def test_eval_gate_blocks_regression(db_session: AsyncSession) -> None:
    tenant = await _tenant_with_categories(db_session)

    async def good_gate(_p: str, _s: frozenset[str]) -> GateMetrics:
        return GateMetrics(accuracy=0.90, macro_f1=0.88)

    async def bad_gate(_p: str, _s: frozenset[str]) -> GateMetrics:
        return GateMetrics(accuracy=0.50, macro_f1=0.48)

    await PromptStudioService(gate=good_gate).publish(db_session, tenant.id, None)  # baseline
    with pytest.raises(PromptStudioError) as exc:
        await PromptStudioService(gate=bad_gate).publish(db_session, tenant.id, None)
    assert exc.value.status_code == 409
    assert "Eval-gate failed" in exc.value.detail


async def test_eval_gate_allows_non_regression(db_session: AsyncSession) -> None:
    tenant = await _tenant_with_categories(db_session)

    async def gate(_p: str, _s: frozenset[str]) -> GateMetrics:
        return GateMetrics(accuracy=0.90, macro_f1=0.88)

    await PromptStudioService(gate=gate).publish(db_session, tenant.id, None)
    v2 = await PromptStudioService(gate=gate).publish(db_session, tenant.id, None)
    assert v2.version == 2  # equal metrics pass


async def test_rollback_reactivates_previous(db_session: AsyncSession) -> None:
    tenant = await _tenant_with_categories(db_session)
    svc = PromptStudioService()
    await svc.publish(db_session, tenant.id, None)  # v1
    await svc.publish(db_session, tenant.id, None)  # v2 active
    rolled = await svc.rollback(db_session, tenant.id, 1)
    assert rolled.version == 1
    active = await svc.versions.active(db_session, tenant.id)
    assert active is not None and active.version == 1


# ── HTTP / RBAC ───────────────────────────────────────────────────────────────

_SECRET = "studio-test-secret-32-bytes-pad!!"


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        groq_api_key="x", api_key="x", database_url=None, session_secret=_SECRET, bcrypt_rounds=4
    )


def _bearer(user_id: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(_SECRET, user_id)}"}


@pytest.fixture()
async def studio(tmp_path: Any) -> AsyncGenerator[SimpleNamespace]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/studio.db")
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
        await TriageConfigService().seed_defaults(session, team.id)
        cat = (await CategoryRepo().list_for_tenant(session, team.id))[0]
        ids = SimpleNamespace(
            owner=owner.id, admin=admin.id, member=member.id, team=team.id, cat=cat.id
        )

    app.dependency_overrides[get_settings] = _settings
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ids.client = client
        yield ids
    app.dependency_overrides.clear()
    db_engine_module._session_factory = None  # type: ignore[attr-defined]
    await engine.dispose()


async def test_member_cannot_add_example(studio: SimpleNamespace) -> None:
    resp = await studio.client.post(
        f"/workspaces/{studio.team}/categories/{studio.cat}/examples",
        headers=_bearer(studio.member),
        json={"kind": "positive", "subject": "s", "body": "b"},
    )
    assert resp.status_code == 403


async def test_admin_can_add_example(studio: SimpleNamespace) -> None:
    resp = await studio.client.post(
        f"/workspaces/{studio.team}/categories/{studio.cat}/examples",
        headers=_bearer(studio.admin),
        json={"kind": "positive", "subject": "s", "body": "b"},
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "positive"


async def test_preview_returns_prompt(studio: SimpleNamespace) -> None:
    resp = await studio.client.post(
        f"/workspaces/{studio.team}/prompt/preview", headers=_bearer(studio.admin)
    )
    assert resp.status_code == 200
    assert "Categories:" in resp.json()["prompt"]


async def test_publish_requires_owner_scope(studio: SimpleNamespace) -> None:
    # admin has triage:configure but NOT prompt:publish
    resp = await studio.client.post(
        f"/workspaces/{studio.team}/prompt/publish", headers=_bearer(studio.admin)
    )
    assert resp.status_code == 403
    assert "prompt:publish" in resp.json()["detail"]


async def test_owner_can_publish_and_list_versions(studio: SimpleNamespace) -> None:
    pub = await studio.client.post(
        f"/workspaces/{studio.team}/prompt/publish", headers=_bearer(studio.owner)
    )
    assert pub.status_code == 201
    assert pub.json()["version"] == 1 and pub.json()["is_active"] is True

    versions = await studio.client.get(
        f"/workspaces/{studio.team}/prompt/versions", headers=_bearer(studio.member)
    )
    assert versions.status_code == 200
    assert len(versions.json()) == 1


async def test_rollback_via_activate_endpoint(studio: SimpleNamespace) -> None:
    await studio.client.post(
        f"/workspaces/{studio.team}/prompt/publish", headers=_bearer(studio.owner)
    )
    await studio.client.post(
        f"/workspaces/{studio.team}/prompt/publish", headers=_bearer(studio.owner)
    )
    resp = await studio.client.post(
        f"/workspaces/{studio.team}/prompt/versions/1/activate", headers=_bearer(studio.owner)
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 1 and resp.json()["is_active"] is True
