from __future__ import annotations

import asyncio
import urllib.parse
import uuid

import bcrypt
import httpx
import structlog
from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import RedirectResponse
from joserfc import jwt as joserfc_jwt  # type: ignore[import-untyped]
from joserfc.jwk import KeySet  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, field_validator

from email_triage.auth.api_key import issue_api_key
from email_triage.auth.pkce import code_challenge, generate_code_verifier
from email_triage.auth.session import create_access_token
from email_triage.auth.state import generate_pkce_cookie, unpack_pkce_cookie
from email_triage.db.engine import get_session_factory
from email_triage.db.repos.tenants import TenantRepo
from email_triage.db.repos.users import UserRepo
from email_triage.deps import (
    CurrentUserDep,
    ManageWorkspaceDep,
    SettingsDep,
    invalidate_api_key_cache,
    limiter,
)

_log = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
# Google mints id_tokens with either form of the issuer; both are valid.
_GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
_PKCE_COOKIE = "pkce_state"
_SCOPES = "openid email profile"


# ── /auth/signup ──────────────────────────────────────────────────────────────


class SignupRequest(BaseModel):
    email: str = Field(min_length=6)
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=255)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        v = v.strip().lower()
        parts = v.rsplit("@", 1)
        if len(parts) != 2 or not parts[0] or "." not in parts[1]:  # noqa: PLR2004
            raise ValueError("Invalid email address")
        return v


class SignupResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str
    display_name: str
    tenant_id: uuid.UUID
    tenant_name: str
    tenant_type: str
    plan: str
    api_key: str
    message: str


@router.post("/signup")
@limiter.limit("5/minute")  # type: ignore[reportUnknownMemberType]
async def signup(
    request: Request,
    body: SignupRequest,
    settings: SettingsDep,
) -> SignupResponse:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    # Quick duplicate check before the slow bcrypt calls
    async with factory() as session:
        existing = await UserRepo().get_by_email(session, body.email)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Password hashing is CPU-bound → keep it outside the transaction.
    # The API key is hashed with a fast sha256 (see auth/api_key.py), so it is
    # issued cheaply inside the write phase once the tenant id exists.
    password_hash = (
        await asyncio.to_thread(
            bcrypt.hashpw,
            body.password.encode(),
            bcrypt.gensalt(rounds=settings.bcrypt_rounds),
        )
    ).decode()

    # Write: user + personal workspace + membership in one transaction
    async with factory() as session, session.begin():
        user = await UserRepo().create_with_password(
            session, body.email, body.display_name, password_hash
        )
        workspace_name = f"{body.display_name}'s workspace"
        tenant = await TenantRepo().create_personal(session, workspace_name)
        plaintext_key, key_hash = issue_api_key(tenant.id)
        tenant.api_key_hash = key_hash
        await TenantRepo().add_member(session, user.id, tenant.id, "owner")

    token = create_access_token(
        settings.session_secret, user.id, settings.access_token_expire_minutes
    )
    return SignupResponse(
        access_token=token,
        email=user.email,
        display_name=user.display_name,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        tenant_type=tenant.type,
        plan=tenant.plan,
        api_key=plaintext_key,
        message="Account created. Save your API key — it will not be shown again.",
    )


# ── POST /auth/login (password) ───────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str
    display_name: str
    tenant_id: uuid.UUID
    tenant_name: str
    tenant_type: str
    plan: str
    role: str
    message: str


_INVALID_CREDENTIALS = "Invalid credentials"


@router.post("/login")
@limiter.limit("5/minute")  # type: ignore[reportUnknownMemberType]
async def login_password(
    request: Request,
    body: LoginRequest,
    settings: SettingsDep,
) -> LoginResponse:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    async with factory() as session:
        user = await UserRepo().get_by_email(session, body.email.strip().lower())
    if user is None:
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)

    if user.password_hash is None:
        raise HTTPException(
            status_code=401,
            detail="This account uses Google Sign-In. Please log in with Google.",
        )

    is_valid = await asyncio.to_thread(
        bcrypt.checkpw, body.password.encode(), user.password_hash.encode()
    )
    if not is_valid:
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)

    async with factory() as session:
        membership = await UserRepo().get_membership(session, user.id)
        if membership is None:
            raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)
        tenant = await TenantRepo().get_by_id(session, membership.tenant_id)
        if tenant is None:
            raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)

    token = create_access_token(
        settings.session_secret, user.id, settings.access_token_expire_minutes
    )
    return LoginResponse(
        access_token=token,
        email=user.email,
        display_name=user.display_name,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        tenant_type=tenant.type,
        plan=tenant.plan,
        role=membership.role,
        message="Logged in successfully.",
    )


# ── GET /auth/login (Google SSO redirect) ────────────────────────────────────


@router.get("/login")
async def login(request: Request, settings: SettingsDep) -> RedirectResponse:
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google OAuth2 not configured")

    verifier = generate_code_verifier()
    challenge = code_challenge(verifier)
    pkce_cookie_value, state_token = generate_pkce_cookie(settings.session_secret, verifier)

    params = urllib.parse.urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "state": state_token,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
        }
    )
    is_prod = settings.logfire_environment == "production"
    redirect = RedirectResponse(url=f"{_GOOGLE_AUTH_URL}?{params}", status_code=302)
    redirect.set_cookie(
        key=_PKCE_COOKIE,
        value=pkce_cookie_value,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        max_age=300,
    )
    return redirect


# ── GET /auth/callback ────────────────────────────────────────────────────────


class CallbackResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str
    display_name: str
    tenant_name: str
    tenant_type: str
    plan: str
    api_key: str | None = None
    message: str


def _is_browser(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept


@router.get("/callback")
@limiter.limit("5/minute")  # type: ignore[reportUnknownMemberType]
async def callback(
    request: Request,
    settings: SettingsDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    pkce_state: str | None = Cookie(alias=_PKCE_COOKIE, default=None),
) -> CallbackResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth2 error: {error}")
    if code is None or state is None:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    if pkce_state is None:
        raise HTTPException(status_code=400, detail="PKCE cookie missing — restart login")
    unpacked = unpack_pkce_cookie(settings.session_secret, pkce_state)
    if unpacked is None:
        raise HTTPException(status_code=400, detail="PKCE cookie invalid or expired")
    code_verifier, expected_state = unpacked
    if state != expected_state:
        raise HTTPException(status_code=400, detail="State mismatch — possible CSRF attack")

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
        if token_resp.status_code != 200:
            _log.warning("auth.token_exchange_failed", status=token_resp.status_code)
            raise HTTPException(status_code=502, detail="Token exchange with Google failed")
        token_data: dict[str, object] = token_resp.json()

        jwks_resp = await client.get(_GOOGLE_JWKS_URL)
        jwks_data: dict[str, object] = jwks_resp.json()

    id_token = str(token_data.get("id_token", ""))
    if not id_token:
        raise HTTPException(status_code=502, detail="No id_token in Google response")

    try:
        key_set = KeySet.import_key_set(jwks_data)  # type: ignore[arg-type]
        # Pin RS256: without an explicit allow-list an attacker could present a
        # token signed with "none" or HS256 (alg-confusion). OpenID Connect also
        # requires verifying iss / aud / exp, not just the signature.
        google_token = joserfc_jwt.decode(id_token, key_set, algorithms=["RS256"])  # type: ignore[arg-type]
        claims_registry = joserfc_jwt.JWTClaimsRegistry(
            iss={"essential": True, "values": _GOOGLE_ISSUERS},
            aud={"essential": True, "value": settings.google_client_id},
            exp={"essential": True},
            sub={"essential": True},
        )
        claims_registry.validate(google_token.claims)
        claims = google_token.claims
    except Exception as exc:
        _log.warning("auth.id_token_invalid", error=str(exc))
        raise HTTPException(status_code=401, detail="Invalid ID token") from exc

    google_sub = str(claims.get("sub", ""))
    email = str(claims.get("email", ""))
    display_name = str(claims.get("name", email.split("@")[0]))
    # Google may send email_verified as a bool or the string "true".
    raw_verified = claims.get("email_verified", False)
    email_verified = raw_verified is True or str(raw_verified).lower() == "true"
    if not google_sub or not email:
        raise HTTPException(status_code=502, detail="Missing claims in ID token")

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    # Read phase: find the target user and decide what to create.
    #  - matched by google_sub → returning Google user
    #  - else matched by a *verified* email → link Google to an existing
    #    password account (avoids a duplicate-email 500 and account splitting)
    #  - else → brand-new user
    link_google = False
    async with factory() as session:
        existing_user = await UserRepo().get_by_google_sub(session, google_sub)
        if existing_user is None:
            user_by_email = await UserRepo().get_by_email(session, email)
            if user_by_email is not None:
                if not email_verified:
                    # The email is taken but Google hasn't verified it for this
                    # login — refuse to link (prevents account takeover).
                    raise HTTPException(
                        status_code=409,
                        detail="An account with this email already exists. "
                        "Log in with your password.",
                    )
                existing_user = user_by_email
                link_google = True
        existing_membership = (
            await UserRepo().get_membership(session, existing_user.id)
            if existing_user is not None
            else None
        )

    needs_workspace = existing_membership is None
    plaintext_key: str | None = None

    # Write phase
    user_id_val: uuid.UUID
    tenant_name_val: str
    tenant_type_val: str
    plan_val: str

    async with factory() as session, session.begin():
        if existing_user is None:
            user = await UserRepo().create_from_google(
                session, google_sub, email, display_name, email_verified
            )
        else:
            refreshed = await session.get(
                type(existing_user),
                existing_user.id,  # type: ignore[arg-type]
            )
            if refreshed is None:
                raise HTTPException(status_code=503, detail="User not found after read")
            refreshed.display_name = display_name
            if link_google:
                # First Google login for a pre-existing password account.
                refreshed.google_sub = google_sub
                refreshed.email_verified = True
            user = refreshed

        user_id_val = user.id

        if needs_workspace:
            workspace_name = f"{display_name}'s workspace"
            tenant = await TenantRepo().create_personal(session, workspace_name)
            plaintext_key, key_hash = issue_api_key(tenant.id)
            tenant.api_key_hash = key_hash
            await TenantRepo().add_member(session, user_id_val, tenant.id, "owner")
            tenant_name_val = tenant.name
            tenant_type_val = tenant.type
            plan_val = tenant.plan
        else:
            assert existing_membership is not None
            tenant = await TenantRepo().get_by_id(session, existing_membership.tenant_id)
            if tenant is None:
                raise HTTPException(status_code=503, detail="Workspace not found")
            tenant_name_val = tenant.name
            tenant_type_val = tenant.type
            plan_val = tenant.plan

    token = create_access_token(
        settings.session_secret, user_id_val, settings.access_token_expire_minutes
    )
    msg = (
        "Welcome back!"
        if not needs_workspace
        else "Account created. Save your API key — it will not be shown again."
    )

    # Browser flow: redirect to frontend with only the session token in the URL
    # fragment. The API key is intentionally NOT placed in the URL (it would
    # leak into browser history); new Google users mint one via /auth/rotate-key.
    if _is_browser(request):
        return RedirectResponse(  # type: ignore[return-value]
            url=f"{settings.frontend_url}/#token={token}",
            status_code=302,
        )

    return CallbackResponse(
        access_token=token,
        email=email,
        display_name=display_name,
        tenant_name=tenant_name_val,
        tenant_type=tenant_type_val,
        plan=plan_val,
        api_key=plaintext_key,
        message=msg,
    )


# ── /auth/me ─────────────────────────────────────────────────────────────────


class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    email_verified: bool
    tenant_id: uuid.UUID
    tenant_name: str
    tenant_type: str
    plan: str
    role: str


@router.get("/me")
async def me(ctx: CurrentUserDep) -> MeResponse:
    return MeResponse(
        user_id=ctx.user_id,
        email=ctx.email,
        display_name=ctx.display_name,
        email_verified=ctx.email_verified,
        tenant_id=ctx.tenant_id,
        tenant_name=ctx.tenant_name,
        tenant_type=ctx.tenant_type,
        plan=ctx.plan,
        role=ctx.role,
    )


# ── /auth/logout ──────────────────────────────────────────────────────────────


@router.post("/logout")
async def logout(_ctx: CurrentUserDep) -> dict[str, str]:
    # JWT is stateless — the client discards the token to log out.
    return {"message": "Logged out"}


# ── /auth/rotate-key ─────────────────────────────────────────────────────────


class RotateKeyResponse(BaseModel):
    api_key: str
    message: str


@router.post("/rotate-key")
async def rotate_key(ctx: ManageWorkspaceDep) -> RotateKeyResponse:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    plaintext, new_hash = issue_api_key(ctx.tenant_id)

    async with factory() as session, session.begin():
        await TenantRepo().update_api_key_hash(session, ctx.tenant_id, new_hash)

    # Drop cached verifications so the old key stops working immediately
    # (on this worker — see invalidate_api_key_cache for the multi-worker caveat).
    invalidate_api_key_cache()
    _log.info("tenant.key_rotated", tenant_id=str(ctx.tenant_id))
    return RotateKeyResponse(
        api_key=plaintext,
        message="New API key issued. Save it — it will not be shown again.",
    )
