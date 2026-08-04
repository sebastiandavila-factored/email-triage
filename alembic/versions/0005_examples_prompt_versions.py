"""triage_examples, prompt_templates, prompt_versions (Triage Studio F3)

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-01 00:00:00.000000

Adds few-shot examples per category, a per-tenant mutable prompt-template draft, and
immutable published prompt versions (publish / eval-gate / rollback). Pure schema —
no data backfill; tenants start with no examples, no draft overrides, and no published
version, which is exactly the F2 live-compile behaviour.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "triage_examples",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False, server_default="positive"),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("expected_reply", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_triage_examples_tenant_id", "triage_examples", ["tenant_id"])
    op.create_index("ix_triage_examples_category_id", "triage_examples", ["category_id"])

    op.create_table(
        "prompt_templates",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_block", sa.Text(), nullable=True),
        sa.Column("task_block", sa.Text(), nullable=True),
        sa.Column("guardrails_block", sa.Text(), nullable=True),
        sa.Column("tone", sa.Text(), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("tenant_id"),
    )

    op.create_table(
        "prompt_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("compiled_prompt", sa.Text(), nullable=False),
        sa.Column("allowed_slugs", sa.Text(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("macro_f1", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "version", name="uq_prompt_versions_tenant_v"),
    )
    op.create_index("ix_prompt_versions_tenant_id", "prompt_versions", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_prompt_versions_tenant_id", table_name="prompt_versions")
    op.drop_table("prompt_versions")
    op.drop_table("prompt_templates")
    op.drop_index("ix_triage_examples_category_id", table_name="triage_examples")
    op.drop_index("ix_triage_examples_tenant_id", table_name="triage_examples")
    op.drop_table("triage_examples")
