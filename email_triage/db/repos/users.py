from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
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
