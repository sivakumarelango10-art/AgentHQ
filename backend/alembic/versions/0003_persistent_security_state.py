"""Create persistent security state tables: owner_sessions, login_attempts, websocket_tickets.

Revision ID: 0003_persistent_security_state
Revises: 0002_daily_ai_usage
Create Date: 2026-11-14 12:45:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_persistent_security_state"
down_revision: Union[str, None] = "0002_daily_ai_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    # 1. owner_sessions
    if "owner_sessions" not in existing_tables:
        op.create_table(
            "owner_sessions",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("session_token_hash", sa.String(length=64), nullable=False),
            sa.Column("username", sa.String(length=120), nullable=False),
            sa.Column("role", sa.String(length=32), server_default="founder", nullable=False),
            sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
            sa.Column("ip_address", sa.String(length=45), nullable=True),
            sa.Column("user_agent", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("expires_at", sa.BigInteger(), nullable=False),
            sa.Column("is_revoked", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("revoked_at", sa.String(length=40), nullable=True),
            sa.Column("last_seen_at", sa.String(length=40), nullable=True),
        )
        op.create_index("uq_owner_sessions_token_hash", "owner_sessions", ["session_token_hash"], unique=True)
        op.create_index("idx_owner_sessions_expires_at", "owner_sessions", ["expires_at"], unique=False)
        op.create_index("idx_owner_sessions_is_revoked", "owner_sessions", ["is_revoked"], unique=False)
        op.create_index("idx_owner_sessions_username", "owner_sessions", ["username"], unique=False)

    # 2. login_attempts
    if "login_attempts" not in existing_tables:
        op.create_table(
            "login_attempts",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("ip_address", sa.String(length=45), nullable=False),
            sa.Column("username", sa.String(length=120), nullable=True),
            sa.Column("attempt_time", sa.BigInteger(), nullable=False),
            sa.Column("success", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
        )
        op.create_index("idx_login_attempts_ip_time", "login_attempts", ["ip_address", "attempt_time"], unique=False)
        op.create_index("idx_login_attempts_attempt_time", "login_attempts", ["attempt_time"], unique=False)

    # 3. websocket_tickets
    if "websocket_tickets" not in existing_tables:
        op.create_table(
            "websocket_tickets",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("ticket_hash", sa.String(length=64), nullable=False),
            sa.Column("username", sa.String(length=120), nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("expires_at", sa.BigInteger(), nullable=False),
            sa.Column("is_consumed", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("consumed_at", sa.String(length=40), nullable=True),
        )
        op.create_index("uq_ws_tickets_hash", "websocket_tickets", ["ticket_hash"], unique=True)
        op.create_index("idx_ws_tickets_expires_at", "websocket_tickets", ["expires_at"], unique=False)
        op.create_index("idx_ws_tickets_consumed", "websocket_tickets", ["is_consumed"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "websocket_tickets" in existing_tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("websocket_tickets")}
        for idx_name in ("idx_ws_tickets_consumed", "idx_ws_tickets_expires_at", "uq_ws_tickets_hash"):
            if idx_name in indexes:
                op.drop_index(idx_name, table_name="websocket_tickets")
        op.drop_table("websocket_tickets")

    if "login_attempts" in existing_tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("login_attempts")}
        for idx_name in ("idx_login_attempts_attempt_time", "idx_login_attempts_ip_time"):
            if idx_name in indexes:
                op.drop_index(idx_name, table_name="login_attempts")
        op.drop_table("login_attempts")

    if "owner_sessions" in existing_tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("owner_sessions")}
        for idx_name in ("idx_owner_sessions_username", "idx_owner_sessions_is_revoked", "idx_owner_sessions_expires_at", "uq_owner_sessions_token_hash"):
            if idx_name in indexes:
                op.drop_index(idx_name, table_name="owner_sessions")
        op.drop_table("owner_sessions")

