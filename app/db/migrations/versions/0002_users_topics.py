"""users and topics

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("first_name", sa.String(256), nullable=False),
        sa.Column("last_name", sa.String(256), nullable=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("language_code", sa.String(16), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("dm_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("dm_topics_supported", sa.Boolean(), nullable=True),
        sa.Column("active_context", sa.String(24), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_users_tenant_id_tenants"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("tenant_id", "tg_id", name="uq_users_tenant_tg"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_topics_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_topics_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_topics"),
        sa.UniqueConstraint("tenant_id", "user_id", "kind", name="uq_topics_user_kind"),
    )
    op.create_index("ix_topics_tenant_id", "topics", ["tenant_id"])
    op.create_index("ix_topics_user_id", "topics", ["user_id"])


def downgrade() -> None:
    op.drop_table("topics")
    op.drop_table("users")
