"""Initial production schema and dual-database migration.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-14 10:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_AGENTS = [
    {
        "id": "ceo", "name": "Atlas", "role": "AI Orchestrator",
        "department": "Management", "status": "idle", "room": "CEO Office",
        "color": "#c5a46d", "current_task": "Available — awaiting assignment",
    },
    {
        "id": "pm", "name": "Mira", "role": "Project Manager",
        "department": "Management", "status": "idle", "room": "Development Room",
        "color": "#73a9a1", "current_task": "Available — awaiting assignment",
    },
    {
        "id": "dev", "name": "Arin", "role": "Software Engineer",
        "department": "Engineering", "status": "idle", "room": "Development Room",
        "color": "#8c9bc8", "current_task": "Available — awaiting assignment",
    },
    {
        "id": "design", "name": "Nia", "role": "UI/UX Designer",
        "department": "Design", "status": "idle", "room": "Design Studio",
        "color": "#c28ca8", "current_task": "Available — awaiting assignment",
    },
    {
        "id": "research", "name": "Ira", "role": "Research Analyst",
        "department": "Research", "status": "idle", "room": "Research Room",
        "color": "#89a98b", "current_task": "Available — awaiting assignment",
    },
    {
        "id": "qa", "name": "Dev", "role": "QA Engineer",
        "department": "Quality & Testing", "status": "idle", "room": "Meeting Room",
        "color": "#d69a70", "current_task": "Available — awaiting assignment",
    },
    {
        "id": "kiran", "name": "Kiran", "role": "Software Engineer",
        "department": "Engineering", "status": "idle", "room": "Development Room",
        "color": "#7d8cbc", "current_task": "Available — awaiting assignment",
    },
]


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())
    is_sqlite = conn.dialect.name == "sqlite"

    # 1. agents
    if "agents" not in existing_tables:
        op.create_table(
            "agents",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("name", sa.String(length=48), nullable=False),
            sa.Column("role", sa.String(length=80), nullable=False),
            sa.Column("department", sa.String(length=48), nullable=False),
            sa.Column("status", sa.String(length=20), server_default="idle", nullable=False),
            sa.Column("room", sa.String(length=64), nullable=False),
            sa.Column("color", sa.String(length=7), server_default="#8c9bc8", nullable=False),
            sa.Column("current_task", sa.String(length=255), server_default="Available — awaiting assignment", nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
            sa.CheckConstraint("status IN ('working', 'idle', 'meeting', 'offline')", name="check_agent_status"),
        )

    # 2. tasks
    if "tasks" not in existing_tables:
        op.create_table(
            "tasks",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), server_default="", nullable=False),
            sa.Column("priority", sa.String(length=20), server_default="normal", nullable=False),
            sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
            sa.Column("assigned_agent_id", sa.String(length=64), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
            sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="check_task_priority"),
            sa.CheckConstraint("status IN ('queued', 'cancelled')", name="check_task_status"),
        )
        op.create_index("idx_tasks_created_at", "tasks", ["created_at"], unique=False)
        op.create_index("idx_tasks_status", "tasks", ["status"], unique=False)
        op.create_index("idx_tasks_assigned_agent", "tasks", ["assigned_agent_id"], unique=False)

    # 3. conversations
    if "conversations" not in existing_tables:
        op.create_table(
            "conversations",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("agent_id", sa.String(length=64), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
        )
        op.create_index("idx_conversations_agent_updated", "conversations", ["agent_id", "updated_at"], unique=False)

    # 4. conversation_messages
    if "conversation_messages" not in existing_tables:
        op.create_table(
            "conversation_messages",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("conversation_id", sa.String(length=64), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("order_index", sa.Integer(), server_default="0", nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.CheckConstraint("role IN ('user', 'assistant')", name="check_message_role"),
        )
        op.create_index("idx_messages_conversation_created", "conversation_messages", ["conversation_id", "created_at"], unique=False)
        op.create_index("idx_messages_conversation_order", "conversation_messages", ["conversation_id", "created_at", "order_index"], unique=False)
    else:
        existing_cols = {col["name"] for col in inspector.get_columns("conversation_messages")}
        if "order_index" not in existing_cols:
            with op.batch_alter_table("conversation_messages") as batch_op:
                batch_op.add_column(sa.Column("order_index", sa.Integer(), server_default="0", nullable=False))
            if is_sqlite:
                op.execute(sa.text("UPDATE conversation_messages SET order_index = rowid WHERE order_index = 0"))
            existing_indexes = {idx["name"] for idx in inspector.get_indexes("conversation_messages")}
            if "idx_messages_conversation_order" not in existing_indexes:
                op.create_index("idx_messages_conversation_order", "conversation_messages", ["conversation_id", "created_at", "order_index"], unique=False)

    # 5. runtime_sessions
    if "runtime_sessions" not in existing_tables:
        op.create_table(
            "runtime_sessions",
            sa.Column("session_id", sa.String(length=200), primary_key=True, nullable=False),
            sa.Column("agent_id", sa.String(length=64), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("conversation_id", sa.String(length=64), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
        )

    # 6. Idempotent Seed for Canonical Agents
    now = datetime.now(timezone.utc).isoformat()
    existing_agent_ids = {
        row[0]
        for row in conn.execute(sa.text("SELECT id FROM agents")).fetchall()
    }
    for agent in SEED_AGENTS:
        if agent["id"] not in existing_agent_ids:
            conn.execute(
                sa.text(
                    "INSERT INTO agents (id, name, role, department, status, room, color, current_task, created_at, updated_at) "
                    "VALUES (:id, :name, :role, :department, :status, :room, :color, :current_task, :created_at, :updated_at)"
                ),
                {**agent, "created_at": now, "updated_at": now},
            )


def downgrade() -> None:
    op.drop_table("runtime_sessions")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
    op.drop_table("tasks")
    op.drop_table("agents")

