"""Voice report workflow (Plan 41): structured script, harness-computed counts, empty degrade.

No network: both workflow agents run on pydantic-ai's ``TestModel``. The endpoint test overrides
auth + the runner, so it never touches Groq or the DB."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
from email_triage.deps import SessionContext, get_current_user
from email_triage.main import app
from email_triage.routers.reports import get_voice_report_runner
from email_triage.schemas import InboxItem
from email_triage.services.voice_report import (
    VoiceReportRunner,
    build_script_agent,
    build_summary_agent,
    run_voice_report,
)
from pydantic_ai.models.test import TestModel


def _item(subject: str, category: str) -> InboxItem:
    return InboxItem(
        message_id=f"m-{subject}",
        sender="customer@example.com",
        subject=subject,
        category=category,
        confidence=0.9,
        draft_reply="Thanks, we're on it.",
    )


def _runner() -> VoiceReportRunner:
    return VoiceReportRunner(build_summary_agent(TestModel()), build_script_agent(TestModel()))


# ── Service workflow ────────────────────────────────────────────────────────────


async def test_generates_structured_report() -> None:
    items = [_item("Where is my order?", "status"), _item("Refund please", "refunds")]
    report = await _runner().run(items)

    assert report.total == 2
    assert report.script.opening  # non-empty
    assert isinstance(report.script.closing, str)


async def test_by_category_counts_are_harness_computed() -> None:
    items = [_item("a", "refunds"), _item("b", "refunds"), _item("c", "status")]
    report = await run_voice_report(
        summary_agent=build_summary_agent(TestModel()),
        script_agent=build_script_agent(TestModel()),
        items=items,
    )
    counts = {c.category: c.count for c in report.by_category}
    assert counts == {"refunds": 2, "status": 1}
    assert report.total == 3


async def test_empty_inbox_degrades_without_llm() -> None:
    report = await _runner().run([])
    assert report.total == 0
    assert report.by_category == []
    # The exact opening only the no-LLM degrade path produces (TestModel would differ).
    assert report.script.opening == "No relevant emails today."


# ── Endpoint ──────────────────────────────────────────────────────────────────


def _fake_ctx() -> SessionContext:
    return SessionContext(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role="member",
        email="m@acme.com",
        display_name="M",
        email_verified=True,
        tenant_name="Acme",
        tenant_type="team",
        plan="free",
    )


@pytest.fixture()
async def client() -> AsyncGenerator[httpx.AsyncClient]:
    app.dependency_overrides[get_current_user] = _fake_ctx
    app.dependency_overrides[get_voice_report_runner] = _runner
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_endpoint_returns_voice_report(client: httpx.AsyncClient) -> None:
    body: dict[str, Any] = {
        "items": [
            {
                "message_id": "m1",
                "sender": "a@b.com",
                "subject": "Where is my order?",
                "category": "status",
                "confidence": 0.9,
                "draft_reply": "On it.",
            }
        ]
    }
    resp = await client.post("/reports/voice", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 1
    assert data["audio_url"] is None
    assert "opening" in data["script"]
