"""Gmail API client for pulling the day's emails (Gmail Ingestion F2, Plan 37).

Given a stored (encrypted, then decrypted) ``refresh_token``, this refreshes a short-lived
access token and lists today's unread inbox messages, parsing each into a plain
``GmailMessage`` that the router maps to a ``TriageRequest``. No triage logic here — the
existing per-tenant ``LLMService`` does the classification, unchanged.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import cast

import httpx
import structlog

_log = structlog.get_logger()

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"


def build_inbox_query(unread_only: bool, days: int) -> str:
    """Build the Gmail search query for an inbox sync (Plan 40).

    ``in:inbox`` always; ``is:unread`` only when filtering to unread; ``newer_than:Nd`` is a
    rolling N×24h window (good enough for v1 — a strict "since local midnight" would use
    ``after:<epoch>``).
    """
    parts = ["in:inbox"]
    if unread_only:
        parts.append("is:unread")
    parts.append(f"newer_than:{int(days)}d")
    return " ".join(parts)


# Back-compat alias: the default (today's unread inbox) the sync used before Plan 40's filters.
TODAY_QUERY = build_inbox_query(unread_only=True, days=1)

_MAX_RETRIES = 2
_BACKOFF_BASE = 0.5  # seconds; exponential, only on 429/503


class GmailError(RuntimeError):
    """Gmail API returned an unexpected error."""


class GmailAuthError(GmailError):
    """The refresh/access token was rejected (revoked or expired) → user must reconnect."""


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    sender: str  # raw From header (may be "Name <email>")
    subject: str
    body: str
    received_at: datetime | None


def _as_dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _decode_b64url(data: str) -> str:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")


def _find_body(payload: dict[str, object], *, plain_only: bool) -> str:
    """Depth-first search for a body part. ``plain_only`` matches text/plain exactly;
    otherwise any text/* part."""
    mime = str(payload.get("mimeType", ""))
    data = _as_dict(payload.get("body")).get("data")
    matches = (mime == "text/plain") if plain_only else mime.startswith("text/")
    if matches and isinstance(data, str):
        return _decode_b64url(data)
    for part in _as_list(payload.get("parts")):
        text = _find_body(_as_dict(part), plain_only=plain_only)
        if text:
            return text
    return ""


def _extract_body(payload: dict[str, object]) -> str:
    """Prefer a text/plain part anywhere in the tree; fall back to any text/* part."""
    return _find_body(payload, plain_only=True) or _find_body(payload, plain_only=False)


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except TypeError, ValueError:
        return None


class GmailClient:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    async def refresh_access_token(self, http: httpx.AsyncClient, refresh_token: str) -> str:
        resp = await http.post(
            _GOOGLE_TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code == 400:
            # invalid_grant: the refresh token was revoked or expired.
            raise GmailAuthError("Gmail refresh token rejected — reconnect required")
        if resp.status_code != 200:
            raise GmailError(f"Token refresh failed: {resp.status_code}")
        token = str(resp.json().get("access_token", ""))
        if not token:
            raise GmailError("Token refresh returned no access_token")
        return token

    async def _get(
        self,
        http: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str | int] | None = None,
    ) -> dict[str, object]:
        for attempt in range(_MAX_RETRIES + 1):
            resp = await http.get(url, headers=headers, params=params)
            if resp.status_code in (429, 503) and attempt < _MAX_RETRIES:
                await asyncio.sleep(_BACKOFF_BASE * (2**attempt))
                continue
            if resp.status_code == 401:
                raise GmailAuthError("Gmail access token rejected")
            if resp.status_code != 200:
                raise GmailError(f"Gmail API error: {resp.status_code}")
            return resp.json()
        raise GmailError("Gmail API rate limited after retries")

    async def list_today(
        self,
        http: httpx.AsyncClient,
        access_token: str,
        query: str = TODAY_QUERY,
        max_results: int = 25,
        concurrency: int = 5,
    ) -> list[GmailMessage]:
        headers = {"Authorization": f"Bearer {access_token}"}
        listing = await self._get(
            http,
            _GMAIL_MESSAGES_URL,
            headers=headers,
            params={"q": query, "maxResults": max_results},
        )
        ids: list[str] = []
        for m in _as_list(listing.get("messages")):
            mid = _as_dict(m).get("id")
            if isinstance(mid, str):
                ids.append(mid)

        # Fetch the per-message bodies concurrently (bounded) — sequentially, dozens of
        # round trips add seconds that push a sync toward the edge timeout. Order is
        # preserved by gather; a failed fetch drops just that message.
        sem = asyncio.Semaphore(max(1, concurrency))

        async def _fetch(mid: str) -> GmailMessage | None:
            async with sem:
                try:
                    raw = await self._get(
                        http,
                        f"{_GMAIL_MESSAGES_URL}/{mid}",
                        headers=headers,
                        params={"format": "full"},
                    )
                except GmailError:
                    _log.warning("gmail.message_fetch_failed", message_id=mid)
                    return None
            return self.parse_message(raw)

        fetched = await asyncio.gather(*(_fetch(mid) for mid in ids))
        return [m for m in fetched if m is not None]

    @staticmethod
    def parse_message(raw: dict[str, object]) -> GmailMessage:
        payload = _as_dict(raw.get("payload"))
        headers: dict[str, str] = {}
        for h in _as_list(payload.get("headers")):
            hd = _as_dict(h)
            name, value = hd.get("name"), hd.get("value")
            if isinstance(name, str) and isinstance(value, str):
                headers[name.lower()] = value
        body = _extract_body(payload) or str(raw.get("snippet", ""))
        return GmailMessage(
            message_id=str(raw.get("id", "")),
            sender=headers.get("from", ""),
            subject=headers.get("subject", "(no subject)"),
            body=body,
            received_at=_parse_date(headers.get("date")),
        )
