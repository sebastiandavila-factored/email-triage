"""Business rules for per-workspace triage configuration (Triage Studio F1).

Repos do SQL; this service does the *rules* — reserved/immutable slugs, slug
format, uniqueness, and the last-active-category guard. Methods take primitives
(ids, strings), never web types, so the service stays transport-agnostic; the
router maps ``TriageConfigError`` → ``HTTPException`` (same pattern as
``WorkspaceService``).
"""

from __future__ import annotations

import re
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from email_triage.db.models import Category
from email_triage.db.repos.categories import CategoryRepo

_log = structlog.get_logger()

# Reserved: the prompt compiler (F2) always adds an implicit "unknown" escape
# category, so a tenant must never define one that would collide with it.
RESERVED_SLUGS: frozenset[str] = frozenset({"unknown"})

_SLUG_RE = re.compile(r"^[a-z0-9_]{1,50}$")

# Frozen snapshot of the pre-F1 taxonomy. Mirrors LEGACY_CATEGORIES in migration
# 0004: the migration seeds *existing* tenants, this seeds *new* workspaces.
DEFAULT_CATEGORIES: list[tuple[str, str, str]] = [
    ("status", "Order status", "Question about the status of an order"),
    ("refunds", "Refunds", "Question about refund eligibility or process"),
    ("availability", "Availability", "Question about product availability or stock"),
    ("shipments", "Shipments", "Question about shipping times, costs or methods"),
    ("prices", "Prices", "Question about prices, discounts or promotions"),
]


class TriageConfigError(Exception):
    """A business-rule violation, carrying the HTTP status the router should use."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class TriageConfigService:
    def __init__(self) -> None:
        self.categories = CategoryRepo()

    async def seed_defaults(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        """Seed a brand-new workspace with the legacy taxonomy. Idempotent: does
        nothing if the tenant already has any category."""
        existing = await self.categories.list_for_tenant(session, tenant_id)
        if existing:
            return
        for order, (slug, name, description) in enumerate(DEFAULT_CATEGORIES):
            await self.categories.create(session, tenant_id, slug, name, description, order)
        _log.info("triage_config.seeded", tenant_id=str(tenant_id), n=len(DEFAULT_CATEGORIES))

    async def list_categories(
        self, session: AsyncSession, tenant_id: uuid.UUID, active_only: bool = False
    ) -> list[Category]:
        return await self.categories.list_for_tenant(session, tenant_id, active_only=active_only)

    async def create_category(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        slug: str,
        name: str,
        description: str,
    ) -> Category:
        slug = slug.strip().lower()
        self._validate_slug(slug)
        if await self.categories.get_by_slug(session, tenant_id, slug) is not None:
            raise TriageConfigError(409, f"A category with slug '{slug}' already exists")
        sort_order = await self.categories.max_sort_order(session, tenant_id) + 1
        return await self.categories.create(
            session, tenant_id, slug, name.strip(), description.strip(), sort_order
        )

    async def update_category(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        category_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        sort_order: int | None = None,
    ) -> Category:
        """Edit display/prompt copy or activation. The slug is immutable — it is
        the classification value written to logs/evals, so renaming would corrupt
        history. To rename, create a new category and deactivate the old one."""
        category = await self.categories.get(session, tenant_id, category_id)
        if category is None:
            raise TriageConfigError(404, "Category not found")

        # Deactivating: never leave the tenant with zero active categories.
        if (
            is_active is False
            and category.is_active
            and await self.categories.count_active(session, tenant_id, exclude_id=category_id) == 0
        ):
            raise TriageConfigError(409, "Cannot deactivate the last active category")

        if name is not None:
            category.name = name.strip()
        if description is not None:
            category.description = description.strip()
        if is_active is not None:
            category.is_active = is_active
        if sort_order is not None:
            category.sort_order = sort_order

        await session.flush()
        _log.info("category.updated", tenant_id=str(tenant_id), slug=category.slug)
        return category

    async def delete_category(
        self, session: AsyncSession, tenant_id: uuid.UUID, category_id: uuid.UUID
    ) -> None:
        category = await self.categories.get(session, tenant_id, category_id)
        if category is None:
            raise TriageConfigError(404, "Category not found")
        # Never delete the last active category out from under the tenant.
        if (
            category.is_active
            and await self.categories.count_active(session, tenant_id, exclude_id=category_id) == 0
        ):
            raise TriageConfigError(409, "Cannot delete the last active category")
        await self.categories.delete(session, category)
        _log.info("category.deleted", tenant_id=str(tenant_id), slug=category.slug)

    @staticmethod
    def _validate_slug(slug: str) -> None:
        if slug in RESERVED_SLUGS:
            raise TriageConfigError(422, f"'{slug}' is a reserved slug")
        if not _SLUG_RE.match(slug):
            raise TriageConfigError(
                422, "slug must match ^[a-z0-9_]{1,50}$ (lowercase letters, digits, underscore)"
            )
