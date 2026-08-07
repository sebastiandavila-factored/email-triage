"""Gmail connection flow (Gmail Ingestion F1, Plan 36).

A *separate* OAuth flow from the login (``routers/auth.py``): incremental consent for
the ``gmail.readonly`` scope with ``access_type=offline`` so Google returns a
``refresh_token``, which we store **encrypted** (``services.crypto.TokenCipher``) to pull
the day's emails later (Plan 37).

Identity binding — **stateless, no cookies**. ``POST /gmail/connect`` is authenticated
(Bearer) and mints an **encrypted** OAuth ``state`` carrying the caller's ``(user_id,
tenant_id)`` plus the PKCE ``code_verifier``. Google echoes ``state`` back to ``GET
/gmail/callback`` (a top-level browser navigation with no auth header); the callback decrypts
it to recover identity. Encryption (not just signing) keeps the ``code_verifier`` confidential
in the URL, and the ``ttl`` bounds replay. This avoids third-party cookies entirely, so the
flow works across the SPA/API origin split.
"""

from __future__ import annotations

import json
import urllib.parse
import uuid

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from email_triage.auth.pkce import code_challenge, generate_code_verifier
from email_triage.db.engine import get_session_factory
from email_triage.db.repos.gmail import GmailRepo
from email_triage.deps import ConnectGmailDep, SettingsDep
from email_triage.services.crypto import TokenCipher, TokenCipherError

_log = structlog.get_logger()

router = APIRouter(prefix="/gmail", tags=["gmail"])

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
# Read-only mailbox access — the minimum needed to pull email bodies for triage.
# RESTRICTED scope: production >100 users requires Google verification (CASA).
_GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_STATE_TTL = 600  # seconds; bounds how long a minted state stays valid


def _require_gmail_configured(settings: SettingsDep) -> str:
    """Ensure Gmail is configured; return the Fernet key (503 otherwise)."""
    if not settings.google_client_id or not settings.gmail_token_enc_key:
        raise HTTPException(status_code=503, detail="Gmail integration not configured")
    return settings.gmail_token_enc_key


def encode_connect_state(
    cipher: TokenCipher, code_verifier: str, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> str:
    """Encrypt the identity + PKCE verifier into the opaque OAuth ``state``."""
    return cipher.encrypt(
        json.dumps({"cv": code_verifier, "uid": str(user_id), "tid": str(tenant_id)})
    )


def decode_connect_state(
    cipher: TokenCipher, state: str
) -> tuple[str, uuid.UUID, uuid.UUID] | None:
    """Decrypt + validate the OAuth ``state`` → ``(code_verifier, user_id, tenant_id)``."""
    try:
        payload = json.loads(cipher.decrypt(state, ttl=_STATE_TTL))
        return payload["cv"], uuid.UUID(payload["uid"]), uuid.UUID(payload["tid"])
    except TokenCipherError, KeyError, ValueError, TypeError:
        return None


# ── POST /gmail/connect ───────────────────────────────────────────────────────


class ConnectResponse(BaseModel):
    authorization_url: str


@router.post("/connect")
async def connect(ctx: ConnectGmailDep, settings: SettingsDep) -> ConnectResponse:
    """Start the Gmail consent flow. Returns the Google authorization URL for the SPA to
    navigate to; identity travels in the encrypted ``state`` (no cookie)."""
    enc_key = _require_gmail_configured(settings)

    verifier = generate_code_verifier()
    challenge = code_challenge(verifier)
    state = encode_connect_state(TokenCipher(enc_key), verifier, ctx.user_id, ctx.tenant_id)

    params = urllib.parse.urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.gmail_redirect_uri,
            "response_type": "code",
            "scope": _GMAIL_SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # offline + consent guarantee a refresh_token, even on reconnect.
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    return ConnectResponse(authorization_url=f"{_GOOGLE_AUTH_URL}?{params}")


# ── GET /gmail/callback ───────────────────────────────────────────────────────


@router.get("/callback")
async def callback(
    settings: SettingsDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Google redirects here after consent. Recover identity from the encrypted state,
    exchange the code for a refresh token, store it encrypted, and bounce back to the inbox."""
    enc_key = _require_gmail_configured(settings)
    cipher = TokenCipher(enc_key)
    inbox = f"{settings.frontend_url}/inbox"

    if error:
        # User declined consent — not an error state, just no connection.
        return RedirectResponse(url=f"{inbox}?gmail=denied", status_code=302)
    if code is None or state is None:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    decoded = decode_connect_state(cipher, state)
    if decoded is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state")
    code_verifier, user_id, tenant_id = decoded

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.gmail_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
        if token_resp.status_code != 200:
            _log.warning("gmail.token_exchange_failed", status=token_resp.status_code)
            raise HTTPException(status_code=502, detail="Token exchange with Google failed")
        token_data: dict[str, object] = token_resp.json()

        refresh_token = str(token_data.get("refresh_token", ""))
        access_token = str(token_data.get("access_token", ""))
        if not refresh_token:
            # No refresh token means Google didn't grant offline access (e.g. a prior
            # consent without prompt=consent). We force prompt=consent, so this is rare.
            raise HTTPException(
                status_code=502,
                detail="Google did not return a refresh token — reconnect and grant access",
            )

        profile_resp = await client.get(
            _GMAIL_PROFILE_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        if profile_resp.status_code != 200:
            _log.warning("gmail.profile_fetch_failed", status=profile_resp.status_code)
            raise HTTPException(status_code=502, detail="Could not read the Gmail profile")
        google_email = str(profile_resp.json().get("emailAddress", ""))

    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    refresh_token_enc = cipher.encrypt(refresh_token)
    async with factory() as session, session.begin():
        await GmailRepo().upsert(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            google_email=google_email,
            refresh_token_enc=refresh_token_enc,
            scopes=_GMAIL_SCOPE,
        )

    _log.info("gmail.connected", tenant_id=str(tenant_id), email=google_email)
    return RedirectResponse(url=f"{inbox}?gmail=connected", status_code=302)


# ── DELETE /gmail/connection ──────────────────────────────────────────────────


class DisconnectResponse(BaseModel):
    disconnected: bool
    message: str


@router.delete("/connection")
async def disconnect(ctx: ConnectGmailDep) -> DisconnectResponse:
    """Remove the caller's Gmail connection for this workspace (deletes the stored
    encrypted refresh token)."""
    factory = get_session_factory()
    if factory is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    async with factory() as session, session.begin():
        removed = await GmailRepo().delete(session, ctx.tenant_id, ctx.user_id)

    return DisconnectResponse(
        disconnected=removed,
        message="Gmail disconnected." if removed else "No Gmail connection to remove.",
    )
