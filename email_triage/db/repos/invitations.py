from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.db.models import Invitation


class InvitationRepo:
    async def create(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        email: str,
        role: str,
        token_hash: str,
        invited_by: uuid.UUID,
        expires_at: datetime,
    ) -> Invitation:
        invitation = Invitation(
            tenant_id=tenant_id,
            email=email,
            role=role,
            token_hash=token_hash,
            invited_by=invited_by,
            expires_at=expires_at,
            status="pending",
        )
        session.add(invitation)
        await session.flush()
        return invitation

    async def get_by_token_hash(self, session: AsyncSession, token_hash: str) -> Invitation | None:
        return await session.scalar(select(Invitation).where(Invitation.token_hash == token_hash))

    async def get_pending_for_email(
        self, session: AsyncSession, tenant_id: uuid.UUID, email: str
    ) -> Invitation | None:
        return await session.scalar(
            select(Invitation).where(
                Invitation.tenant_id == tenant_id,
                Invitation.email == email,
                Invitation.status == "pending",
            )
        )

    async def list_pending(self, session: AsyncSession, tenant_id: uuid.UUID) -> list[Invitation]:
        rows = await session.scalars(
            select(Invitation).where(
                Invitation.tenant_id == tenant_id, Invitation.status == "pending"
            )
        )
        return list(rows.all())

    async def get_by_id(self, session: AsyncSession, invitation_id: uuid.UUID) -> Invitation | None:
        return await session.scalar(select(Invitation).where(Invitation.id == invitation_id))

    async def set_status(
        self,
        session: AsyncSession,
        invitation: Invitation,
        status: str,
        accepted_at: datetime | None = None,
    ) -> None:
        invitation.status = status
        if accepted_at is not None:
            invitation.accepted_at = accepted_at
        await session.flush()
