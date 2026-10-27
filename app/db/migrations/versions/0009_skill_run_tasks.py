"""skill runs: tasks and the prompt pack

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skill_runs", sa.Column("tasks", sa.JSON(), nullable=True))
    op.add_column("skill_runs", sa.Column("tasks_text", sa.Text(), nullable=True))
    op.add_column(
        "skill_runs",
        sa.Column("tasks_status", sa.String(10), nullable=False, server_default="none"),
    )
    op.add_column(
        "skill_runs", sa.Column("tasks_rev", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("skill_runs", sa.Column("pack_text", sa.Text(), nullable=True))


def downgrade() -> None:
    for column in ("pack_text", "tasks_rev", "tasks_status", "tasks_text", "tasks"):
        op.drop_column("skill_runs", column)
