"""Add execution attempt lineage and worker lease recovery.

Revision ID: 0008_task_execution_recovery
Revises: 0007_task_execution_github_pr
Create Date: 2026-11-15 18:30:00.000000
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_task_execution_recovery"
down_revision: Union[str, None] = "0007_task_execution_github_pr"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_executions",
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "task_executions",
        sa.Column(
            "retry_of_execution_id",
            sa.String(length=64),
            sa.ForeignKey("task_executions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("task_executions", sa.Column("last_heartbeat_at", sa.String(length=40), nullable=True))
    op.add_column("task_executions", sa.Column("lease_expires_at", sa.String(length=40), nullable=True))
    op.create_index("idx_task_executions_lease", "task_executions", ["status", "lease_expires_at"])
    # Give legacy running attempts one lease window to finish before recovering them.
    # New workers heartbeat and extend this deadline; interrupted old workers expire safely.
    now = datetime.now(timezone.utc)
    now_text = now.isoformat()
    lease_text = (now + timedelta(seconds=300)).isoformat()
    op.execute(
        sa.text(
            "UPDATE task_executions "
            "SET last_heartbeat_at = :now_text, lease_expires_at = :lease_text "
            "WHERE status = 'running'"
        ).bindparams(now_text=now_text, lease_text=lease_text)
    )


def downgrade() -> None:
    op.drop_index("idx_task_executions_lease", table_name="task_executions")
    op.drop_column("task_executions", "lease_expires_at")
    op.drop_column("task_executions", "last_heartbeat_at")
    op.drop_column("task_executions", "retry_of_execution_id")
    op.drop_column("task_executions", "attempt_number")
