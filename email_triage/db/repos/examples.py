from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.db.models import Category, TriageExample
from email_triage.services.prompt_compiler import ExampleSpec

_log = structlog.get_logger()


class ExampleRepo:
    """SQL for per-category few-shot examples. Rules live in TriageConfigService."""

    async def get(
        self, session: AsyncSession, tenant_id: uuid.UUID, example_id: uuid.UUID
    ) -> TriageExample | None:
        return await session.scalar(
            select(TriageExample).where(
                TriageExample.id == example_id, TriageExample.tenant_id == tenant_id
            )
        )

    async def list_for_category(
        self, session: AsyncSession, tenant_id: uuid.UUID, category_id: uuid.UUID
    ) -> list[TriageExample]:
        stmt = (
            select(TriageExample)
            .where(
                TriageExample.tenant_id == tenant_id,
                TriageExample.category_id == category_id,
            )
            .order_by(TriageExample.created_at)
        )
        return list((await session.scalars(stmt)).all())

    async def count_for_category(
        self, session: AsyncSession, tenant_id: uuid.UUID, category_id: uuid.UUID
    ) -> int:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(TriageExample)
                .where(
                    TriageExample.tenant_id == tenant_id,
                    TriageExample.category_id == category_id,
                )
            )
            or 0
        )

    async def active_specs(self, session: AsyncSession, tenant_id: uuid.UUID) -> list[ExampleSpec]:
        """Examples whose category is active, projected for the prompt compiler.
        Ordered by the category's sort_order so the few-shot block is stable."""
        stmt = (
            select(TriageExample, Category.slug)
            .join(Category, Category.id == TriageExample.category_id)
            .where(
                TriageExample.tenant_id == tenant_id,
                Category.is_active.is_(True),
            )
            .order_by(Category.sort_order, TriageExample.created_at)
        )
        rows = await session.execute(stmt)
        return [
            ExampleSpec(
                category_slug=slug,
                kind=ex.kind,
                subject=ex.subject,
                body=ex.body,
                expected_reply=ex.expected_reply,
            )
            for ex, slug in rows.all()
        ]

    async def create(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        category_id: uuid.UUID,
        kind: str,
        subject: str,
        body: str,
        expected_reply: str | None,
        created_by: uuid.UUID | None,
    ) -> TriageExample:
        example = TriageExample(
            tenant_id=tenant_id,
            category_id=category_id,
            kind=kind,
            subject=subject,
            body=body,
            expected_reply=expected_reply,
            created_by=created_by,
        )
        session.add(example)
        await session.flush()
        _log.info("example.created", tenant_id=str(tenant_id), kind=kind)
        return example

    async def delete(self, session: AsyncSession, example: TriageExample) -> None:
        await session.delete(example)
        await session.flush()
