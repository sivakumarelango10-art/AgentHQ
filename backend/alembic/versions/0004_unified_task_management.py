"""Unified persistent task management schema and audit logs.

Revision ID: 0004_unified_task_management
Revises: 0003_persistent_security_state
Create Date: 2026-11-14 14:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_unified_task_management"
down_revision: Union[str, None] = "0003_persistent_security_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if conn.dialect.name == "postgresql":
        op.execute(sa.text("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS check_task_status;"))
        op.execute(sa.text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'check_task_status_v2'
                ) THEN
                    ALTER TABLE tasks ADD CONSTRAINT check_task_status_v2
                    CHECK (status IN ('inbox', 'queued', 'scheduled', 'working', 'needs_attention', 'done', 'cancelled'));
                END IF;
            END $$;
        """))

    # 1. Update tasks table with extended fields if not already present
    if "tasks" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("tasks")}
        if "due_date" not in existing_cols:
            op.add_column("tasks", sa.Column("due_date", sa.String(length=40), nullable=True))
        if "completed_at" not in existing_cols:
            op.add_column("tasks", sa.Column("completed_at", sa.String(length=40), nullable=True))
        if "source" not in existing_cols:
            op.add_column(
                "tasks",
                sa.Column("source", sa.String(length=40), server_default="hermes3d_manual", nullable=False),
            )
        if "source_event_id" not in existing_cols:
            op.add_column("tasks", sa.Column("source_event_id", sa.String(length=120), nullable=True))

        existing_indexes = {idx["name"] for idx in inspector.get_indexes("tasks")}
        if "idx_tasks_due_date" not in existing_indexes:
            op.create_index("idx_tasks_due_date", "tasks", ["due_date"], unique=False)

    # 2. task_audit_logs
    if "task_audit_logs" not in existing_tables:
        op.create_table(
            "task_audit_logs",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column(
                "task_id",
                sa.String(length=64),
                sa.ForeignKey("tasks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("action", sa.String(length=40), nullable=False),
            sa.Column("from_status", sa.String(length=40), nullable=True),
            sa.Column("to_status", sa.String(length=40), nullable=True),
            sa.Column("from_agent_id", sa.String(length=64), nullable=True),
            sa.Column("to_agent_id", sa.String(length=64), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("actor", sa.String(length=80), server_default="founder", nullable=False),
            sa.Column("at", sa.String(length=40), nullable=False),
        )
        op.create_index("idx_task_audit_task_id_at", "task_audit_logs", ["task_id", "at"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "task_audit_logs" in existing_tables:
        op.drop_table("task_audit_logs")

    if "tasks" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("tasks")}
        with op.batch_alter_table("tasks") as batch_op:
            if "source_event_id" in existing_cols:
                batch_op.drop_column("source_event_id")
            if "source" in existing_cols:
                batch_op.drop_column("source")
            if "completed_at" in existing_cols:
                batch_op.drop_column("completed_at")
            if "due_date" in existing_cols:
                batch_op.drop_column("due_date")

