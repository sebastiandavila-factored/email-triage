"""categories table (Triage Studio F1)

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-01 00:00:00.000000

Moves triage categories out of the frozen ``schemas.Category`` StrEnum and into a
per-tenant table. Seeds every *existing* tenant with the five legacy categories so
no workspace ends up with an empty taxonomy after the migration. New workspaces are
seeded in code (``TriageConfigService.seed_defaults``), not here.

The seed is idempotent: a tenant that already has categories is skipped, so
re-running the data step never duplicates rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen snapshot of the pre-F1 taxonomy. Duplicated in
# ``services/triage_config.py`` on purpose: a migration must be self-contained and
# must not import app code that may drift after this revision is written.
LEGACY_CATEGORIES: list[tuple[str, str, str]] = [
    ("status", "Order status", "Question about the status of an order"),
    ("refunds", "Refunds", "Question about refund eligibility or process"),
    ("availability", "Availability", "Question about product availability or stock"),
    ("shipments", "Shipments", "Question about shipping times, costs or methods"),
    ("prices", "Prices", "Question about prices, discounts or promotions"),
]


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_categories_tenant_slug"),
    )
    op.create_index("ix_categories_tenant_id", "categories", ["tenant_id"])
    _seed_existing_tenants()


def _seed_existing_tenants() -> None:
    bind = op.get_bind()
    tenant_ids = bind.execute(sa.text("SELECT id FROM tenants")).scalars().all()
    insert = sa.text(
        "INSERT INTO categories "
        "(id, tenant_id, slug, name, description, is_active, sort_order) "
        "VALUES (:id, :tenant_id, :slug, :name, :description, true, :sort_order)"
    )
    for tenant_id in tenant_ids:
        already = bind.execute(
            sa.text("SELECT COUNT(*) FROM categories WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        ).scalar()
        if already:
            continue  # idempotent: never double-seed
        for order, (slug, name, description) in enumerate(LEGACY_CATEGORIES):
            bind.execute(
                insert,
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "slug": slug,
                    "name": name,
                    "description": description,
                    "sort_order": order,
                },
            )


def downgrade() -> None:
    op.drop_index("ix_categories_tenant_id", table_name="categories")
    op.drop_table("categories")
