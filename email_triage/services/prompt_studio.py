"""Draft → preview → publish workflow for the tenant prompt (Triage Studio F3).

Repos do SQL; this service does the *rules*: example limits, draft compilation,
the publish eval-gate (block a regression), and rollback. The eval-gate is
injectable (``PromptGate``) so tests never touch the LLM; production may wire a
real classification gate or leave it None (versioned publish without evaluation).

Governance model ("published wins if present"): a tenant with no active version
keeps F2 live-compile; publishing freezes an immutable ``PromptVersion`` that
``deps.get_triage_service`` serves until the next publish or rollback.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.db.models import PromptVersion, TriageExample
from email_triage.db.repos.categories import CategoryRepo
from email_triage.db.repos.examples import ExampleRepo
from email_triage.db.repos.prompts import PromptTemplateRepo, PromptVersionRepo
from email_triage.services.prompt_compiler import (
    UNKNOWN_SLUG,
    CategorySpec,
    TemplateOverrides,
    compile_system_prompt,
)

_log = structlog.get_logger()

_EXAMPLE_KINDS = frozenset({"positive", "negative"})
MAX_EXAMPLES_PER_CATEGORY = 20
# A new version may not regress accuracy/macro_f1 below the active one by more than this.
GATE_MARGIN = 0.02


@dataclass(frozen=True)
class GateMetrics:
    accuracy: float
    macro_f1: float


# Evaluate a compiled prompt (given its allowed slugs) and return quality metrics.
PromptGate = Callable[[str, frozenset[str]], Awaitable[GateMetrics]]


class PromptStudioError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class CompiledDraft:
    prompt: str
    allowed_slugs: frozenset[str]


class PromptStudioService:
    def __init__(self, gate: PromptGate | None = None) -> None:
        self.gate = gate
        self.categories = CategoryRepo()
        self.examples = ExampleRepo()
        self.templates = PromptTemplateRepo()
        self.versions = PromptVersionRepo()

    # ── examples ────────────────────────────────────────────────────────────────

    async def add_example(
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
        if kind not in _EXAMPLE_KINDS:
            raise PromptStudioError(422, "kind must be 'positive' or 'negative'")
        category = await self.categories.get(session, tenant_id, category_id)
        if category is None:
            raise PromptStudioError(404, "Category not found")
        if (
            await self.examples.count_for_category(session, tenant_id, category_id)
            >= MAX_EXAMPLES_PER_CATEGORY
        ):
            raise PromptStudioError(
                409, f"At most {MAX_EXAMPLES_PER_CATEGORY} examples per category"
            )
        return await self.examples.create(
            session,
            tenant_id,
            category_id,
            kind,
            subject.strip(),
            body.strip(),
            expected_reply.strip() if expected_reply else None,
            created_by,
        )

    async def list_examples(
        self, session: AsyncSession, tenant_id: uuid.UUID, category_id: uuid.UUID
    ) -> list[TriageExample]:
        return await self.examples.list_for_category(session, tenant_id, category_id)

    async def delete_example(
        self, session: AsyncSession, tenant_id: uuid.UUID, example_id: uuid.UUID
    ) -> None:
        example = await self.examples.get(session, tenant_id, example_id)
        if example is None:
            raise PromptStudioError(404, "Example not found")
        await self.examples.delete(session, example)

    # ── draft ───────────────────────────────────────────────────────────────────

    async def get_draft_overrides(
        self, session: AsyncSession, tenant_id: uuid.UUID
    ) -> TemplateOverrides:
        template = await self.templates.get(session, tenant_id)
        if template is None:
            return TemplateOverrides()
        return TemplateOverrides(
            role=template.role_block,
            task=template.task_block,
            guardrails=template.guardrails_block,
            tone=template.tone,
        )

    async def save_draft(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        overrides: TemplateOverrides,
        updated_by: uuid.UUID | None,
    ) -> None:
        await self.templates.upsert(
            session,
            tenant_id,
            role_block=overrides.role,
            task_block=overrides.task,
            guardrails_block=overrides.guardrails,
            tone=overrides.tone,
            updated_by=updated_by,
        )

    async def compile_draft(self, session: AsyncSession, tenant_id: uuid.UUID) -> CompiledDraft:
        """Compile the tenant's current draft (active categories + their examples +
        template overrides). Used by preview and publish."""
        rows = await self.categories.list_for_tenant(session, tenant_id, active_only=True)
        if not rows:
            raise PromptStudioError(409, "Publish requires at least one active category")
        specs = [CategorySpec(slug=r.slug, name=r.name, description=r.description) for r in rows]
        examples = await self.examples.active_specs(session, tenant_id)
        overrides = await self.get_draft_overrides(session, tenant_id)
        prompt = compile_system_prompt(specs, examples=examples, overrides=overrides)
        slugs = frozenset(s.slug for s in specs) | {UNKNOWN_SLUG}
        return CompiledDraft(prompt=prompt, allowed_slugs=slugs)

    # ── publish / rollback ──────────────────────────────────────────────────────

    async def publish(
        self, session: AsyncSession, tenant_id: uuid.UUID, publisher_id: uuid.UUID | None
    ) -> PromptVersion:
        draft = await self.compile_draft(session, tenant_id)

        metrics: GateMetrics | None = None
        if self.gate is not None:
            metrics = await self.gate(draft.prompt, draft.allowed_slugs)
            active = await self.versions.active(session, tenant_id)
            if (
                active is not None
                and active.accuracy is not None
                and active.macro_f1 is not None
                and (
                    metrics.accuracy < active.accuracy - GATE_MARGIN
                    or metrics.macro_f1 < active.macro_f1 - GATE_MARGIN
                )
            ):
                raise PromptStudioError(
                    409,
                    "Eval-gate failed: "
                    f"accuracy {metrics.accuracy:.3f} vs baseline {active.accuracy:.3f}, "
                    f"macro_f1 {metrics.macro_f1:.3f} vs baseline {active.macro_f1:.3f}",
                )

        version = await self.versions.next_version(session, tenant_id)
        return await self.versions.create_active(
            session,
            tenant_id,
            version,
            compiled_prompt=draft.prompt,
            allowed_slugs=json.dumps(sorted(draft.allowed_slugs)),
            accuracy=metrics.accuracy if metrics else None,
            macro_f1=metrics.macro_f1 if metrics else None,
            published_by=publisher_id,
        )

    async def rollback(
        self, session: AsyncSession, tenant_id: uuid.UUID, version: int
    ) -> PromptVersion:
        row = await self.versions.get_by_version(session, tenant_id, version)
        if row is None:
            raise PromptStudioError(404, "Version not found")
        await self.versions.activate(session, tenant_id, row)
        return row
