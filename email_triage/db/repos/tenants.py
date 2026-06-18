from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.db.models import Membership, Tenant

_log = structlog.get_logger()


class TenantRepo:
    async def get_by_id(self, session: AsyncSession, tenant_id: uuid.UUID) -> Tenant | None:
        return await session.scalar(select(Tenant).where(Tenant.id == tenant_id))

    async def create_personal(
        self,
        session: AsyncSession,
        name: str,
        api_key_hash: str | None = None,
    ) -> Tenant:
        """Create a personal workspace. The api_key_hash is usually set right
        after the flush, once the tenant id (embedded in the key) is known."""
        tenant = Tenant(name=name, type="personal", domain=None, api_key_hash=api_key_hash)
        session.add(tenant)
        await session.flush()
        _log.info("tenant.created", name=name, type="personal")
        return tenant

    async def create_team(self, session: AsyncSession, name: str) -> Tenant:
        tenant = Tenant(name=name, type="team", domain=None)
        session.add(tenant)
        await session.flush()
        _log.info("tenant.created", name=name, type="team")
        return tenant

    async def list_for_user(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> list[tuple[Tenant, str]]:
        rows = await session.execute(
            select(Tenant, Membership.role)
            .join(Membership, Membership.tenant_id == Tenant.id)
            .where(Membership.user_id == user_id)
            .order_by(Tenant.created_at)
        )
        return [(t, role) for t, role in rows.all()]

    async def delete(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        tenant = await self.get_by_id(session, tenant_id)
        if tenant is not None:
            await session.delete(tenant)
            await session.flush()

    async def add_member(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        role: str = "owner",
    ) -> Membership:
        membership = Membership(user_id=user_id, tenant_id=tenant_id, role=role)
        session.add(membership)
        await session.flush()
        return membership

    async def update_api_key_hash(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        new_hash: str,
    ) -> None:
        tenant = await self.get_by_id(session, tenant_id)
        if tenant is not None:
            tenant.api_key_hash = new_hash
            await session.flush()
