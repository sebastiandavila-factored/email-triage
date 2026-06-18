from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.db.models import Membership, User

_log = structlog.get_logger()


class UserRepo:
    async def get_by_email(self, session: AsyncSession, email: str) -> User | None:
        return await session.scalar(select(User).where(User.email == email))

    async def get_by_google_sub(self, session: AsyncSession, google_sub: str) -> User | None:
        return await session.scalar(select(User).where(User.google_sub == google_sub))

    async def get_membership(self, session: AsyncSession, user_id: uuid.UUID) -> Membership | None:
        return await session.scalar(select(Membership).where(Membership.user_id == user_id))

    async def get_membership_in(
        self, session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Membership | None:
        """Membership of a user in a specific workspace. Used for per-workspace
        RBAC: resolving the role here also proves the user belongs to the tenant
        (object-level authorization / anti-IDOR)."""
        return await session.scalar(
            select(Membership).where(
                Membership.user_id == user_id, Membership.tenant_id == tenant_id
            )
        )

    async def list_members(
        self, session: AsyncSession, tenant_id: uuid.UUID
    ) -> list[tuple[User, str]]:
        rows = await session.execute(
            select(User, Membership.role)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.tenant_id == tenant_id)
            .order_by(Membership.created_at)
        )
        return [(u, role) for u, role in rows.all()]

    async def count_owners(self, session: AsyncSession, tenant_id: uuid.UUID) -> int:
        result = await session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.tenant_id == tenant_id, Membership.role == "owner")
        )
        return int(result or 0)

    async def delete_membership(
        self, session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> None:
        membership = await self.get_membership_in(session, user_id, tenant_id)
        if membership is not None:
            await session.delete(membership)
            await session.flush()

    async def create_with_password(
        self,
        session: AsyncSession,
        email: str,
        display_name: str,
        password_hash: str,
    ) -> User:
        user = User(
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            email_verified=False,
        )
        session.add(user)
        await session.flush()
        _log.info("user.created", email=email, method="password")
        return user

    async def create_from_google(
        self,
        session: AsyncSession,
        google_sub: str,
        email: str,
        display_name: str,
        email_verified: bool = False,
    ) -> User:
        user = User(
            google_sub=google_sub,
            email=email,
            display_name=display_name,
            email_verified=email_verified,
        )
        session.add(user)
        await session.flush()
        _log.info("user.created", email=email, method="google")
        return user
