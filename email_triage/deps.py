from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import structlog
from fastapi import Depends, Header, HTTPException, Security
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from slowapi import Limiter
from slowapi.util import get_remote_address

from email_triage.auth.api_key import parse_api_key, secret_matches
from email_triage.auth.scopes import ROLE_SCOPES
from email_triage.auth.session import decode_access_token
from email_triage.config import Settings
from email_triage.db.engine import get_session_factory
from email_triage.db.models import User
from email_triage.db.repos.tenants import TenantRepo
from email_triage.db.repos.users import UserRepo
from email_triage.observability import AUTH_FAILURES_TOTAL
from email_triage.services.llm import LLMService

limiter = Limiter(key_func=get_remote_address)
_log = structlog.get_logger()

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


# ── API-key auth (machine clients via X-API-Key) ──────────────────────────────


@dataclass(frozen=True)
class TenantContext:
    """Identity resolved from an API key. ``tenant_id`` is None in the static
    no-DB fallback (local dev / tests) where there is no tenant row."""

    tenant_id: uuid.UUID | None


# Cache: sha256(api_key) → (tenant_id | None, expires_monotonic). Caches the
# *verification result* so the sha256 + DB round-trip is paid once per minute
# per key, not per request. tenant_id is immutable for a key, so caching it is
# safe; rotation clears the entry (see invalidate_api_key_cache).
_key_cache: dict[str, tuple[uuid.UUID | None, float]] = {}
_KEY_CACHE_TTL = 60.0
_KEY_CACHE_MAX = 10_000  # crude bound; an LRU would be the production choice


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # fields come from env vars


SettingsDep = Annotated[Settings, Depends(get_settings)]


def _cache_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def invalidate_api_key_cache() -> None:
    """Drop all cached verifications (called after a key rotation).

    Per-process only: with multiple workers each holds its own cache, so a
    rotated key may linger up to the TTL on other workers. A shared store
    (Redis) would make revocation instant across the fleet.
    """
    _key_cache.clear()


async def _resolve_tenant(api_key: str) -> uuid.UUID | None:
    """O(1) verify: parse tenant id from the key, fetch that one tenant, and
    compare the high-entropy secret in constant time. Returns the tenant id on
    success, None on any failure."""
    parsed = parse_api_key(api_key)
    if parsed is None:
        return None
    tenant_id, secret = parsed

    factory = get_session_factory()
    if factory is None:
        return None
    async with factory() as session:
        tenant = await TenantRepo().get_by_id(session, tenant_id)
    if tenant is None or tenant.api_key_hash is None:
        return None
    if not secret_matches(secret, tenant.api_key_hash):
        return None
    return tenant_id


async def verify_api_key(
    settings: SettingsDep,
    x_api_key: Annotated[str | None, Header()] = None,
) -> TenantContext:
    if x_api_key is None:
        AUTH_FAILURES_TOTAL.add(1)
        raise HTTPException(status_code=403, detail="Invalid or missing API key")

    # No DB configured → static shared key (local dev / tests); no tenant.
    if not settings.database_url or get_session_factory() is None:
        if x_api_key == settings.api_key:
            return TenantContext(tenant_id=None)
        AUTH_FAILURES_TOTAL.add(1)
        raise HTTPException(status_code=403, detail="Invalid or missing API key")

    ck = _cache_key(x_api_key)
    now = time.monotonic()
    cached = _key_cache.get(ck)
    if cached is not None and now < cached[1]:
        tenant_id = cached[0]
    else:
        tenant_id = await _resolve_tenant(x_api_key)
        if len(_key_cache) >= _KEY_CACHE_MAX:
            _key_cache.clear()
        _key_cache[ck] = (tenant_id, now + _KEY_CACHE_TTL)

    if tenant_id is None:
        AUTH_FAILURES_TOTAL.add(1)
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return TenantContext(tenant_id=tenant_id)


TenantDep = Annotated[TenantContext, Depends(verify_api_key)]


# ── Session context ───────────────────────────────────────────────────────────


@dataclass
class SessionContext:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    email: str
    display_name: str
    email_verified: bool
    tenant_name: str
    tenant_type: str
    plan: str


async def get_current_user(
    security_scopes: SecurityScopes,
    token: Annotated[str, Depends(_oauth2_scheme)],
    settings: SettingsDep,
) -> SessionContext:
    """Decode Bearer JWT, load user + membership + tenant, enforce scopes."""
    user_id = decode_access_token(settings.session_secret, token)
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    async with factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")

        membership = await UserRepo().get_membership(session, user_id)
        if membership is None:
            raise HTTPException(status_code=401, detail="No workspace membership found")

        tenant = await TenantRepo().get_by_id(session, membership.tenant_id)
        if tenant is None:
            raise HTTPException(status_code=401, detail="Workspace not found")

    user_scopes = ROLE_SCOPES.get(membership.role, frozenset())
    for scope in security_scopes.scopes:
        if scope not in user_scopes:
            raise HTTPException(
                status_code=403,
                detail=f"Scope required: {scope}",
                headers={"WWW-Authenticate": f'Bearer scope="{scope}"'},
            )

    return SessionContext(
        user_id=user_id,
        tenant_id=membership.tenant_id,
        role=membership.role,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified,
        tenant_name=tenant.name,
        tenant_type=tenant.type,
        plan=tenant.plan,
    )


CurrentUserDep = Annotated[SessionContext, Security(get_current_user, scopes=[])]
ManageWorkspaceDep = Annotated[
    SessionContext, Security(get_current_user, scopes=["workspace:manage"])
]


@lru_cache(maxsize=1)
def get_llm_service() -> LLMService:
    s = get_settings()
    return LLMService(api_key=s.groq_api_key, model=s.groq_model)
