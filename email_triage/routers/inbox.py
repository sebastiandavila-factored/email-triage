"""Today's inbox: pull Gmail and triage it (Gmail Ingestion F2, Plan 37).

Reuses the connection stored by Plan 36 and the per-tenant ``LLMService`` (unchanged): each
of today's unread emails is mapped to a ``TriageRequest`` and classified. Emails are
**ephemeral** — nothing but the existing ``TriageLog`` (chars, not content) is persisted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parseaddr

import httpx
import logfire
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from email_triage.db.engine import get_session_factory
from email_triage.db.repos.gmail import GmailRepo
from email_triage.deps import (
    SettingsDep,
    TenantContext,
    WriteTriageDep,
    get_triage_service,
)
from email_triage.schemas import (
    GmailStatusResponse,
    InboxItem,
    SyncRequest,
    SyncResponse,
    TriageRequest,
)
from email_triage.services.crypto import TokenCipher, TokenCipherError
from email_triage.services.gmail import (
    GmailAuthError,
    GmailClient,
    GmailError,
    GmailMessage,
    build_inbox_query,
)
from email_triage.services.llm import LLMError

_log = structlog.get_logger()

router = APIRouter(prefix="/gmail", tags=["gmail"])

_MAX_SUBJECT = 500
_MAX_BODY = 20_000
_FALLBACK_SENDER = "unknown@example.com"


def _to_triage_request(msg: GmailMessage) -> TriageRequest:
    """Map a Gmail message to the strict TriageRequest schema, coercing edge cases
    (display-name senders, empty bodies) so one odd email never 422s the batch."""
    _, addr = parseaddr(msg.sender)
    sender = addr or _FALLBACK_SENDER
    subject = (msg.subject or "(no subject)")[:_MAX_SUBJECT]
    body = (msg.body or msg.subject or " ").strip()[:_MAX_BODY] or " "
    try:
        return TriageRequest(subject=subject, sender=sender, body=body)
    except ValidationError:
        # Almost always an unparseable sender; fall back to a valid placeholder.
        return TriageRequest(subject=subject, sender=_FALLBACK_SENDER, body=body)


@router.get("/status")
async def status(ctx: WriteTriageDep) -> GmailStatusResponse:
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    async with factory() as session:
        conn = await GmailRepo().get_by_user(session, ctx.tenant_id, ctx.user_id)
    if conn is None:
        return GmailStatusResponse(connected=False)
    return GmailStatusResponse(
        connected=True, google_email=conn.google_email, last_synced_at=conn.last_synced_at
    )


@router.post("/sync")
async def sync(
    ctx: WriteTriageDep, settings: SettingsDep, req: SyncRequest | None = None
) -> SyncResponse:
    # Body is optional: no body → default filters (Plan 37's today's-unread behavior).
    req = req or SyncRequest()
    if not settings.google_client_id or not settings.gmail_token_enc_key:
        raise HTTPException(status_code=503, detail="Gmail integration not configured")
    if req.days > settings.gmail_sync_max_days:
        raise HTTPException(
            status_code=422,
            detail=f"days must be between 1 and {settings.gmail_sync_max_days}",
        )
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    async with factory() as session:
        conn = await GmailRepo().get_by_user(session, ctx.tenant_id, ctx.user_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Gmail not connected")

    try:
        refresh_token = TokenCipher(settings.gmail_token_enc_key).decrypt(conn.refresh_token_enc)
    except TokenCipherError as exc:
        # Key rotated or row tampered — the stored token is unusable; ask to reconnect.
        raise HTTPException(status_code=409, detail="Gmail connection invalid — reconnect") from exc

    gmail = GmailClient(settings.google_client_id, settings.google_client_secret)

    query = build_inbox_query(req.unread_only, req.days)

    with logfire.span("gmail.sync") as span:
        span.set_attribute("tenant_id", str(ctx.tenant_id))
        span.set_attribute("filter.unread_only", req.unread_only)
        span.set_attribute("filter.days", req.days)
        try:
            async with httpx.AsyncClient() as http:
                access_token = await gmail.refresh_access_token(http, refresh_token)
                messages = await gmail.list_today(
                    http, access_token, query, settings.gmail_sync_max_results
                )
        except GmailAuthError as exc:
            span.set_attribute("error.kind", "gmail_auth")
            raise HTTPException(
                status_code=409, detail="Gmail connection expired — reconnect"
            ) from exc
        except GmailError as exc:
            span.set_attribute("error.kind", "gmail_unavailable")
            raise HTTPException(status_code=502, detail="Gmail is unavailable") from exc

        span.set_attribute("gmail.messages.count", len(messages))

        # Reuse the tenant's live triage service ("published wins" / dynamic / fallback).
        svc = await get_triage_service(TenantContext(tenant_id=ctx.tenant_id))

        items: list[InboxItem] = []
        errors = 0
        with logfire.set_baggage(tenant_id=str(ctx.tenant_id)):
            for msg in messages:
                try:
                    result = await svc.triage(_to_triage_request(msg))
                except LLMError:
                    errors += 1
                    _log.warning("gmail.triage_failed", message_id=msg.message_id)
                    continue
                items.append(
                    InboxItem(
                        message_id=msg.message_id,
                        sender=msg.sender or _FALLBACK_SENDER,
                        subject=msg.subject,
                        received_at=msg.received_at,
                        category=str(result.category),
                        confidence=result.confidence,
                        draft_reply=result.draft_reply,
                        trace_id=result.trace_id,
                    )
                )

        # Every message failing (with at least one present) signals the LLM is down —
        # surface it instead of masking an outage as an empty inbox.
        if messages and errors == len(messages):
            span.set_attribute("error.kind", "llm_unavailable")
            raise HTTPException(status_code=503, detail="Triage service unavailable")

    async with factory() as session, session.begin():
        await GmailRepo().touch_last_synced(session, ctx.tenant_id, ctx.user_id)

    return SyncResponse(items=items, synced_at=datetime.now(UTC))
