"""passports

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("group_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_passports_tenant_id_tenants"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_passports_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_passports"),
        sa.UniqueConstraint("tenant_id", "user_id", "version", name="uq_passport"),
    )
    op.create_index("ix_passports_tenant_id", "passports", ["tenant_id"])
    op.create_index("ix_passports_user_id", "passports", ["user_id"])


def downgrade() -> None:
    op.drop_table("passports")
