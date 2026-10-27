"""skill runs

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("version", sa.String(8), nullable=False),
        sa.Column("road", sa.String(8), nullable=True),
        sa.Column("phase", sa.String(12), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("decisions", sa.JSON(), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=True),
        sa.Column("spec_text", sa.Text(), nullable=True),
        sa.Column("spec_status", sa.String(10), nullable=False),
        sa.Column("spec_rev", sa.Integer(), nullable=False),
        sa.Column("batch_asked", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_skill_runs_tenant_id_tenants"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_skill_runs_user_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_skill_runs"),
    )
    op.create_index("ix_skill_runs_tenant_id", "skill_runs", ["tenant_id"])
    op.create_index("ix_skill_runs_user_id", "skill_runs", ["user_id"])


def downgrade() -> None:
    op.drop_table("skill_runs")
