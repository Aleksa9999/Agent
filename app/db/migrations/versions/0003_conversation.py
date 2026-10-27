"""messages, session summaries, pending questions

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("context_key", sa.String(24), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_messages_tenant_id_tenants"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_messages_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.create_index("ix_messages_user_context", "messages", ["user_id", "context_key", "id"])
    op.create_table(
        "session_summaries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("context_key", sa.String(24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("upto_message_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_session_summaries_tenant_id_tenants"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_session_summaries_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_session_summaries"),
        sa.UniqueConstraint("tenant_id", "user_id", "context_key", name="uq_summaries_context"),
    )
    op.create_index("ix_session_summaries_tenant_id", "session_summaries", ["tenant_id"])
    op.create_table(
        "pending_questions",
        sa.Column("id", sa.String(16), nullable=False),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("context_key", sa.String(24), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_pending_questions_tenant_id_tenants"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_pending_questions_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pending_questions"),
    )
    op.create_index("ix_pending_questions_tenant_id", "pending_questions", ["tenant_id"])
    op.create_index("ix_pending_questions_user_id", "pending_questions", ["user_id"])


def downgrade() -> None:
    op.drop_table("pending_questions")
    op.drop_table("session_summaries")
    op.drop_table("messages")
