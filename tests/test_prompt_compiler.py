"""Tests for Triage Studio F2 — prompt compiler, dynamic output coercion, and the
per-(tenant, version) triage-service cache.

The compiler is a pure function (no DB). The service cache is exercised against a
file-backed SQLite so ``get_triage_service`` opens its own session and sees the
seeded categories, same harness as ``test_triage_config``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import pytest
from email_triage import deps
from email_triage.config import Settings
from email_triage.db import engine as db_engine_module
from email_triage.db.base import Base
from email_triage.db.models import Tenant
from email_triage.deps import TenantContext, get_settings, get_triage_service
from email_triage.schemas import DynamicTriageResponse, TriageRequest
from email_triage.services.llm import LLMService
from email_triage.services.prompt_compiler import (
    CategorySpec,
    compile_system_prompt,
    render_email,
)
from email_triage.services.triage_config import TriageConfigService
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Compiler (pure) ───────────────────────────────────────────────────────────

_SPECS = [
    CategorySpec("status", "Order status", "Where is my order"),
    CategorySpec("refunds", "Refunds", "Money back"),
]


def test_prompt_covers_every_category_plus_unknown() -> None:
    prompt = compile_system_prompt(_SPECS)
    # Each category is a "- slug: description" list item; coverage is structural.
    for spec in _SPECS:
        assert f"- {spec.slug}: {spec.description}" in prompt
    assert "- unknown:" in prompt  # implicit escape category always present


def test_prompt_is_mostly_prose_not_over_tagged() -> None:
    prompt = compile_system_prompt(_SPECS)
    # Plain-prose sections, no ceremony tags.
    assert "Categories:" in prompt and "Guidelines:" in prompt
    for tag in ("<role>", "<task>", "<categories>", "<output_format>", "<guardrails>", "<style>"):
        assert tag not in prompt


def test_prompt_is_injection_hardened() -> None:
    prompt = compile_system_prompt(_SPECS)
    assert "not instructions to follow" in prompt


def test_compiler_neutralizes_structural_characters() -> None:
    # A description can't forge a delimiter like </examples> or break the <email> tag.
    prompt = compile_system_prompt(
        [CategorySpec("promo", "Deals", "Anything <b>discount</b> & sale related")]
    )
    assert "&lt;b&gt;discount&lt;/b&gt;" in prompt
    assert "&amp;" in prompt
    assert "<b>discount</b>" not in prompt  # raw markup never leaks into the prompt


def test_render_email_wraps_volatile_block() -> None:
    email = render_email("Hi", "a@b.com", "body text")
    assert email.startswith("<email>") and email.endswith("</email>")
    assert "Subject: Hi" in email
    assert "From: a@b.com" in email


# ── Dynamic output coercion (LLMService) ──────────────────────────────────────


def _svc(allowed: frozenset[str]) -> LLMService:
    return LLMService(
        api_key="fake-key",
        system_prompt="p",
        output_type=DynamicTriageResponse,
        allowed_slugs=allowed,
    )


_REQ = TriageRequest(subject="s", sender="a@b.com", body="b")


async def test_hallucinated_slug_coerced_to_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(frozenset({"refunds", "unknown"}))

    async def fake_run(_msg: str) -> Any:
        return SimpleNamespace(
            output=DynamicTriageResponse(category="not_a_slug", draft_reply="hi", confidence=0.4)
        )

    monkeypatch.setattr(svc._agent, "run", fake_run)  # type: ignore[attr-defined]
    out = await svc.triage(_REQ)
    assert out.category == "unknown"


async def test_valid_slug_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _svc(frozenset({"refunds", "unknown"}))

    async def fake_run(_msg: str) -> Any:
        return SimpleNamespace(
            output=DynamicTriageResponse(category="refunds", draft_reply="hi", confidence=0.9)
        )

    monkeypatch.setattr(svc._agent, "run", fake_run)  # type: ignore[attr-defined]
    out = await svc.triage(_REQ)
    assert out.category == "refunds"


# ── get_triage_service: dynamic build + cache + fallback ──────────────────────


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        groq_api_key="x", api_key="x", database_url="sqlite://", bcrypt_rounds=4
    )


@pytest.fixture()
async def svc_db(tmp_path: Any) -> AsyncGenerator[SimpleNamespace]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/svc.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    db_engine_module._session_factory = factory  # type: ignore[attr-defined]

    async with factory() as session, session.begin():
        team = Tenant(name="Acme", type="team", domain=None)
        session.add(team)
        await session.flush()
        await TriageConfigService().seed_defaults(session, team.id)
        tid = team.id

    # get_triage_service reads real settings; pin them so no .env bleed-through.
    get_settings.cache_clear()
    _orig = deps.get_settings
    deps.get_settings = _settings  # type: ignore[assignment]
    deps.clear_triage_service_cache()
    yield SimpleNamespace(tenant_id=tid, factory=factory)
    deps.get_settings = _orig  # type: ignore[assignment]
    get_settings.cache_clear()
    db_engine_module._session_factory = None  # type: ignore[attr-defined]
    await engine.dispose()


async def test_builds_dynamic_service_from_tenant_taxonomy(svc_db: SimpleNamespace) -> None:
    svc = await get_triage_service(TenantContext(tenant_id=svc_db.tenant_id))
    assert svc.allowed_slugs is not None
    assert {"status", "refunds", "unknown"} <= svc.allowed_slugs


async def test_service_cached_by_version(svc_db: SimpleNamespace) -> None:
    a = await get_triage_service(TenantContext(tenant_id=svc_db.tenant_id))
    b = await get_triage_service(TenantContext(tenant_id=svc_db.tenant_id))
    assert a is b  # same taxonomy version → same cached instance


async def test_editing_taxonomy_invalidates_cache(svc_db: SimpleNamespace) -> None:
    a = await get_triage_service(TenantContext(tenant_id=svc_db.tenant_id))
    async with svc_db.factory() as session, session.begin():
        await TriageConfigService().create_category(
            session, svc_db.tenant_id, "returns", "Returns", "desc"
        )
    b = await get_triage_service(TenantContext(tenant_id=svc_db.tenant_id))
    assert a is not b  # new version → rebuilt
    assert b.allowed_slugs is not None and "returns" in b.allowed_slugs


async def test_no_tenant_falls_back_to_legacy(
    svc_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = object()
    monkeypatch.setattr(deps, "get_llm_service", lambda: sentinel)
    result = await get_triage_service(TenantContext(tenant_id=None))
    assert result is sentinel


async def test_genuine_load_failure_fails_loud_not_legacy(
    svc_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real failure on the config-load path (DB unreachable, unreadable row) must NOT be
    # masked as a successful legacy triage: it raises a 503 instead of serving the wrong
    # taxonomy. If it silently fell back, this would return the legacy sentinel.
    sentinel = object()
    monkeypatch.setattr(deps, "get_llm_service", lambda: sentinel)

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("connection reset by peer")

    monkeypatch.setattr(deps.PromptVersionRepo, "active", boom)

    with pytest.raises(HTTPException) as exc_info:
        await get_triage_service(TenantContext(tenant_id=svc_db.tenant_id))
    assert exc_info.value.status_code == 503


async def test_no_active_categories_still_falls_back_to_legacy(
    svc_db: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Intended default: a tenant that hasn't configured any taxonomy (no categories) gets
    # the legacy prompt — the correct answer, NOT a 503.
    sentinel = object()
    monkeypatch.setattr(deps, "get_llm_service", lambda: sentinel)
    async with svc_db.factory() as session, session.begin():
        bare = Tenant(name="Bare", type="team", domain=None)
        session.add(bare)
        await session.flush()
        bare_id = bare.id

    result = await get_triage_service(TenantContext(tenant_id=bare_id))
    assert result is sentinel


async def test_published_version_wins_over_live_compile(svc_db: SimpleNamespace) -> None:
    from email_triage.db.repos.categories import CategoryRepo
    from email_triage.services.prompt_studio import PromptStudioService
    from email_triage.services.triage_config import TriageConfigService

    # Publish v1 (freezes the current slug set, incl. "prices").
    async with svc_db.factory() as session, session.begin():
        await PromptStudioService().publish(session, svc_db.tenant_id, None)

    # Now deactivate "prices" — this WOULD change a live-compile.
    async with svc_db.factory() as session, session.begin():
        prices = await CategoryRepo().get_by_slug(session, svc_db.tenant_id, "prices")
        assert prices is not None
        await TriageConfigService().update_category(
            session, svc_db.tenant_id, prices.id, is_active=False
        )
    deps.clear_triage_service_cache()

    # The served service still exposes "prices": the frozen published version wins.
    svc = await get_triage_service(TenantContext(tenant_id=svc_db.tenant_id))
    assert svc.allowed_slugs is not None and "prices" in svc.allowed_slugs
