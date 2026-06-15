"""users and tenant refactor

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-08 00:00:00.000000

Separates User (person) from Tenant (workspace).
Every existing tenant row becomes a personal workspace
and its owner is migrated to the new users table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create users table
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("google_sub", sa.String(255), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("google_sub", name="uq_users_google_sub"),
    )

    # 2. Add new columns to tenants (nullable first, filled during migration)
    op.add_column("tenants", sa.Column("domain", sa.String(255), nullable=True))
    op.add_column("tenants", sa.Column("name", sa.String(255), nullable=True))
    op.add_column("tenants", sa.Column("type", sa.String(50), nullable=True))

    # 3. Create memberships table
    op.create_table(
        "memberships",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="owner"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "tenant_id"),
    )

    # 4. Migrate existing tenant rows → users + memberships
    #    Preserve the existing tenant UUIDs so triage_logs FK stays valid.
    op.execute("""
        INSERT INTO users
            (id, email, display_name, google_sub, email_verified, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            email,
            COALESCE(display_name, split_part(email, '@', 1)),
            google_sub,
            (google_sub IS NOT NULL),
            created_at,
            now()
        FROM tenants
    """)

    op.execute("""
        INSERT INTO memberships (user_id, tenant_id, role, created_at)
        SELECT u.id, t.id, 'owner', now()
        FROM tenants t
        JOIN users u ON u.email = t.email
    """)

    # 5. Populate tenants.name and tenants.type from existing columns
    op.execute("""
        UPDATE tenants
        SET
            name = COALESCE(display_name, split_part(email, '@', 1)),
            type = 'personal',
            domain = NULL
    """)

    # 6. Make name and type NOT NULL now that every row has a value
    op.alter_column("tenants", "name", nullable=False)
    op.alter_column("tenants", "type", nullable=False, server_default="personal")

    # 7. Make api_key_hash nullable (was NOT NULL in 0001)
    op.alter_column("tenants", "api_key_hash", nullable=True)

    # 8. Drop old unique constraints and columns
    op.execute("ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_email_key")
    op.execute("ALTER TABLE tenants DROP CONSTRAINT IF EXISTS tenants_google_sub_key")
    op.drop_column("tenants", "email")
    op.drop_column("tenants", "google_sub")
    op.drop_column("tenants", "display_name")

    # 9. Add unique index on domain (NULLs are not considered equal, so multiple NULLs allowed)
    op.create_unique_constraint("uq_tenants_domain", "tenants", ["domain"])


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade from 0002 is not supported. Restore from a database backup."
    )
