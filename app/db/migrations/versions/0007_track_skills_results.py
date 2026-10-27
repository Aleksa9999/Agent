"""user skills and first results

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_skills",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("version", sa.String(8), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_user_skills_tenant_id_tenants"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_skills_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_user_skills"),
        sa.UniqueConstraint("tenant_id", "user_id", "slug", name="uq_user_skill"),
    )
    op.create_index("ix_user_skills_tenant_id", "user_skills", ["tenant_id"])
    op.create_index("ix_user_skills_user_id", "user_skills", ["user_id"])
    op.create_table(
        "first_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("passport_version", sa.Integer(), nullable=False),
        sa.Column("track", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_first_results_tenant_id_tenants"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_first_results_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_first_results"),
        sa.UniqueConstraint("tenant_id", "user_id", "passport_version", name="uq_first_result"),
    )
    op.create_index("ix_first_results_tenant_id", "first_results", ["tenant_id"])
    op.create_index("ix_first_results_user_id", "first_results", ["user_id"])


def downgrade() -> None:
    op.drop_table("first_results")
    op.drop_table("user_skills")
