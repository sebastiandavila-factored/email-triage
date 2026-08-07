"""gmail_connections (Gmail Ingestion F1, Plan 36)

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07 00:00:00.000000

Adds a per-user Gmail connection table storing the OAuth refresh token **encrypted
at rest** (Fernet). Pure schema — no data backfill; workspaces start with no
connection, which is exactly the "not connected" state the API reports.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gmail_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("google_email", sa.String(255), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_gmail_connections_tenant_user"),
    )
    op.create_index("ix_gmail_connections_tenant_id", "gmail_connections", ["tenant_id"])
    op.create_index("ix_gmail_connections_user_id", "gmail_connections", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_gmail_connections_user_id", table_name="gmail_connections")
    op.drop_index("ix_gmail_connections_tenant_id", table_name="gmail_connections")
    op.drop_table("gmail_connections")
