"""skill versions

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("version", sa.String(8), nullable=False),
        sa.Column("branch", sa.String(24), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("origin", sa.String(8), nullable=False),
        sa.Column("skill_md", sa.Text(), nullable=False),
        sa.Column("test_yaml", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_skill_versions_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_skill_versions"),
        sa.UniqueConstraint("tenant_id", "slug", "version", name="uq_skill_version"),
    )
    op.create_index("ix_skill_versions_tenant_id", "skill_versions", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("skill_versions")
