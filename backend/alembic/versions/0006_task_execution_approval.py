"""Add durable founder-reviewed task executions.

Revision ID: 0006_task_execution_approval
Revises: 0005_task_lifecycle_and_concurrency
Create Date: 2026-11-15 16:45:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006_task_execution_approval"
down_revision: Union[str, None] = "0005_task_lifecycle_and_concurrency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_executions",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("task_id", sa.String(length=64), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(length=64), sa.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("artifacts_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=80), nullable=False, server_default="founder"),
        sa.Column("approved_by", sa.String(length=80), nullable=True),
        sa.Column("rejection_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.String(length=40), nullable=True),
        sa.Column("finished_at", sa.String(length=40), nullable=True),
        sa.Column("approved_at", sa.String(length=40), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_approval', 'approved', 'rejected', 'failed', 'cancelled')",
            name="check_task_execution_status",
        ),
    )
    op.create_index("idx_task_executions_task_created", "task_executions", ["task_id", "created_at"], unique=False)
    op.create_index("idx_task_executions_status_created", "task_executions", ["status", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_task_executions_status_created", table_name="task_executions")
    op.drop_index("idx_task_executions_task_created", table_name="task_executions")
    op.drop_table("task_executions")
