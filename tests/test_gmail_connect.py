"""Unit tests for Plan 36 (Gmail Ingestion F1 — connect OAuth + encrypted token).

Identity is stateless: it travels in the encrypted OAuth ``state`` (no cookie).
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

# Starlette's TestClient returns httpx2.Response (it does `import httpx2 as httpx`
# internally since 1.3.x); the app's own routers still use httpx (v1).
import httpx2
import pytest
from cryptography.fernet import Fernet
from email_triage.auth.session import create_access_token
from email_triage.config import Settings
from email_triage.db.models import Membership, Tenant, User
from email_triage.deps import get_settings
from email_triage.main import app
from email_triage.routers.gmail import decode_connect_state, encode_connect_state
from email_triage.services.crypto import TokenCipher, TokenCipherError
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
        gmail_redirect_uri="http://localhost:8000/gmail/callback",
        gmail_token_enc_key=_ENC_KEY,
        session_secret=_SECRET,
        frontend_url="http://localhost:5173",
        bcrypt_rounds=4,
    )


@pytest.fixture()
def gmail_client() -> Generator[TestClient]:
    app.dependency_overrides[get_settings] = _mock_settings
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.pop(get_settings, None)


# ── Shared mock helpers (mirroring test_auth.py) ──────────────────────────────


def _make_session_mock() -> AsyncMock:
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=None)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_cm)
    return mock_session


def _make_factory(mock_session: AsyncMock) -> MagicMock:
    inst = MagicMock()
    inst.return_value = mock_session
    factory = MagicMock()
    factory.return_value = inst
    return factory


def _bearer(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(_SECRET, user_id)}"}


def _push_auth(stack: ExitStack, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> AsyncMock:
    """Patch the deps layer so get_current_user resolves a user with ``role``."""
    fake_user = User(id=user_id, email="owner@acme.com", display_name="Owner", email_verified=True)
    fake_membership = Membership(user_id=user_id, tenant_id=tenant_id, role=role)
    fake_tenant = Tenant(
        id=tenant_id, name="Acme workspace", type="personal", domain=None, plan="free"
    )
    mock_session = _make_session_mock()
    mock_session.get.return_value = fake_user
    factory = _make_factory(mock_session)

    stack.enter_context(
        patch("email_triage.deps.get_session_factory", return_value=factory.return_value)
    )
    user_repo = AsyncMock()
    user_repo.get_membership.return_value = fake_membership
    stack.enter_context(patch("email_triage.deps.UserRepo", return_value=user_repo))
    tenant_repo = AsyncMock()
    tenant_repo.get_by_id.return_value = fake_tenant
    stack.enter_context(patch("email_triage.deps.TenantRepo", return_value=tenant_repo))
    return mock_session


# ── TokenCipher ───────────────────────────────────────────────────────────────


def test_token_cipher_round_trip() -> None:
    cipher = TokenCipher(_ENC_KEY)
    secret = "1//refresh-token-xyz"
    enc = cipher.encrypt(secret)
    assert enc != secret  # actually encrypted, not stored in the clear
    assert cipher.decrypt(enc) == secret


def test_token_cipher_wrong_key_raises() -> None:
    enc = TokenCipher(_ENC_KEY).encrypt("secret")
    other = TokenCipher(Fernet.generate_key().decode())
    with pytest.raises(TokenCipherError):
        other.decrypt(enc)


# ── Encrypted OAuth state ─────────────────────────────────────────────────────


def test_state_round_trip() -> None:
    cipher = TokenCipher(_ENC_KEY)
    uid, tid = uuid.uuid4(), uuid.uuid4()
    state = encode_connect_state(cipher, "verifier-123", uid, tid)
    result = decode_connect_state(cipher, state)
    assert result == ("verifier-123", uid, tid)


def test_state_tampered_returns_none() -> None:
    cipher = TokenCipher(_ENC_KEY)
    state = encode_connect_state(cipher, "verifier-123", uuid.uuid4(), uuid.uuid4())
    assert decode_connect_state(cipher, state + "x") is None


def test_state_wrong_key_returns_none() -> None:
    state = encode_connect_state(TokenCipher(_ENC_KEY), "v", uuid.uuid4(), uuid.uuid4())
    assert decode_connect_state(TokenCipher(Fernet.generate_key().decode()), state) is None


# ── POST /gmail/connect ───────────────────────────────────────────────────────


def test_connect_requires_auth(gmail_client: TestClient) -> None:
    assert gmail_client.post("/gmail/connect").status_code == 401


def test_connect_as_member_returns_403(gmail_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    with ExitStack() as stack:
        _push_auth(stack, user_id, tenant_id, "member")
        resp = gmail_client.post("/gmail/connect", headers=_bearer(user_id))
    assert resp.status_code == 403
    assert "gmail:connect" in resp.json()["detail"]


def test_connect_as_owner_returns_authorization_url(gmail_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    with ExitStack() as stack:
        _push_auth(stack, user_id, tenant_id, "owner")
        resp = gmail_client.post("/gmail/connect", headers=_bearer(user_id))
    assert resp.status_code == 200, resp.text
    url = resp.json()["authorization_url"]
    assert "accounts.google.com" in url
    assert "gmail.readonly" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=" in url


def test_connect_503_when_enc_key_missing() -> None:
    def _no_enc() -> Settings:
        return Settings(  # type: ignore[call-arg]
            groq_api_key="test",
            api_key="test-key",
            database_url=None,
            google_client_id="google-client-id",
            gmail_token_enc_key=None,  # feature disabled
            session_secret=_SECRET,
        )

    app.dependency_overrides[get_settings] = _no_enc
    try:
        user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
        with TestClient(app, raise_server_exceptions=False) as c, ExitStack() as stack:
            _push_auth(stack, user_id, tenant_id, "owner")
            resp = c.post("/gmail/connect", headers=_bearer(user_id))
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.pop(get_settings, None)


# ── GET /gmail/callback ───────────────────────────────────────────────────────


def test_callback_missing_state_returns_400(gmail_client: TestClient) -> None:
    resp = gmail_client.get("/gmail/callback", params={"code": "abc"}, follow_redirects=False)
    assert resp.status_code == 400


def test_callback_invalid_state_returns_400(gmail_client: TestClient) -> None:
    resp = gmail_client.get(
        "/gmail/callback",
        params={"code": "abc", "state": "not-a-valid-state"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "state" in resp.json()["detail"].lower()


def test_callback_denied_redirects_to_inbox(gmail_client: TestClient) -> None:
    resp = gmail_client.get(
        "/gmail/callback", params={"error": "access_denied"}, follow_redirects=False
    )
    assert resp.status_code == 302
    assert "gmail=denied" in resp.headers["location"]


def _run_callback(
    gmail_client: TestClient,
    token_json: dict[str, object],
    *,
    profile_json: dict[str, object] | None = None,
    gmail_repo: AsyncMock | None = None,
) -> httpx2.Response:
    uid, tid = uuid.uuid4(), uuid.uuid4()
    state = encode_connect_state(TokenCipher(_ENC_KEY), "verifier-123", uid, tid)

    token_resp = MagicMock(status_code=200)
    token_resp.json.return_value = token_json
    profile_resp = MagicMock(status_code=200)
    profile_resp.json.return_value = profile_json or {"emailAddress": "me@gmail.com"}

    mock_session = _make_session_mock()
    factory = _make_factory(mock_session)
    repo = gmail_repo or AsyncMock()

    with (
        patch("email_triage.routers.gmail.httpx.AsyncClient") as mock_httpx,
        patch(
            "email_triage.routers.gmail.get_session_factory",
            return_value=factory.return_value,
        ),
        patch("email_triage.routers.gmail.GmailRepo", return_value=repo),
    ):
        client = AsyncMock()
        client.post.return_value = token_resp
        client.get.return_value = profile_resp
        mock_httpx.return_value.__aenter__.return_value = client

        return gmail_client.get(
            "/gmail/callback", params={"code": "abc", "state": state}, follow_redirects=False
        )


def test_callback_stores_encrypted_refresh_token(gmail_client: TestClient) -> None:
    repo = AsyncMock()
    resp = _run_callback(
        gmail_client,
        {"refresh_token": "1//real-refresh", "access_token": "ya29.access"},
        gmail_repo=repo,
    )
    assert resp.status_code == 302
    assert "gmail=connected" in resp.headers["location"]

    repo.upsert.assert_awaited_once()
    stored = repo.upsert.await_args.kwargs["refresh_token_enc"]
    # Persisted value is ciphertext, not the plaintext token…
    assert stored != "1//real-refresh"
    # …and it decrypts back to the original with the configured key.
    assert TokenCipher(_ENC_KEY).decrypt(stored) == "1//real-refresh"
    assert repo.upsert.await_args.kwargs["google_email"] == "me@gmail.com"


def test_callback_missing_refresh_token_returns_502(gmail_client: TestClient) -> None:
    resp = _run_callback(gmail_client, {"access_token": "ya29.access"})  # no refresh_token
    assert resp.status_code == 502


# ── DELETE /gmail/connection ──────────────────────────────────────────────────


def test_disconnect_owner_deletes_connection(gmail_client: TestClient) -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    repo = AsyncMock()
    repo.delete.return_value = True
    with ExitStack() as stack:
        mock_session = _push_auth(stack, user_id, tenant_id, "owner")
        factory = _make_factory(mock_session)
        stack.enter_context(
            patch(
                "email_triage.routers.gmail.get_session_factory",
                return_value=factory.return_value,
            )
        )
        stack.enter_context(patch("email_triage.routers.gmail.GmailRepo", return_value=repo))
        resp = gmail_client.request("DELETE", "/gmail/connection", headers=_bearer(user_id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["disconnected"] is True
    repo.delete.assert_awaited_once()
