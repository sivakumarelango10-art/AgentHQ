"""Task lifecycle timestamp semantics and optimistic concurrency versioning.

Revision ID: 0005_task_lifecycle_and_concurrency
Revises: 0004_unified_task_management
Create Date: 2026-11-14 15:15:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005_task_lifecycle_and_concurrency"
down_revision: Union[str, None] = "0004_unified_task_management"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "tasks" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("tasks")}
        if "cancelled_at" not in existing_cols:
            op.add_column("tasks", sa.Column("cancelled_at", sa.String(length=40), nullable=True))
        if "version" not in existing_cols:
            op.add_column(
                "tasks",
                sa.Column("version", sa.Integer(), server_default="1", nullable=False),
            )

        existing_indexes = {idx["name"] for idx in inspector.get_indexes("tasks")}
        if "idx_tasks_cancelled_at" not in existing_indexes:
            op.create_index("idx_tasks_cancelled_at", "tasks", ["cancelled_at"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "tasks" in existing_tables:
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("tasks")}
        if "idx_tasks_cancelled_at" in existing_indexes:
            op.drop_index("idx_tasks_cancelled_at", table_name="tasks")

        existing_cols = {col["name"] for col in inspector.get_columns("tasks")}
        with op.batch_alter_table("tasks") as batch_op:
            if "version" in existing_cols:
                batch_op.drop_column("version")
            if "cancelled_at" in existing_cols:
                batch_op.drop_column("cancelled_at")

