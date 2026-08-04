from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.db.models import Category

_log = structlog.get_logger()


class CategoryRepo:
    """SQL for per-workspace triage categories. Rules live in TriageConfigService."""

    async def get(
        self, session: AsyncSession, tenant_id: uuid.UUID, category_id: uuid.UUID
    ) -> Category | None:
        """Fetch scoped by tenant. Filtering by tenant_id here means a category of
        another tenant reads as *not found* (404), never leaking existence."""
        return await session.scalar(
            select(Category).where(Category.id == category_id, Category.tenant_id == tenant_id)
        )

    async def get_by_slug(
        self, session: AsyncSession, tenant_id: uuid.UUID, slug: str
    ) -> Category | None:
        return await session.scalar(
            select(Category).where(Category.tenant_id == tenant_id, Category.slug == slug)
        )

    async def list_for_tenant(
        self, session: AsyncSession, tenant_id: uuid.UUID, active_only: bool = False
    ) -> list[Category]:
        stmt = select(Category).where(Category.tenant_id == tenant_id)
        if active_only:
            stmt = stmt.where(Category.is_active.is_(True))
        stmt = stmt.order_by(Category.sort_order, Category.created_at)
        return list((await session.scalars(stmt)).all())

    async def count_active(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        exclude_id: uuid.UUID | None = None,
    ) -> int:
        """Active categories in the tenant, optionally excluding one row. Used to
        protect the last active category (deactivate/delete guard)."""
        stmt = (
            select(func.count())
            .select_from(Category)
            .where(Category.tenant_id == tenant_id, Category.is_active.is_(True))
        )
        if exclude_id is not None:
            stmt = stmt.where(Category.id != exclude_id)
        return int(await session.scalar(stmt) or 0)

    async def create(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        slug: str,
        name: str,
        description: str,
        sort_order: int,
    ) -> Category:
        category = Category(
            tenant_id=tenant_id,
            slug=slug,
            name=name,
            description=description,
            sort_order=sort_order,
        )
        session.add(category)
        await session.flush()
        _log.info("category.created", tenant_id=str(tenant_id), slug=slug)
        return category

    async def max_sort_order(self, session: AsyncSession, tenant_id: uuid.UUID) -> int:
        result = await session.scalar(
            select(func.max(Category.sort_order)).where(Category.tenant_id == tenant_id)
        )
        return int(result) if result is not None else -1

    async def delete(self, session: AsyncSession, category: Category) -> None:
        await session.delete(category)
        await session.flush()
