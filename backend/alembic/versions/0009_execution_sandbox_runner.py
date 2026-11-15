"""Add isolated repository runner metadata to task executions.

Revision ID: 0009_execution_sandbox_runner
Revises: 0008_task_execution_recovery
Create Date: 2026-11-15 20:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_execution_sandbox_runner"
down_revision: Union[str, None] = "0008_task_execution_recovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("task_executions", sa.Column("sandbox_branch", sa.String(length=255), nullable=True))
    op.add_column("task_executions", sa.Column("sandbox_commit_sha", sa.String(length=64), nullable=True))
    op.add_column("task_executions", sa.Column("sandbox_profile", sa.String(length=20), nullable=True))
    op.add_column(
        "task_executions",
        sa.Column("sandbox_status", sa.String(length=20), nullable=False, server_default="not_run"),
    )
    op.add_column("task_executions", sa.Column("sandbox_target_url", sa.String(length=500), nullable=True))
    op.add_column("task_executions", sa.Column("sandbox_requested_at", sa.String(length=40), nullable=True))
    op.add_column("task_executions", sa.Column("sandbox_updated_at", sa.String(length=40), nullable=True))
    op.create_index(
        "idx_task_executions_sandbox_status",
        "task_executions",
        ["sandbox_status", "sandbox_updated_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_task_executions_sandbox_status", table_name="task_executions")
    op.drop_column("task_executions", "sandbox_updated_at")
    op.drop_column("task_executions", "sandbox_requested_at")
    op.drop_column("task_executions", "sandbox_target_url")
    op.drop_column("task_executions", "sandbox_status")
    op.drop_column("task_executions", "sandbox_profile")
    op.drop_column("task_executions", "sandbox_commit_sha")
    op.drop_column("task_executions", "sandbox_branch")
