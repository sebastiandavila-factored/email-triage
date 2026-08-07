from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.db.models import GmailConnection

_log = structlog.get_logger()


class GmailRepo:
    """Persistence for per-user Gmail connections (Plan 36).

    One connection per ``(tenant_id, user_id)`` in v1 (enforced by a unique
    constraint); reconnecting upserts the encrypted refresh token in place.
    """

    async def get_by_user(
        self, session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> GmailConnection | None:
        return await session.scalar(
            select(GmailConnection).where(
                GmailConnection.tenant_id == tenant_id,
                GmailConnection.user_id == user_id,
            )
        )

    async def upsert(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        google_email: str,
        refresh_token_enc: str,
        scopes: str,
    ) -> GmailConnection:
        conn = await self.get_by_user(session, tenant_id, user_id)
        if conn is None:
            conn = GmailConnection(
                tenant_id=tenant_id,
                user_id=user_id,
                google_email=google_email,
                refresh_token_enc=refresh_token_enc,
                scopes=scopes,
            )
            session.add(conn)
        else:
            # Reconnect: refresh the stored credential and re-stamp connected_at.
            conn.google_email = google_email
            conn.refresh_token_enc = refresh_token_enc
            conn.scopes = scopes
            conn.connected_at = datetime.now(UTC)
        await session.flush()
        _log.info("gmail.connection_upserted", tenant_id=str(tenant_id), email=google_email)
        return conn

    async def touch_last_synced(
        self, session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        """Stamp the last successful sync (Plan 37)."""
        conn = await self.get_by_user(session, tenant_id, user_id)
        if conn is not None:
            conn.last_synced_at = datetime.now(UTC)
            await session.flush()

    async def delete(self, session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        conn = await self.get_by_user(session, tenant_id, user_id)
        if conn is None:
            return False
        await session.delete(conn)
        await session.flush()
        _log.info("gmail.connection_deleted", tenant_id=str(tenant_id))
        return True
