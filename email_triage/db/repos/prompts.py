from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.db.models import PromptTemplate, PromptVersion

_log = structlog.get_logger()


class PromptTemplateRepo:
    async def get(self, session: AsyncSession, tenant_id: uuid.UUID) -> PromptTemplate | None:
        return await session.scalar(
            select(PromptTemplate).where(PromptTemplate.tenant_id == tenant_id)
        )

    async def upsert(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        role_block: str | None,
        task_block: str | None,
        guardrails_block: str | None,
        tone: str | None,
        updated_by: uuid.UUID | None,
    ) -> PromptTemplate:
        template = await self.get(session, tenant_id)
        if template is None:
            template = PromptTemplate(tenant_id=tenant_id)
            session.add(template)
        template.role_block = role_block
        template.task_block = task_block
        template.guardrails_block = guardrails_block
        template.tone = tone
        template.updated_by = updated_by
        await session.flush()
        return template


class PromptVersionRepo:
    async def active(self, session: AsyncSession, tenant_id: uuid.UUID) -> PromptVersion | None:
        return await session.scalar(
            select(PromptVersion).where(
                PromptVersion.tenant_id == tenant_id, PromptVersion.is_active.is_(True)
            )
        )

    async def get_by_version(
        self, session: AsyncSession, tenant_id: uuid.UUID, version: int
    ) -> PromptVersion | None:
        return await session.scalar(
            select(PromptVersion).where(
                PromptVersion.tenant_id == tenant_id, PromptVersion.version == version
            )
        )

    async def list_for_tenant(
        self, session: AsyncSession, tenant_id: uuid.UUID
    ) -> list[PromptVersion]:
        stmt = (
            select(PromptVersion)
            .where(PromptVersion.tenant_id == tenant_id)
            .order_by(PromptVersion.version.desc())
        )
        return list((await session.scalars(stmt)).all())

    async def next_version(self, session: AsyncSession, tenant_id: uuid.UUID) -> int:
        current = await session.scalar(
            select(func.max(PromptVersion.version)).where(PromptVersion.tenant_id == tenant_id)
        )
        return int(current or 0) + 1

    async def create_active(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        version: int,
        compiled_prompt: str,
        allowed_slugs: str,
        accuracy: float | None,
        macro_f1: float | None,
        published_by: uuid.UUID | None,
    ) -> PromptVersion:
        await self._deactivate_all(session, tenant_id)
        row = PromptVersion(
            tenant_id=tenant_id,
            version=version,
            compiled_prompt=compiled_prompt,
            allowed_slugs=allowed_slugs,
            accuracy=accuracy,
            macro_f1=macro_f1,
            is_active=True,
            published_by=published_by,
        )
        session.add(row)
        await session.flush()
        _log.info("prompt_version.published", tenant_id=str(tenant_id), version=version)
        return row

    async def activate(
        self, session: AsyncSession, tenant_id: uuid.UUID, row: PromptVersion
    ) -> None:
        await self._deactivate_all(session, tenant_id)
        row.is_active = True
        await session.flush()
        _log.info("prompt_version.activated", tenant_id=str(tenant_id), version=row.version)

    async def _deactivate_all(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        await session.execute(
            update(PromptVersion)
            .where(PromptVersion.tenant_id == tenant_id, PromptVersion.is_active.is_(True))
            .values(is_active=False)
        )
