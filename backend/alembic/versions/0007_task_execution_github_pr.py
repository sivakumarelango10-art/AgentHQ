"""Add GitHub PR metadata to approved task executions.

Revision ID: 0007_task_execution_github_pr
Revises: 0006_task_execution_approval
Create Date: 2026-11-15 18:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_task_execution_github_pr"
down_revision: Union[str, None] = "0006_task_execution_approval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("task_executions", sa.Column("github_repo", sa.String(length=200), nullable=True))
    op.add_column("task_executions", sa.Column("github_branch", sa.String(length=255), nullable=True))
    op.add_column("task_executions", sa.Column("github_commit_sha", sa.String(length=64), nullable=True))
    op.add_column("task_executions", sa.Column("github_pr_url", sa.String(length=500), nullable=True))
    op.add_column("task_executions", sa.Column("github_pr_number", sa.Integer(), nullable=True))
    op.add_column("task_executions", sa.Column("github_pr_state", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("task_executions", "github_pr_state")
    op.drop_column("task_executions", "github_pr_number")
    op.drop_column("task_executions", "github_pr_url")
    op.drop_column("task_executions", "github_commit_sha")
    op.drop_column("task_executions", "github_branch")
    op.drop_column("task_executions", "github_repo")
