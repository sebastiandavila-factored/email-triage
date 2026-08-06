from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import logfire
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
from email_triage.db.repos.prompts import PromptVersionRepo
from email_triage.db.repos.tenants import TenantRepo
from email_triage.db.repos.users import UserRepo
from email_triage.evals_online import build_online_capability
from email_triage.observability import AUTH_FAILURES_TOTAL
from email_triage.schemas import (
    Category,
    DynamicStreamingTriageResponse,
    DynamicTriageResponse,
)
from email_triage.services.llm import SYSTEM_PROMPT, LLMService
from email_triage.services.prompt_studio import PromptStudioError, PromptStudioService

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


# ── Per-workspace RBAC (scoped by {tid} in the path) ──────────────────────────


@dataclass(frozen=True)
class WorkspaceContext:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


def require_scope(scope: str) -> Callable[..., Awaitable[WorkspaceContext]]:
    """Build a dependency that resolves the caller's membership in the workspace
    named by the path param ``tid`` and enforces ``scope`` against that role.

    Loading the membership by (user, tenant) also proves the caller belongs to
    the workspace — object-level authorization, so it doubles as IDOR defense.
    Pass scope="" to require only membership.
    """

    async def dependency(
        tid: uuid.UUID,
        settings: SettingsDep,
        token: Annotated[str, Depends(_oauth2_scheme)],
    ) -> WorkspaceContext:
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
            membership = await UserRepo().get_membership_in(session, user_id, tid)
        if membership is None:
            raise HTTPException(status_code=403, detail="Not a member of this workspace")
        if scope and scope not in ROLE_SCOPES.get(membership.role, frozenset()):
            raise HTTPException(
                status_code=403,
                detail=f"Scope required: {scope}",
                headers={"WWW-Authenticate": f'Bearer scope="{scope}"'},
            )
        return WorkspaceContext(user_id=user_id, tenant_id=tid, role=membership.role)

    return dependency


WorkspaceMemberDep = Annotated[WorkspaceContext, Depends(require_scope(""))]
ManageMembersDep = Annotated[WorkspaceContext, Depends(require_scope("workspace:manage"))]
DeleteWorkspaceDep = Annotated[WorkspaceContext, Depends(require_scope("workspace:delete"))]
ConfigureTriageDep = Annotated[WorkspaceContext, Depends(require_scope("triage:configure"))]
PublishPromptDep = Annotated[WorkspaceContext, Depends(require_scope("prompt:publish"))]
TracesReadDep = Annotated[WorkspaceContext, Depends(require_scope("traces:read"))]


# ── Prompt management (Logfire) ───────────────────────────────────────────────

PROMPT_VAR_NAME = "prompt__email_triage_system"

# Registered exactly once at import: ``logfire.var(name=...)`` is a registration
# call and raises if the same name is registered twice. The in-code SYSTEM_PROMPT
# is the ``default=`` so an unresolved/unreachable Logfire yields it
# (ResolvedVariable.reason == "code_default") and the critical path never breaks.
_SYSTEM_PROMPT_VAR = logfire.var(name=PROMPT_VAR_NAME, default=SYSTEM_PROMPT)


@lru_cache(maxsize=1)
def get_system_prompt() -> str:
    """Resolve the triage system prompt from Logfire Prompt Management, once per
    process (``@lru_cache`` + eager warm-up in the lifespan → no per-request fetch)."""
    settings = get_settings()
    return _SYSTEM_PROMPT_VAR.get(label=settings.prompt_label).value


def assert_category_coverage(prompt: str) -> None:
    """Governance guard for the prompt ↔ ``Category`` contract.

    The 5 categories are frozen in ``schemas.Category`` and code review is the gate
    for changing them. A prompt edited in the Logfire UI bypasses that gate, so on
    startup we verify the resolved prompt still mentions every category. On drift we
    log a structured warning and keep serving — the in-code fallback remains valid, so
    crashing would be worse than a loud warning.
    """
    missing = [c.value for c in Category if c.value not in prompt]
    if missing:
        _log.warning("prompt.category_drift", missing_categories=missing)


@lru_cache(maxsize=1)
def get_llm_service() -> LLMService:
    """Legacy service: static SYSTEM_PROMPT + frozen ``Category`` enum. Used on the
    no-DB path and as the safe fallback when the dynamic path can't resolve."""
    s = get_settings()
    capability = build_online_capability(s)
    return LLMService(
        api_key=s.groq_api_key,
        model=s.groq_model,
        system_prompt=get_system_prompt(),
        capabilities=[capability] if capability is not None else None,
    )


# ── Dynamic per-tenant triage service (Triage Studio F2/F3) ───────────────────

# One LLMService (Agent) per (tenant, version). For a published tenant the version
# is "v{n}"; otherwise it is a hash of the live-compiled draft prompt, so any edit
# (category, example, template) yields a new key and the stale entry ages out of
# this bounded LRU — invalidation for free.
_svc_cache: OrderedDict[tuple[uuid.UUID, str], LLMService] = OrderedDict()
_SVC_CACHE_MAX = 256


def clear_triage_service_cache() -> None:
    """Drop all cached per-tenant services. Per-process (like the api-key cache);
    a shared store would make it fleet-wide. Called after publish/rollback and in tests."""
    _svc_cache.clear()


def _build_service(system_prompt: str, allowed_slugs: frozenset[str]) -> LLMService:
    s = get_settings()
    capability = build_online_capability(s)
    return LLMService(
        api_key=s.groq_api_key,
        model=s.groq_model,
        system_prompt=system_prompt,
        capabilities=[capability] if capability is not None else None,
        output_type=DynamicTriageResponse,
        streaming_output_type=DynamicStreamingTriageResponse,
        allowed_slugs=allowed_slugs,
    )


def _cached_or_build(key: tuple[uuid.UUID, str], build: Callable[[], LLMService]) -> LLMService:
    cached = _svc_cache.get(key)
    if cached is not None:
        _svc_cache.move_to_end(key)
        return cached
    service = build()
    _svc_cache[key] = service
    if len(_svc_cache) > _SVC_CACHE_MAX:
        _svc_cache.popitem(last=False)
    return service


async def get_triage_service(tenant: TenantDep) -> LLMService:
    """Resolve the triage service for the calling workspace.

    "Published wins if present": a tenant with an active PromptVersion is served that
    frozen prompt; otherwise the draft is live-compiled (F2 + F3 examples/overrides).
    Falls back to the legacy service on no tenant / no DB / no active categories — the
    critical path must never 500 on prompt configuration.
    """
    tenant_id = tenant.tenant_id
    if tenant_id is None:
        return get_llm_service()
    factory = get_session_factory()
    if factory is None:
        return get_llm_service()
    try:
        async with factory() as session:
            active = await PromptVersionRepo().active(session, tenant_id)
            if active is not None:
                slugs = frozenset(json.loads(active.allowed_slugs))
                prompt = active.compiled_prompt
                return _cached_or_build(
                    (tenant_id, f"v{active.version}"),
                    lambda: _build_service(prompt, slugs),
                )
            draft = await PromptStudioService().compile_draft(session, tenant_id)
    except PromptStudioError:
        _log.warning("prompt.fallback", reason="no_active_categories")
        return get_llm_service()
    except Exception:
        _log.warning("prompt.fallback", reason="taxonomy_query_failed")
        return get_llm_service()

    token = hashlib.sha1(draft.prompt.encode()).hexdigest()  # noqa: S324 — cache key, not security
    return _cached_or_build(
        (tenant_id, token), lambda: _build_service(draft.prompt, draft.allowed_slugs)
    )
