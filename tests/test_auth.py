"""Unit tests for Plan 15 (Google OAuth2 SSO) and Plan 16 (Users + Password Auth + JWT)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from email_triage.auth.pkce import code_challenge, generate_code_verifier
from email_triage.auth.session import create_access_token, decode_access_token
from email_triage.auth.state import generate_pkce_cookie, unpack_pkce_cookie
from email_triage.config import Settings
from email_triage.db.models import Membership, Tenant, User
from email_triage.deps import get_settings
from email_triage.main import app
from fastapi.testclient import TestClient

_SECRET = "test-session-secret-32-bytes-here"
_PKCE_COOKIE = "pkce_state"


def _mock_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        groq_api_key="test",
        api_key="test-key",
        database_url=None,
        google_client_id="google-client-id",
        google_client_secret="google-client-secret",
        google_redirect_uri="http://localhost:8000/auth/callback",
        session_secret=_SECRET,
        bcrypt_rounds=4,  # fast for tests
    )


@pytest.fixture()
def auth_client() -> Generator[TestClient]:
    app.dependency_overrides[get_settings] = _mock_settings
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.pop(get_settings, None)


# ── Shared mock helpers ───────────────────────────────────────────────────────


def _make_session_mock() -> tuple[AsyncMock, MagicMock]:
    """Return (mock_session, mock_cm) where mock_cm is the begin() context manager."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=None)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_cm)
    return mock_session, mock_cm


def _make_factory_mock(mock_session: AsyncMock) -> MagicMock:
    mock_factory_inst = MagicMock()
    mock_factory_inst.return_value = mock_session
    mock_factory = MagicMock()
    mock_factory.return_value = mock_factory_inst
    return mock_factory


def _bearer(user_id: uuid.UUID) -> dict[str, str]:
    """Build an Authorization header dict for use in test requests."""
    token = create_access_token(_SECRET, user_id)
    return {"Authorization": f"Bearer {token}"}


# ── PKCE ─────────────────────────────────────────────────────────────────────


def test_pkce_verifier_length() -> None:
    v = generate_code_verifier()
    assert 43 <= len(v) <= 128


def test_pkce_challenge_matches_s256() -> None:
    import base64
    import hashlib

    v = generate_code_verifier()
    c = code_challenge(v)
    expected = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert c == expected


# ── State / PKCE cookie ───────────────────────────────────────────────────────


def test_pkce_cookie_round_trip() -> None:
    verifier = generate_code_verifier()
    cookie, _ = generate_pkce_cookie(_SECRET, verifier)
    result = unpack_pkce_cookie(_SECRET, cookie)
    assert result is not None
    cv, _ = result
    assert cv == verifier


def test_pkce_cookie_expired() -> None:
    verifier = generate_code_verifier()
    cookie, _ = generate_pkce_cookie(_SECRET, verifier)
    result = unpack_pkce_cookie(_SECRET, cookie, max_age=-1)
    assert result is None


def test_pkce_cookie_tampered() -> None:
    verifier = generate_code_verifier()
    cookie, _ = generate_pkce_cookie(_SECRET, verifier)
    result = unpack_pkce_cookie(_SECRET, cookie + "x")
    assert result is None


# ── JWT access token ──────────────────────────────────────────────────────────


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(_SECRET, user_id)
    recovered = decode_access_token(_SECRET, token)
    assert recovered == user_id


def test_access_token_wrong_secret() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(_SECRET, user_id)
    assert decode_access_token("wrong-secret", token) is None


def test_access_token_tampered() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(_SECRET, user_id)
    assert decode_access_token(_SECRET, token + "x") is None


def test_access_token_has_standard_claims() -> None:
    import jwt

    user_id = uuid.uuid4()
    token = create_access_token(_SECRET, user_id)
    payload = jwt.decode(token, _SECRET, algorithms=["HS256"])
    assert payload["sub"] == str(user_id)
    assert "exp" in payload
    assert "iat" in payload


# ── GET /auth/login (Google SSO redirect) ────────────────────────────────────


def test_login_redirects_to_google(auth_client: TestClient) -> None:
    response = auth_client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert "accounts.google.com" in location
    assert "code_challenge" in location
    assert "state" in location
    assert "openid" in location
    assert _PKCE_COOKIE in response.cookies


def test_login_503_when_not_configured() -> None:
    def _no_google() -> Settings:
        # Pin every field this test depends on so a populated .env (real Google
        # creds, DATABASE_URL) cannot leak in and change the outcome.
        return Settings(  # type: ignore[call-arg]
            groq_api_key="test",
            api_key="test-key",
            session_secret=_SECRET,
            database_url=None,
            google_client_id="",
        )

    app.dependency_overrides[get_settings] = _no_google
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get("/auth/login", follow_redirects=False)
        assert response.status_code == 503
    finally:
        app.dependency_overrides.pop(get_settings, None)


# ── GET /auth/callback ────────────────────────────────────────────────────────


def test_callback_missing_code_returns_400(auth_client: TestClient) -> None:
    response = auth_client.get("/auth/callback")
    assert response.status_code == 400


def test_callback_missing_pkce_cookie_returns_400(auth_client: TestClient) -> None:
    response = auth_client.get("/auth/callback?code=abc&state=xyz")
    assert response.status_code == 400
    assert "PKCE" in response.json()["detail"]


def test_callback_state_mismatch_returns_400(auth_client: TestClient) -> None:
    verifier = generate_code_verifier()
    cookie_val, _ = generate_pkce_cookie(_SECRET, verifier)
    auth_client.cookies.set(_PKCE_COOKIE, cookie_val)
    response = auth_client.get("/auth/callback?code=abc&state=definitely-wrong-state")
    assert response.status_code == 400
    assert "State mismatch" in response.json()["detail"]


def test_callback_creates_user_and_workspace_on_first_login(
    auth_client: TestClient,
) -> None:
    verifier = generate_code_verifier()
    cookie_val, state_token = generate_pkce_cookie(_SECRET, verifier)

    # A realistic Google id_token claim set — the callback now validates
    # iss / aud / exp for real (aud must equal the mock client id).
    fake_claims = {
        "sub": "google-sub-123",
        "email": "founder@example.com",
        "name": "Founder",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": "google-client-id",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }

    fake_user = User(
        id=uuid.uuid4(),
        google_sub="google-sub-123",
        email="founder@example.com",
        display_name="Founder",
        email_verified=True,
    )
    fake_tenant = Tenant(
        id=uuid.uuid4(),
        name="Founder's workspace",
        type="personal",
        domain=None,
        api_key_hash="$2b$04$fakehash",
        plan="free",
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"id_token": "fake.jwt.token"}

    mock_jwks_resp = MagicMock()
    mock_jwks_resp.json.return_value = {"keys": []}

    mock_decoded_token = MagicMock()
    mock_decoded_token.claims = fake_claims

    mock_session, _ = _make_session_mock()
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch("email_triage.routers.auth.httpx.AsyncClient") as mock_httpx,
        patch("email_triage.routers.auth.KeySet.import_key_set"),
        patch("email_triage.routers.auth.joserfc_jwt.decode", return_value=mock_decoded_token),
        patch(
            "email_triage.routers.auth.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.routers.auth.UserRepo") as mock_user_repo_cls,
        patch("email_triage.routers.auth.TenantRepo") as mock_tenant_repo_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_token_resp
        mock_client.get.return_value = mock_jwks_resp
        mock_httpx.return_value.__aenter__.return_value = mock_client

        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_google_sub.return_value = None  # new user
        mock_user_repo.get_by_email.return_value = None  # no account to link to
        mock_user_repo.create_from_google.return_value = fake_user
        mock_user_repo_cls.return_value = mock_user_repo

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.create_personal.return_value = fake_tenant
        mock_tenant_repo.add_member.return_value = MagicMock()
        mock_tenant_repo_cls.return_value = mock_tenant_repo

        auth_client.cookies.set(_PKCE_COOKIE, cookie_val)
        response = auth_client.get(f"/auth/callback?code=abc&state={state_token}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["email"] == "founder@example.com"
    assert data["api_key"] is not None
    assert data["tenant_name"] == "Founder's workspace"
    assert data["tenant_type"] == "personal"
    assert data["access_token"]
    assert data["token_type"] == "bearer"


def _valid_google_claims(**overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "sub": "google-sub-123",
        "email": "founder@example.com",
        "name": "Founder",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": "google-client-id",  # must match _mock_settings().google_client_id
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    claims.update(overrides)
    return claims


def _run_callback(
    auth_client: TestClient,
    claims: dict[str, object],
    user_repo: AsyncMock,
    tenant_repo: AsyncMock,
    session_get: object = None,
) -> httpx.Response:
    """Drive GET /auth/callback with a mocked Google exchange + DB layer.

    joserfc_jwt.decode is patched (no real signature check), but the callback's
    JWTClaimsRegistry runs for real against `claims`.
    """
    verifier = generate_code_verifier()
    cookie_val, state_token = generate_pkce_cookie(_SECRET, verifier)

    mock_token_resp = MagicMock(status_code=200)
    mock_token_resp.json.return_value = {"id_token": "fake.jwt.token"}
    mock_jwks_resp = MagicMock()
    mock_jwks_resp.json.return_value = {"keys": []}
    mock_decoded = MagicMock()
    mock_decoded.claims = claims

    mock_session, _ = _make_session_mock()
    if session_get is not None:
        mock_session.get.return_value = session_get
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch("email_triage.routers.auth.httpx.AsyncClient") as mock_httpx,
        patch("email_triage.routers.auth.KeySet.import_key_set"),
        patch("email_triage.routers.auth.joserfc_jwt.decode", return_value=mock_decoded),
        patch(
            "email_triage.routers.auth.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.routers.auth.UserRepo", return_value=user_repo),
        patch("email_triage.routers.auth.TenantRepo", return_value=tenant_repo),
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_token_resp
        mock_client.get.return_value = mock_jwks_resp
        mock_httpx.return_value.__aenter__.return_value = mock_client

        auth_client.cookies.set(_PKCE_COOKIE, cookie_val)
        return auth_client.get(f"/auth/callback?code=abc&state={state_token}")


def test_callback_rejects_wrong_audience(auth_client: TestClient) -> None:
    user_repo = AsyncMock()
    user_repo.get_by_google_sub.return_value = None
    user_repo.get_by_email.return_value = None
    response = _run_callback(
        auth_client,
        _valid_google_claims(aud="attacker-client-id"),
        user_repo,
        AsyncMock(),
    )
    assert response.status_code == 401, response.text
    user_repo.create_from_google.assert_not_called()


def test_callback_rejects_expired_token(auth_client: TestClient) -> None:
    user_repo = AsyncMock()
    user_repo.get_by_google_sub.return_value = None
    user_repo.get_by_email.return_value = None
    response = _run_callback(
        auth_client,
        _valid_google_claims(exp=int(time.time()) - 10),
        user_repo,
        AsyncMock(),
    )
    assert response.status_code == 401, response.text


def test_callback_links_google_to_existing_password_account(auth_client: TestClient) -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    password_user = User(
        id=user_id,
        email="founder@example.com",
        display_name="Founder",
        password_hash="$2b$04$fakehash",
        google_sub=None,
        email_verified=False,
    )
    membership = Membership(user_id=user_id, tenant_id=tenant_id, role="owner")
    tenant = Tenant(
        id=tenant_id,
        name="Founder's workspace",
        type="personal",
        domain=None,
        api_key_hash="sha256hash",
        plan="free",
    )

    user_repo = AsyncMock()
    user_repo.get_by_google_sub.return_value = None  # no Google identity yet
    user_repo.get_by_email.return_value = password_user  # but the email exists
    user_repo.get_membership.return_value = membership
    tenant_repo = AsyncMock()
    tenant_repo.get_by_id.return_value = tenant

    response = _run_callback(
        auth_client,
        _valid_google_claims(),
        user_repo,
        tenant_repo,
        session_get=password_user,
    )

    assert response.status_code == 200, response.text
    # Linked, not duplicated: no new user, no new workspace.
    user_repo.create_from_google.assert_not_called()
    tenant_repo.create_personal.assert_not_called()
    # Google identity is now attached to the existing account.
    assert password_user.google_sub == "google-sub-123"
    assert password_user.email_verified is True


# ── GET /auth/me ──────────────────────────────────────────────────────────────


def test_me_unauthenticated_returns_401(auth_client: TestClient) -> None:
    response = auth_client.get("/auth/me")
    assert response.status_code == 401


def test_me_with_valid_token(auth_client: TestClient) -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    fake_user = User(
        id=user_id,
        email="user@example.com",
        display_name="Test User",
        email_verified=True,
        google_sub="google-sub-456",
    )
    fake_membership = Membership(user_id=user_id, tenant_id=tenant_id, role="owner")
    fake_tenant = Tenant(
        id=tenant_id,
        name="Test User's workspace",
        type="personal",
        domain=None,
        api_key_hash="$2b$04$fakehash",
        plan="free",
    )

    mock_session, _ = _make_session_mock()
    mock_session.get.return_value = fake_user
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch(
            "email_triage.deps.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.deps.UserRepo") as mock_user_repo_cls,
        patch("email_triage.deps.TenantRepo") as mock_tenant_repo_cls,
    ):
        mock_user_repo = AsyncMock()
        mock_user_repo.get_membership.return_value = fake_membership
        mock_user_repo_cls.return_value = mock_user_repo

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.get_by_id.return_value = fake_tenant
        mock_tenant_repo_cls.return_value = mock_tenant_repo

        response = auth_client.get("/auth/me", headers=_bearer(user_id))

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["user_id"] == str(user_id)
    assert data["email"] == "user@example.com"
    assert data["display_name"] == "Test User"
    assert data["email_verified"] is True
    assert data["tenant_id"] == str(tenant_id)
    assert data["tenant_name"] == "Test User's workspace"
    assert data["tenant_type"] == "personal"
    assert data["plan"] == "free"
    assert data["role"] == "owner"


# ── POST /auth/signup ─────────────────────────────────────────────────────────


def test_signup_creates_user_and_personal_tenant(auth_client: TestClient) -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    fake_user = User(
        id=user_id,
        email="alice@acme.com",
        display_name="Alice",
        email_verified=False,
    )
    fake_tenant = Tenant(
        id=tenant_id,
        name="Alice's workspace",
        type="personal",
        domain=None,
        api_key_hash="$2b$04$fakehash",
        plan="free",
    )

    mock_session, _ = _make_session_mock()
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch(
            "email_triage.routers.auth.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.routers.auth.UserRepo") as mock_user_repo_cls,
        patch("email_triage.routers.auth.TenantRepo") as mock_tenant_repo_cls,
    ):
        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email.return_value = None  # no duplicate
        mock_user_repo.create_with_password.return_value = fake_user
        mock_user_repo_cls.return_value = mock_user_repo

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.create_personal.return_value = fake_tenant
        mock_tenant_repo.add_member.return_value = MagicMock()
        mock_tenant_repo_cls.return_value = mock_tenant_repo

        response = auth_client.post(
            "/auth/signup",
            json={"email": "alice@acme.com", "password": "securepass1", "display_name": "Alice"},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["email"] == "alice@acme.com"
    assert data["display_name"] == "Alice"
    assert data["tenant_type"] == "personal"
    assert data["plan"] == "free"
    assert data["api_key"]
    assert data["access_token"]
    assert data["token_type"] == "bearer"


def test_signup_duplicate_email_returns_409(auth_client: TestClient) -> None:
    fake_existing = User(
        id=uuid.uuid4(), email="alice@acme.com", display_name="Alice", email_verified=False
    )

    mock_session, _ = _make_session_mock()
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch(
            "email_triage.routers.auth.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.routers.auth.UserRepo") as mock_user_repo_cls,
    ):
        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email.return_value = fake_existing
        mock_user_repo_cls.return_value = mock_user_repo

        response = auth_client.post(
            "/auth/signup",
            json={"email": "alice@acme.com", "password": "securepass1", "display_name": "Alice"},
        )

    assert response.status_code == 409


def test_signup_weak_password_returns_422(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/auth/signup",
        json={"email": "alice@acme.com", "password": "short", "display_name": "Alice"},
    )
    assert response.status_code == 422


def test_signup_invalid_email_returns_422(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/auth/signup",
        json={"email": "not-an-email", "password": "securepass1", "display_name": "Alice"},
    )
    assert response.status_code == 422


# ── POST /auth/login (password) ───────────────────────────────────────────────


def test_login_password_success(auth_client: TestClient) -> None:
    import bcrypt as _bcrypt

    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    password = "securepass1"
    pw_hash = _bcrypt.hashpw(password.encode(), _bcrypt.gensalt(rounds=4)).decode()

    fake_user = User(
        id=user_id,
        email="alice@acme.com",
        display_name="Alice",
        password_hash=pw_hash,
        email_verified=False,
    )
    fake_membership = Membership(user_id=user_id, tenant_id=tenant_id, role="owner")
    fake_tenant = Tenant(
        id=tenant_id,
        name="Alice's workspace",
        type="personal",
        domain=None,
        api_key_hash="$2b$04$fakehash",
        plan="free",
    )

    mock_session, _ = _make_session_mock()
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch(
            "email_triage.routers.auth.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.routers.auth.UserRepo") as mock_user_repo_cls,
        patch("email_triage.routers.auth.TenantRepo") as mock_tenant_repo_cls,
    ):
        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email.return_value = fake_user
        mock_user_repo.get_membership.return_value = fake_membership
        mock_user_repo_cls.return_value = mock_user_repo

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.get_by_id.return_value = fake_tenant
        mock_tenant_repo_cls.return_value = mock_tenant_repo

        response = auth_client.post(
            "/auth/login", json={"email": "alice@acme.com", "password": password}
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["email"] == "alice@acme.com"
    assert data["role"] == "owner"
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert "api_key" not in data  # not returned on login


def test_login_wrong_password_returns_401(auth_client: TestClient) -> None:
    import bcrypt as _bcrypt

    user_id = uuid.uuid4()
    pw_hash = _bcrypt.hashpw(b"correctpass", _bcrypt.gensalt(rounds=4)).decode()

    fake_user = User(
        id=user_id,
        email="alice@acme.com",
        display_name="Alice",
        password_hash=pw_hash,
        email_verified=False,
    )

    mock_session, _ = _make_session_mock()
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch(
            "email_triage.routers.auth.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.routers.auth.UserRepo") as mock_user_repo_cls,
    ):
        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email.return_value = fake_user
        mock_user_repo_cls.return_value = mock_user_repo

        response = auth_client.post(
            "/auth/login", json={"email": "alice@acme.com", "password": "wrongpass"}
        )

    assert response.status_code == 401


def test_login_unknown_email_returns_401(auth_client: TestClient) -> None:
    mock_session, _ = _make_session_mock()
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch(
            "email_triage.routers.auth.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.routers.auth.UserRepo") as mock_user_repo_cls,
    ):
        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email.return_value = None
        mock_user_repo_cls.return_value = mock_user_repo

        response = auth_client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
        )

    assert response.status_code == 401
    # Same message as wrong password (no user enumeration)
    assert response.json()["detail"] == "Invalid credentials"


def test_login_wrong_password_same_message_as_unknown(auth_client: TestClient) -> None:
    """Both wrong-password and unknown-email return the same detail string."""
    import bcrypt as _bcrypt

    pw_hash = _bcrypt.hashpw(b"correct", _bcrypt.gensalt(rounds=4)).decode()
    fake_user = User(
        id=uuid.uuid4(),
        email="alice@acme.com",
        display_name="Alice",
        password_hash=pw_hash,
        email_verified=False,
    )

    mock_session, _ = _make_session_mock()
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch(
            "email_triage.routers.auth.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.routers.auth.UserRepo") as mock_user_repo_cls,
    ):
        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email.return_value = fake_user
        mock_user_repo_cls.return_value = mock_user_repo
        resp_wrong = auth_client.post(
            "/auth/login", json={"email": "alice@acme.com", "password": "wrong"}
        )

        mock_user_repo.get_by_email.return_value = None
        resp_unknown = auth_client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "wrong"}
        )

    assert resp_wrong.json()["detail"] == resp_unknown.json()["detail"]


def test_login_google_only_account_returns_401(auth_client: TestClient) -> None:
    fake_user = User(
        id=uuid.uuid4(),
        email="google@example.com",
        display_name="Google User",
        password_hash=None,  # Google-only account
        google_sub="google-sub-789",
        email_verified=True,
    )

    mock_session, _ = _make_session_mock()
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch(
            "email_triage.routers.auth.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.routers.auth.UserRepo") as mock_user_repo_cls,
    ):
        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_email.return_value = fake_user
        mock_user_repo_cls.return_value = mock_user_repo

        response = auth_client.post(
            "/auth/login", json={"email": "google@example.com", "password": "anything"}
        )

    assert response.status_code == 401
    assert "Google" in response.json()["detail"]


# ── POST /auth/rotate-key — scope enforcement ─────────────────────────────────


def test_rotate_key_as_member_returns_403(auth_client: TestClient) -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    fake_user = User(
        id=user_id, email="member@acme.com", display_name="Member", email_verified=True
    )
    fake_membership = Membership(user_id=user_id, tenant_id=tenant_id, role="member")
    fake_tenant = Tenant(
        id=tenant_id, name="Acme workspace", type="personal", domain=None, plan="free"
    )

    mock_session, _ = _make_session_mock()
    mock_session.get.return_value = fake_user
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch(
            "email_triage.deps.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.deps.UserRepo") as mock_user_repo_cls,
        patch("email_triage.deps.TenantRepo") as mock_tenant_repo_cls,
    ):
        mock_user_repo = AsyncMock()
        mock_user_repo.get_membership.return_value = fake_membership
        mock_user_repo_cls.return_value = mock_user_repo

        mock_tenant_repo = AsyncMock()
        mock_tenant_repo.get_by_id.return_value = fake_tenant
        mock_tenant_repo_cls.return_value = mock_tenant_repo

        response = auth_client.post("/auth/rotate-key", headers=_bearer(user_id))

    assert response.status_code == 403
    assert "workspace:manage" in response.json()["detail"]


def test_rotate_key_as_owner_succeeds(auth_client: TestClient) -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    fake_user = User(id=user_id, email="owner@acme.com", display_name="Owner", email_verified=True)
    fake_membership = Membership(user_id=user_id, tenant_id=tenant_id, role="owner")
    fake_tenant = Tenant(
        id=tenant_id, name="Acme workspace", type="personal", domain=None, plan="free"
    )

    mock_session, _ = _make_session_mock()
    mock_session.get.return_value = fake_user
    mock_factory = _make_factory_mock(mock_session)

    with (
        patch(
            "email_triage.deps.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.deps.UserRepo") as mock_deps_user_repo_cls,
        patch("email_triage.deps.TenantRepo") as mock_deps_tenant_repo_cls,
        patch(
            "email_triage.routers.auth.get_session_factory",
            return_value=mock_factory.return_value,
        ),
        patch("email_triage.routers.auth.TenantRepo") as mock_auth_tenant_repo_cls,
    ):
        # get_current_user mocks (in deps)
        mock_deps_user_repo = AsyncMock()
        mock_deps_user_repo.get_membership.return_value = fake_membership
        mock_deps_user_repo_cls.return_value = mock_deps_user_repo

        mock_deps_tenant_repo = AsyncMock()
        mock_deps_tenant_repo.get_by_id.return_value = fake_tenant
        mock_deps_tenant_repo_cls.return_value = mock_deps_tenant_repo

        # rotate_key body mocks (in routers/auth)
        mock_auth_tenant_repo = AsyncMock()
        mock_auth_tenant_repo.update_api_key_hash.return_value = None
        mock_auth_tenant_repo_cls.return_value = mock_auth_tenant_repo

        response = auth_client.post("/auth/rotate-key", headers=_bearer(user_id))

    assert response.status_code == 200, response.text
    data = response.json()
    assert "api_key" in data and data["api_key"]
