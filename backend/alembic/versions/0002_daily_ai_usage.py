"""Create daily_ai_usage table for quota tracking.

Revision ID: 0002_daily_ai_usage
Revises: 0001_initial_schema
Create Date: 2026-11-14 10:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_daily_ai_usage"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "daily_ai_quota_buckets" not in existing_tables:
        op.create_table(
            "daily_ai_quota_buckets",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("usage_date", sa.String(length=10), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("daily_limit_neurons", sa.Float(), server_default="8500.0", nullable=False),
            sa.Column("estimated_neurons", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
        )
        op.create_index("uq_daily_quota_bucket_date_provider", "daily_ai_quota_buckets", ["usage_date", "provider"], unique=True)

    if "daily_ai_usage" not in existing_tables:
        op.create_table(
            "daily_ai_usage",
            sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("usage_date", sa.String(length=10), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model", sa.String(length=120), nullable=False),
            sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("estimated_input_tokens", sa.Integer(), server_default="0", nullable=False),
            sa.Column("estimated_output_tokens", sa.Integer(), server_default="0", nullable=False),
            sa.Column("estimated_neurons", sa.Float(), server_default="0.0", nullable=False),
            sa.Column("created_at", sa.String(length=40), nullable=False),
            sa.Column("updated_at", sa.String(length=40), nullable=False),
        )
        op.create_index("idx_daily_ai_usage_date_provider", "daily_ai_usage", ["usage_date", "provider"], unique=False)
        op.create_index("uq_daily_ai_usage_date_provider_model", "daily_ai_usage", ["usage_date", "provider", "model"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_daily_ai_usage_date_provider_model", table_name="daily_ai_usage")
    op.drop_index("idx_daily_ai_usage_date_provider", table_name="daily_ai_usage")
    op.drop_table("daily_ai_usage")
    op.drop_index("uq_daily_quota_bucket_date_provider", table_name="daily_ai_quota_buckets")
    op.drop_table("daily_ai_quota_buckets")

