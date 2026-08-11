"""Unit tests for Plan 37 (Gmail Ingestion F2 — sync + today's triaged inbox)."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Generator
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from email_triage.auth.session import create_access_token
from email_triage.config import Settings
from email_triage.db.models import Membership, Tenant, User
from email_triage.deps import get_settings
from email_triage.main import app
from email_triage.schemas import DynamicTriageResponse
from email_triage.services.crypto import TokenCipher
from email_triage.services.gmail import (
    TODAY_QUERY,
    GmailAuthError,
    GmailClient,
    GmailMessage,
    build_inbox_query,
)
from email_triage.services.llm import LLMError
from fastapi.testclient import TestClient

_SECRET = "test-session-secret-32-bytes-here"
_ENC_KEY = Fernet.generate_key().decode()


def _mock_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        groq_api_key="test",
        api_key="test-key",
        database_url=None,
        google_client_id="google-client-id",
        google_client_secret="google-client-secret",
        gmail_token_enc_key=_ENC_KEY,
        session_secret=_SECRET,
        gmail_sync_max_results=25,
    )


@pytest.fixture()
def inbox_client() -> Generator[TestClient]:
    app.dependency_overrides[get_settings] = _mock_settings
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.pop(get_settings, None)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_session_mock() -> AsyncMock:
    s = AsyncMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=False)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=False)
    s.begin = MagicMock(return_value=cm)
    return s


def _make_factory(session: AsyncMock) -> MagicMock:
    inst = MagicMock()
    inst.return_value = session
    factory = MagicMock()
    factory.return_value = inst
    return factory


def _bearer(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(_SECRET, user_id)}"}


def _push_auth(
    stack: ExitStack, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str = "owner"
) -> None:
    fake_user = User(id=user_id, email="u@acme.com", display_name="U", email_verified=True)
    fake_membership = Membership(user_id=user_id, tenant_id=tenant_id, role=role)
    fake_tenant = Tenant(id=tenant_id, name="Acme", type="personal", domain=None, plan="free")
    session = _make_session_mock()
    session.get.return_value = fake_user
    factory = _make_factory(session)
    stack.enter_context(
        patch("email_triage.deps.get_session_factory", return_value=factory.return_value)
    )
    user_repo = AsyncMock()
    user_repo.get_membership.return_value = fake_membership
    stack.enter_context(patch("email_triage.deps.UserRepo", return_value=user_repo))
    tenant_repo = AsyncMock()
    tenant_repo.get_by_id.return_value = fake_tenant
    stack.enter_context(patch("email_triage.deps.TenantRepo", return_value=tenant_repo))


def _raw_message(
    mid: str,
    subject: str,
    sender: str,
    body_text: str,
    date: str = "Wed, 06 Aug 2026 08:14:00 +0000",
) -> dict[str, object]:
    data = base64.urlsafe_b64encode(body_text.encode()).decode().rstrip("=")
    return {
        "id": mid,
        "snippet": "snippet fallback",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Date", "value": date},
            ],
            "body": {"data": data},
        },
    }


# ── parse_message ─────────────────────────────────────────────────────────────


def test_parse_message_extracts_plain_text() -> None:
    msg = GmailClient.parse_message(
        _raw_message("m1", "Where is my order?", "Maya <maya@shop.com>", "Order #4821 status?")
    )
    assert msg.message_id == "m1"
    assert msg.subject == "Where is my order?"
    assert msg.sender == "Maya <maya@shop.com>"
    assert msg.body == "Order #4821 status?"
    assert msg.received_at is not None


def test_parse_message_prefers_plain_over_html() -> None:
    html = base64.urlsafe_b64encode(b"<p>hi</p>").decode().rstrip("=")
    plain = base64.urlsafe_b64encode(b"plain body").decode().rstrip("=")
    raw: dict[str, object] = {
        "id": "m2",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "Subject", "value": "S"}, {"name": "From", "value": "a@b.com"}],
            "parts": [
                {"mimeType": "text/html", "body": {"data": html}},
                {"mimeType": "text/plain", "body": {"data": plain}},
            ],
        },
    }
    assert GmailClient.parse_message(raw).body == "plain body"


def test_parse_message_falls_back_to_snippet() -> None:
    raw: dict[str, object] = {
        "id": "m3",
        "snippet": "just the snippet",
        "payload": {"mimeType": "multipart/mixed", "headers": []},
    }
    msg = GmailClient.parse_message(raw)
    assert msg.body == "just the snippet"
    assert msg.subject == "(no subject)"


# ── GmailClient (mocked httpx) ────────────────────────────────────────────────


async def test_refresh_access_token_success() -> None:
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"access_token": "ya29.tok"}
    http = AsyncMock()
    http.post = AsyncMock(return_value=resp)
    token = await GmailClient("i", "s").refresh_access_token(http, "1//rt")
    assert token == "ya29.tok"


async def test_refresh_access_token_invalid_grant_raises_auth() -> None:
    resp = MagicMock(status_code=400)
    http = AsyncMock()
    http.post = AsyncMock(return_value=resp)
    with pytest.raises(GmailAuthError):
        await GmailClient("i", "s").refresh_access_token(http, "revoked")


async def test_list_today_lists_and_fetches() -> None:
    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {"messages": [{"id": "m1"}]}
    get_resp = MagicMock(status_code=200)
    get_resp.json.return_value = _raw_message("m1", "Hi", "a@b.com", "body text")
    http = AsyncMock()
    http.get = AsyncMock(side_effect=[list_resp, get_resp])
    msgs = await GmailClient("i", "s").list_today(http, "tok")
    assert len(msgs) == 1
    assert msgs[0].subject == "Hi"
    assert msgs[0].body == "body text"


# ── GET /gmail/status ─────────────────────────────────────────────────────────


def test_status_requires_auth(inbox_client: TestClient) -> None:
    assert inbox_client.get("/gmail/status").status_code == 401


def test_status_not_connected(inbox_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    with ExitStack() as stack:
        _push_auth(stack, user_id, tenant_id)
        session = _make_session_mock()
        factory = _make_factory(session)
        stack.enter_context(
            patch(
                "email_triage.routers.inbox.get_session_factory", return_value=factory.return_value
            )
        )
        repo = AsyncMock()
        repo.get_by_user.return_value = None
        stack.enter_context(patch("email_triage.routers.inbox.GmailRepo", return_value=repo))
        resp = inbox_client.get("/gmail/status", headers=_bearer(user_id))
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


def test_status_connected(inbox_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    conn = SimpleNamespace(google_email="me@gmail.com", last_synced_at=None, refresh_token_enc="x")
    with ExitStack() as stack:
        _push_auth(stack, user_id, tenant_id)
        session = _make_session_mock()
        factory = _make_factory(session)
        stack.enter_context(
            patch(
                "email_triage.routers.inbox.get_session_factory", return_value=factory.return_value
            )
        )
        repo = AsyncMock()
        repo.get_by_user.return_value = conn
        stack.enter_context(patch("email_triage.routers.inbox.GmailRepo", return_value=repo))
        resp = inbox_client.get("/gmail/status", headers=_bearer(user_id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["google_email"] == "me@gmail.com"


# ── POST /gmail/sync ──────────────────────────────────────────────────────────


def _sync_stack(
    stack: ExitStack,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    connection: object,
    gmail_instance: MagicMock,
    triage_side: object = None,
    triage_return: object = None,
) -> tuple[AsyncMock, AsyncMock]:
    _push_auth(stack, user_id, tenant_id)
    session = _make_session_mock()
    factory = _make_factory(session)
    stack.enter_context(
        patch("email_triage.routers.inbox.get_session_factory", return_value=factory.return_value)
    )
    repo = AsyncMock()
    repo.get_by_user.return_value = connection
    stack.enter_context(patch("email_triage.routers.inbox.GmailRepo", return_value=repo))
    stack.enter_context(
        patch("email_triage.routers.inbox.GmailClient", return_value=gmail_instance)
    )
    svc = AsyncMock()
    if triage_side is not None:
        svc.triage = AsyncMock(side_effect=triage_side)
    else:
        svc.triage = AsyncMock(return_value=triage_return)
    get_svc = AsyncMock(return_value=svc)
    stack.enter_context(patch("email_triage.routers.inbox.get_triage_service", get_svc))
    return repo, svc


def _connection() -> SimpleNamespace:
    return SimpleNamespace(
        google_email="me@gmail.com",
        last_synced_at=None,
        refresh_token_enc=TokenCipher(_ENC_KEY).encrypt("1//rt"),
    )


def _gmail_instance(messages: list[GmailMessage]) -> MagicMock:
    inst = MagicMock()
    inst.refresh_access_token = AsyncMock(return_value="ya29.tok")
    inst.list_today = AsyncMock(return_value=messages)
    return inst


def test_sync_404_when_not_connected(inbox_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    with ExitStack() as stack:
        _sync_stack(stack, user_id, tenant_id, connection=None, gmail_instance=_gmail_instance([]))
        resp = inbox_client.post("/gmail/sync", headers=_bearer(user_id))
    assert resp.status_code == 404


def test_sync_returns_triaged_items(inbox_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    messages = [
        GmailMessage("m1", "Maya <maya@shop.com>", "Where is my order?", "Order #4821?", None),
        GmailMessage("m2", "jordi@x.com", "Refund please", "Cancelled order refund", None),
    ]
    result = DynamicTriageResponse(category="refunds", draft_reply="On it.", confidence=0.9)
    with ExitStack() as stack:
        repo, svc = _sync_stack(
            stack,
            user_id,
            tenant_id,
            connection=_connection(),
            gmail_instance=_gmail_instance(messages),
            triage_return=result,
        )
        resp = inbox_client.post("/gmail/sync", headers=_bearer(user_id))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 2
    assert items[0]["category"] == "refunds"
    assert items[0]["sender"] == "Maya <maya@shop.com>"
    assert svc.triage.await_count == 2
    repo.touch_last_synced.assert_awaited_once()


def test_sync_empty_inbox_returns_empty_items(inbox_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    with ExitStack() as stack:
        _sync_stack(
            stack,
            user_id,
            tenant_id,
            connection=_connection(),
            gmail_instance=_gmail_instance([]),
            triage_return=DynamicTriageResponse(category="x", draft_reply="y", confidence=0.5),
        )
        resp = inbox_client.post("/gmail/sync", headers=_bearer(user_id))
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_sync_409_when_token_revoked(inbox_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    inst = MagicMock()
    inst.refresh_access_token = AsyncMock(side_effect=GmailAuthError("revoked"))
    inst.list_today = AsyncMock(return_value=[])
    with ExitStack() as stack:
        _sync_stack(
            stack,
            user_id,
            tenant_id,
            connection=_connection(),
            gmail_instance=inst,
            triage_return=DynamicTriageResponse(category="x", draft_reply="y", confidence=0.5),
        )
        resp = inbox_client.post("/gmail/sync", headers=_bearer(user_id))
    assert resp.status_code == 409


def test_sync_503_when_all_triage_fail(inbox_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    messages = [GmailMessage("m1", "a@b.com", "S", "body", None)]
    with ExitStack() as stack:
        _sync_stack(
            stack,
            user_id,
            tenant_id,
            connection=_connection(),
            gmail_instance=_gmail_instance(messages),
            triage_side=LLMError("groq down"),
        )
        resp = inbox_client.post("/gmail/sync", headers=_bearer(user_id))
    assert resp.status_code == 503


# ── Plan 40: read-state + look-back-window filters ──────────────────────────────


def test_build_inbox_query_combinations() -> None:
    assert build_inbox_query(True, 1) == "in:inbox is:unread newer_than:1d"
    assert build_inbox_query(False, 7) == "in:inbox newer_than:7d"
    assert build_inbox_query(True, 30) == "in:inbox is:unread newer_than:30d"
    assert build_inbox_query(False, 1) == "in:inbox newer_than:1d"


def test_today_query_alias_matches_default() -> None:
    # Back-compat: the module constant is exactly Plan 37's original (unread, 1 day).
    assert TODAY_QUERY == build_inbox_query(True, 1) == "in:inbox is:unread newer_than:1d"


def test_sync_without_body_uses_default_query(inbox_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    inst = _gmail_instance([])
    with ExitStack() as stack:
        _sync_stack(stack, user_id, tenant_id, connection=_connection(), gmail_instance=inst)
        resp = inbox_client.post("/gmail/sync", headers=_bearer(user_id))
    assert resp.status_code == 200
    # 3rd positional arg to list_today(http, access_token, query, max_results) is the query.
    assert inst.list_today.await_args.args[2] == "in:inbox is:unread newer_than:1d"


def test_sync_applies_filters(inbox_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    inst = _gmail_instance([])
    with ExitStack() as stack:
        _sync_stack(stack, user_id, tenant_id, connection=_connection(), gmail_instance=inst)
        resp = inbox_client.post(
            "/gmail/sync", headers=_bearer(user_id), json={"unread_only": False, "days": 7}
        )
    assert resp.status_code == 200
    assert inst.list_today.await_args.args[2] == "in:inbox newer_than:7d"


def test_sync_422_when_days_over_max(inbox_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    with ExitStack() as stack:
        _sync_stack(
            stack, user_id, tenant_id, connection=_connection(), gmail_instance=_gmail_instance([])
        )
        resp = inbox_client.post("/gmail/sync", headers=_bearer(user_id), json={"days": 99})
    assert resp.status_code == 422


def test_sync_422_when_days_below_min(inbox_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    with ExitStack() as stack:
        _sync_stack(
            stack, user_id, tenant_id, connection=_connection(), gmail_instance=_gmail_instance([])
        )
        resp = inbox_client.post("/gmail/sync", headers=_bearer(user_id), json={"days": 0})
    assert resp.status_code == 422


def test_sync_503_when_not_configured() -> None:
    def _no_key() -> Settings:
        return Settings(  # type: ignore[call-arg]
            groq_api_key="test",
            api_key="test-key",
            database_url=None,
            google_client_id="google-client-id",
            gmail_token_enc_key=None,
            session_secret=_SECRET,
        )

    app.dependency_overrides[get_settings] = _no_key
    try:
        user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c, ExitStack() as stack:
            _push_auth(stack, user_id, tenant_id)
            resp = c.post("/gmail/sync", headers=_bearer(user_id))
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.pop(get_settings, None)
