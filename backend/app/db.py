from __future__ import annotations

import math
import os
import random
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    case,
    create_engine,
    event,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
)

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "data" / "agenthq.db"

SEED_AGENTS: list[dict[str, str]] = [
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


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp preserving microsecond precision."""
    return datetime.now(timezone.utc).isoformat()


def database_path() -> Path:
    """Resolve the SQLite database path from environment or default."""
    configured = os.getenv("AGENTHQ_DB_PATH")
    path = Path(configured).expanduser() if configured else DEFAULT_DB_PATH
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def normalize_database_url(url: str) -> str:
    """Normalize PostgreSQL connection URLs for SQLAlchemy 2.x and psycopg 3."""
    cleaned = url.strip()
    if cleaned.startswith("postgres://"):
        cleaned = "postgresql+psycopg://" + cleaned[len("postgres://"):]
    elif cleaned.startswith("postgresql://") and not cleaned.startswith("postgresql+"):
        cleaned = "postgresql+psycopg://" + cleaned[len("postgresql://"):]
    return cleaned


def get_database_url() -> str:
    """Determine the active database URL. DATABASE_URL takes priority over SQLite."""
    configured = os.getenv("DATABASE_URL")
    if configured and configured.strip():
        return normalize_database_url(configured)
    db_path = database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


# --- SQLAlchemy Engine & Session Configuration ---

_cached_engine: Engine | None = None
_cached_engine_url: str | None = None


def create_database_engine(url: str | None = None) -> Engine:
    """Create a database engine with connection pooling and dialect-specific hooks."""
    db_url = url or get_database_url()
    if db_url.startswith("sqlite"):
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False, "timeout": 30.0},
            poolclass=NullPool,
            pool_pre_ping=True,
        )

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            if engine.dialect.name == "sqlite":
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.execute("PRAGMA busy_timeout = 30000")
                cursor.close()

        return engine
    else:
        # PostgreSQL / Neon bounded pool settings
        return create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
            max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "2")),
            pool_timeout=float(os.getenv("DB_POOL_TIMEOUT", "30")),
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "300")),
            pool_pre_ping=True,
        )


def get_engine() -> Engine:
    """Retrieve or create the singleton SQLAlchemy engine, invalidating on URL change."""
    global _cached_engine, _cached_engine_url
    current_url = get_database_url()
    if _cached_engine is None or _cached_engine_url != current_url:
        if _cached_engine is not None:
            _cached_engine.dispose()
        _cached_engine = create_database_engine(current_url)
        _cached_engine_url = current_url
    return _cached_engine


def reset_engine() -> None:
    """Dispose and clear cached engine for test environment resets."""
    global _cached_engine, _cached_engine_url
    if _cached_engine is not None:
        _cached_engine.dispose()
    _cached_engine = None
    _cached_engine_url = None


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional SQLAlchemy session scope."""
    engine = get_engine()
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def connect():
    """Legacy backward-compatibility context manager providing transactional connection access."""
    engine = get_engine()
    with engine.begin() as conn:
        yield conn


# --- SQLAlchemy 2.0 Declarative Models ---


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(48), nullable=False)
    role: Mapped[str] = mapped_column(String(80), nullable=False)
    department: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    room: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#8c9bc8")
    current_task: Mapped[str] = mapped_column(
        String(255), nullable=False, default="Available — awaiting assignment"
    )
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('working', 'idle', 'meeting', 'offline')",
            name="check_agent_status",
        ),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "department": self.department,
            "status": self.status,
            "room": self.room,
            "color": self.color,
            "current_task": self.current_task,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    assigned_agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    assigned_agent: Mapped[Agent | None] = relationship("Agent")

    __table_args__ = (
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="check_task_priority",
        ),
        CheckConstraint(
            "status IN ('queued', 'cancelled')",
            name="check_task_status",
        ),
        Index("idx_tasks_created_at", created_at.desc()),
        Index("idx_tasks_status", status),
        Index("idx_tasks_assigned_agent", assigned_agent_id),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "assigned_agent_id": self.assigned_agent_id,
            "assigned_agent_name": self.assigned_agent.name if self.assigned_agent else None,
            "assigned_agent_role": self.assigned_agent.role if self.assigned_agent else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    agent: Mapped[Agent] = relationship("Agent")

    __table_args__ = (
        Index("idx_conversations_agent_updated", agent_id, updated_at.desc()),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "title": self.title,
            "agent_name": self.agent.name if self.agent else None,
            "agent_role": self.agent.role if self.agent else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="check_message_role"),
        Index("idx_messages_conversation_created", conversation_id, created_at),
        Index("idx_messages_conversation_order", conversation_id, created_at, order_index),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "order_index": self.order_index,
            "created_at": self.created_at,
        }


class RuntimeSession(Base):
    __tablename__ = "runtime_sessions"

    session_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# --- Daily AI Quota Constants ---

INPUT_NEURONS_PER_MILLION = 40909.0
OUTPUT_NEURONS_PER_MILLION = 290909.0
CLOUDFLARE_DEFAULT_DAILY_LIMIT = 8500.0


class DailyAIQuotaBucket(Base):
    __tablename__ = "daily_ai_quota_buckets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    usage_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    daily_limit_neurons: Mapped[float] = mapped_column(Float, nullable=False, default=CLOUDFLARE_DEFAULT_DAILY_LIMIT)
    estimated_neurons: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    __table_args__ = (
        Index("uq_daily_quota_bucket_date_provider", "usage_date", "provider", unique=True),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "usage_date": self.usage_date,
            "provider": self.provider,
            "daily_limit_neurons": self.daily_limit_neurons,
            "estimated_neurons": round(self.estimated_neurons, 6),
            "request_count": self.request_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class DailyAIUsage(Base):
    __tablename__ = "daily_ai_usage"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    usage_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_neurons: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    __table_args__ = (
        Index("idx_daily_ai_usage_date_provider", "usage_date", "provider"),
        Index("uq_daily_ai_usage_date_provider_model", "usage_date", "provider", "model", unique=True),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "usage_date": self.usage_date,
            "provider": self.provider,
            "model": self.model,
            "request_count": self.request_count,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
            "estimated_neurons": round(self.estimated_neurons, 6),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# --- UTC Helper Functions ---


def utc_today_str() -> str:
    """Return the current UTC date in YYYY-MM-DD format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def utc_midnight_info() -> tuple[str, int]:
    """Calculate the ISO string of the next UTC midnight and seconds remaining until then."""
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    seconds_remaining = max(1, int((tomorrow - now).total_seconds()))
    return tomorrow.isoformat(), seconds_remaining


def calculate_estimated_neurons(input_tokens: int, output_tokens: int) -> float:
    """Calculate estimated Cloudflare neurons using published Qwen 27B model rates.

    Negative tokens are normalized to 0. Calculations use 6 decimal places.
    """
    norm_in = max(0, int(input_tokens or 0))
    norm_out = max(0, int(output_tokens or 0))
    in_neurons = (norm_in * INPUT_NEURONS_PER_MILLION) / 1_000_000.0
    out_neurons = (norm_out * OUTPUT_NEURONS_PER_MILLION) / 1_000_000.0
    total = in_neurons + out_neurons
    return float(round(total, 6))


class QuotaExceededException(Exception):
    """Raised when daily inference neuron quota has been reached."""
    def __init__(self, message: str, current_neurons: float, limit: float, reset_at: str, retry_after: int):
        super().__init__(message)
        self.current_neurons = current_neurons
        self.limit = limit
        self.reset_at = reset_at
        self.retry_after = retry_after


@dataclass
class QuotaReservation:
    reservation_id: str
    usage_date: str
    provider: str
    model: str
    provisional_input_tokens: int
    provisional_output_tokens: int
    provisional_neurons: float


def get_daily_neuron_usage(provider: str = "cloudflare", usage_date: str | None = None) -> float:
    """Return cumulative estimated neurons consumed for the specified provider and date across all models."""
    date_str = usage_date or utc_today_str()
    engine = get_engine()
    with engine.connect() as conn:
        b_val = conn.execute(
            text("""
                SELECT estimated_neurons
                FROM daily_ai_quota_buckets
                WHERE usage_date = :usage_date AND provider = :provider
            """),
            {"usage_date": date_str, "provider": provider},
        ).scalar()
        u_val = conn.execute(
            text("""
                SELECT COALESCE(SUM(estimated_neurons), 0.0)
                FROM daily_ai_usage
                WHERE usage_date = :usage_date AND provider = :provider
            """),
            {"usage_date": date_str, "provider": provider},
        ).scalar() or 0.0

        if b_val is None:
            return float(u_val)
        return float(max(float(b_val), float(u_val)))


def get_quota_status(provider: str = "cloudflare", daily_limit: float | None = None) -> dict[str, Any]:
    """Retrieve current daily quota consumption and remaining neurons across all models."""
    limit = (
        daily_limit
        if daily_limit is not None
        else float(os.getenv("CLOUDFLARE_DAILY_NEURON_LIMIT", str(CLOUDFLARE_DEFAULT_DAILY_LIMIT)))
    )
    today = utc_today_str()
    reset_at, retry_after = utc_midnight_info()
    current_neurons = get_daily_neuron_usage(provider=provider, usage_date=today)
    return {
        "provider": provider,
        "usage_date": today,
        "daily_limit_neurons": limit,
        "current_neurons": round(current_neurons, 4),
        "remaining_neurons": max(0.0, round(limit - current_neurons, 4)),
        "is_exhausted": current_neurons >= limit,
        "reset_at": reset_at,
        "retry_after_seconds": retry_after,
    }


def reserve_ai_quota(
    provider: str,
    model: str,
    estimated_input_tokens: int,
    max_output_tokens: int = 700,
    daily_limit: float | None = None,
) -> QuotaReservation:
    """Atomically reserve quota before initiating inference using database-level synchronization.

    PostgreSQL:
      - Inserts shared daily quota bucket row with ON CONFLICT (usage_date, provider) DO NOTHING.
      - Acquires an exclusive row lock on the SHARED provider bucket (SELECT id ... FOR UPDATE).
        This guarantees strict serialization across ALL models sharing the provider and date.
      - Atomically updates the shared bucket only if cumulative usage <= daily_limit.
      - Inserts or updates the model-specific usage record for granular per-model telemetry.

    SQLite:
      - Uses BEGIN IMMEDIATE to acquire an immediate write lock.
      - Uses PRAGMA busy_timeout = 30000 with exponential retry backoff.
      - Atomically updates the shared bucket and model records.
    """
    limit = (
        daily_limit
        if daily_limit is not None
        else float(os.getenv("CLOUDFLARE_DAILY_NEURON_LIMIT", str(CLOUDFLARE_DEFAULT_DAILY_LIMIT)))
    )
    today = utc_today_str()
    now_ts = utc_now()
    norm_in = max(0, int(estimated_input_tokens or 0))
    norm_out = max(0, int(max_output_tokens or 0))
    provisional_neurons = calculate_estimated_neurons(norm_in, norm_out)

    engine = get_engine()
    is_sqlite = engine.dialect.name == "sqlite"
    max_retries = 10 if is_sqlite else 3

    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                if is_sqlite:
                    conn.execute(text("PRAGMA busy_timeout = 30000"))
                    conn.execute(text("BEGIN IMMEDIATE"))
                else:
                    conn.execute(text("BEGIN"))

                # 1. Ensure shared daily quota bucket exists for this provider and date, seeded with any existing usage sum
                conn.execute(
                    text("""
                        INSERT INTO daily_ai_quota_buckets (
                            id, usage_date, provider, daily_limit_neurons,
                            estimated_neurons, request_count, created_at, updated_at
                        ) VALUES (
                            :id, :usage_date, :provider, :limit,
                            (SELECT COALESCE(SUM(estimated_neurons), 0.0) FROM daily_ai_usage WHERE usage_date = :usage_date AND provider = :provider),
                            (SELECT COALESCE(SUM(request_count), 0) FROM daily_ai_usage WHERE usage_date = :usage_date AND provider = :provider),
                            :created_at, :updated_at
                        )
                        ON CONFLICT (usage_date, provider) DO NOTHING
                    """),
                    {
                        "id": f"bucket-{today}-{provider}",
                        "usage_date": today,
                        "provider": provider,
                        "limit": limit,
                        "created_at": now_ts,
                        "updated_at": now_ts,
                    },
                )

                # Sync bucket if direct records exist in daily_ai_usage with higher usage
                conn.execute(
                    text("""
                        UPDATE daily_ai_quota_buckets
                        SET estimated_neurons = (SELECT COALESCE(SUM(estimated_neurons), 0.0) FROM daily_ai_usage WHERE usage_date = :usage_date AND provider = :provider),
                            request_count = (SELECT COALESCE(SUM(request_count), 0) FROM daily_ai_usage WHERE usage_date = :usage_date AND provider = :provider)
                        WHERE usage_date = :usage_date AND provider = :provider
                          AND estimated_neurons < (SELECT COALESCE(SUM(estimated_neurons), 0.0) FROM daily_ai_usage WHERE usage_date = :usage_date AND provider = :provider)
                    """),
                    {"usage_date": today, "provider": provider},
                )

                # 2. Ensure model-specific usage row exists for granular telemetry
                conn.execute(
                    text("""
                        INSERT INTO daily_ai_usage (
                            id, usage_date, provider, model,
                            request_count, estimated_input_tokens, estimated_output_tokens,
                            estimated_neurons, created_at, updated_at
                        ) VALUES (
                            :id, :usage_date, :provider, :model,
                            0, 0, 0, 0.0, :created_at, :updated_at
                        )
                        ON CONFLICT (usage_date, provider, model) DO NOTHING
                    """),
                    {
                        "id": f"usage-{today}-{uuid4().hex[:12]}",
                        "usage_date": today,
                        "provider": provider,
                        "model": model,
                        "created_at": now_ts,
                        "updated_at": now_ts,
                    },
                )

                # 3. For PostgreSQL, lock the SHARED provider bucket row across ALL models
                if not is_sqlite:
                    conn.execute(
                        text("""
                            SELECT id FROM daily_ai_quota_buckets
                            WHERE usage_date = :usage_date AND provider = :provider
                            FOR UPDATE
                        """),
                        {"usage_date": today, "provider": provider},
                    )

                # 4. Atomically update the shared provider bucket under lock
                result = conn.execute(
                    text("""
                        UPDATE daily_ai_quota_buckets
                        SET 
                            request_count = request_count + 1,
                            estimated_neurons = estimated_neurons + :prov_neurons,
                            updated_at = :updated_at
                        WHERE usage_date = :usage_date AND provider = :provider
                          AND (estimated_neurons + :prov_neurons) <= :limit
                        RETURNING estimated_neurons, request_count
                    """),
                    {
                        "prov_neurons": provisional_neurons,
                        "updated_at": now_ts,
                        "usage_date": today,
                        "provider": provider,
                        "limit": limit,
                    },
                )
                bucket_row = result.fetchone()

                if not bucket_row:
                    conn.rollback()
                    current_total = conn.execute(
                        text("""
                            SELECT estimated_neurons FROM daily_ai_quota_buckets
                            WHERE usage_date = :usage_date AND provider = :provider
                        """),
                        {"usage_date": today, "provider": provider},
                    ).scalar() or 0.0
                    reset_at, retry_after = utc_midnight_info()
                    raise QuotaExceededException(
                        f"Daily AI quota reached for {provider}: {current_total:.2f}/{limit:.0f} neurons used.",
                        current_neurons=current_total,
                        limit=limit,
                        reset_at=reset_at,
                        retry_after=retry_after,
                    )

                # 5. Update model-specific telemetry breakdown
                conn.execute(
                    text("""
                        UPDATE daily_ai_usage
                        SET 
                            request_count = request_count + 1,
                            estimated_input_tokens = estimated_input_tokens + :in_tokens,
                            estimated_output_tokens = estimated_output_tokens + :out_tokens,
                            estimated_neurons = estimated_neurons + :prov_neurons,
                            updated_at = :updated_at
                        WHERE usage_date = :usage_date AND provider = :provider AND model = :model
                    """),
                    {
                        "in_tokens": norm_in,
                        "out_tokens": norm_out,
                        "prov_neurons": provisional_neurons,
                        "updated_at": now_ts,
                        "usage_date": today,
                        "provider": provider,
                        "model": model,
                    },
                )

                conn.commit()
                break
        except (sqlite3.OperationalError, OperationalError) as err:
            err_msg = str(err).lower()
            if ("locked" in err_msg or "busy" in err_msg) and attempt < max_retries - 1:
                time.sleep(0.02 * (2 ** attempt) + random.uniform(0.005, 0.02))
                continue
            raise

    return QuotaReservation(
        reservation_id=str(uuid4()),
        usage_date=today,
        provider=provider,
        model=model,
        provisional_input_tokens=norm_in,
        provisional_output_tokens=norm_out,
        provisional_neurons=provisional_neurons,
    )


def reconcile_ai_quota(
    reservation: QuotaReservation,
    actual_input_tokens: int,
    actual_output_tokens: int,
) -> None:
    """Reconcile provisional reservation with actual token counts returned by the provider."""
    norm_in = max(0, int(actual_input_tokens or 0))
    norm_out = max(0, int(actual_output_tokens or 0))
    now_ts = utc_now()
    actual_neurons = calculate_estimated_neurons(norm_in, norm_out)
    delta_input = norm_in - reservation.provisional_input_tokens
    delta_output = norm_out - reservation.provisional_output_tokens
    delta_neurons = actual_neurons - reservation.provisional_neurons

    engine = get_engine()
    is_sqlite = engine.dialect.name == "sqlite"
    max_retries = 10 if is_sqlite else 3

    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                if is_sqlite:
                    conn.execute(text("PRAGMA busy_timeout = 30000"))
                    conn.execute(text("BEGIN IMMEDIATE"))
                else:
                    conn.execute(text("BEGIN"))

                # 1. Update shared provider bucket
                conn.execute(
                    text("""
                        UPDATE daily_ai_quota_buckets
                        SET 
                            estimated_neurons = CASE 
                                WHEN estimated_neurons + :delta_neurons >= 0.0 THEN estimated_neurons + :delta_neurons 
                                ELSE 0.0 
                            END,
                            updated_at = :updated_at
                        WHERE usage_date = :usage_date AND provider = :provider
                    """),
                    {
                        "delta_neurons": delta_neurons,
                        "updated_at": now_ts,
                        "usage_date": reservation.usage_date,
                        "provider": reservation.provider,
                    },
                )

                # 2. Update model-specific telemetry breakdown
                conn.execute(
                    text("""
                        UPDATE daily_ai_usage
                        SET 
                            estimated_input_tokens = CASE 
                                WHEN estimated_input_tokens + :delta_in >= 0 THEN estimated_input_tokens + :delta_in 
                                ELSE 0 
                            END,
                            estimated_output_tokens = CASE 
                                WHEN estimated_output_tokens + :delta_out >= 0 THEN estimated_output_tokens + :delta_out 
                                ELSE 0 
                            END,
                            estimated_neurons = CASE 
                                WHEN estimated_neurons + :delta_neurons >= 0.0 THEN estimated_neurons + :delta_neurons 
                                ELSE 0.0 
                            END,
                            updated_at = :updated_at
                        WHERE usage_date = :usage_date AND provider = :provider AND model = :model
                    """),
                    {
                        "delta_in": delta_input,
                        "delta_out": delta_output,
                        "delta_neurons": delta_neurons,
                        "updated_at": now_ts,
                        "usage_date": reservation.usage_date,
                        "provider": reservation.provider,
                        "model": reservation.model,
                    },
                )
                conn.commit()
                break
        except (sqlite3.OperationalError, OperationalError) as err:
            err_msg = str(err).lower()
            if ("locked" in err_msg or "busy" in err_msg) and attempt < max_retries - 1:
                time.sleep(0.02 * (2 ** attempt) + random.uniform(0.005, 0.02))
                continue
            raise


def release_ai_quota(reservation: QuotaReservation) -> None:
    """Release a provisional quota reservation if an error occurred before dispatch."""
    now_ts = utc_now()
    engine = get_engine()
    is_sqlite = engine.dialect.name == "sqlite"
    max_retries = 10 if is_sqlite else 3

    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                if is_sqlite:
                    conn.execute(text("PRAGMA busy_timeout = 30000"))
                    conn.execute(text("BEGIN IMMEDIATE"))
                else:
                    conn.execute(text("BEGIN"))

                # 1. Update shared provider bucket
                conn.execute(
                    text("""
                        UPDATE daily_ai_quota_buckets
                        SET 
                            request_count = CASE WHEN request_count > 0 THEN request_count - 1 ELSE 0 END,
                            estimated_neurons = CASE 
                                WHEN estimated_neurons >= :prov_neurons THEN estimated_neurons - :prov_neurons 
                                ELSE 0.0 
                            END,
                            updated_at = :updated_at
                        WHERE usage_date = :usage_date AND provider = :provider
                    """),
                    {
                        "prov_neurons": reservation.provisional_neurons,
                        "updated_at": now_ts,
                        "usage_date": reservation.usage_date,
                        "provider": reservation.provider,
                    },
                )

                # 2. Update model-specific telemetry breakdown
                conn.execute(
                    text("""
                        UPDATE daily_ai_usage
                        SET 
                            request_count = CASE WHEN request_count > 0 THEN request_count - 1 ELSE 0 END,
                            estimated_input_tokens = CASE 
                                WHEN estimated_input_tokens >= :prov_in THEN estimated_input_tokens - :prov_in 
                                ELSE 0 
                            END,
                            estimated_output_tokens = CASE 
                                WHEN estimated_output_tokens >= :prov_out THEN estimated_output_tokens - :prov_out 
                                ELSE 0 
                            END,
                            estimated_neurons = CASE 
                                WHEN estimated_neurons >= :prov_neurons THEN estimated_neurons - :prov_neurons 
                                ELSE 0.0 
                            END,
                            updated_at = :updated_at
                        WHERE usage_date = :usage_date AND provider = :provider AND model = :model
                    """),
                    {
                        "prov_in": reservation.provisional_input_tokens,
                        "prov_out": reservation.provisional_output_tokens,
                        "prov_neurons": reservation.provisional_neurons,
                        "updated_at": now_ts,
                        "usage_date": reservation.usage_date,
                        "provider": reservation.provider,
                        "model": reservation.model,
                    },
                )
                conn.commit()
                break
        except (sqlite3.OperationalError, OperationalError) as err:
            err_msg = str(err).lower()
            if ("locked" in err_msg or "busy" in err_msg) and attempt < max_retries - 1:
                time.sleep(0.02 * (2 ** attempt) + random.uniform(0.005, 0.02))
                continue
            raise


# --- Seeding & Initialization ---


def seed_agents(session: Session | None = None) -> None:
    """Ensure all seven canonical employees exist without overwriting customizations."""
    if session is not None:
        _do_seed_agents(session)
    else:
        with get_session() as s:
            _do_seed_agents(s)


def _do_seed_agents(session: Session) -> None:
    now = utc_now()
    for agent_data in SEED_AGENTS:
        existing = session.get(Agent, agent_data["id"])
        if existing is None:
            new_agent = Agent(
                id=agent_data["id"],
                name=agent_data["name"],
                role=agent_data["role"],
                department=agent_data["department"],
                status=agent_data["status"],
                room=agent_data["room"],
                color=agent_data["color"],
                current_task=agent_data["current_task"],
                created_at=now,
                updated_at=now,
            )
            session.add(new_agent)
    session.flush()


def init_db(engine: Engine | None = None) -> None:
    """Initialize schema and ensure existing SQLite databases gain the order_index column safely."""
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)

    with eng.connect() as conn:
        inspector = inspect(conn)
        if "conversation_messages" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("conversation_messages")}
            if "order_index" not in columns:
                conn.execute(
                    text("ALTER TABLE conversation_messages ADD COLUMN order_index INTEGER NOT NULL DEFAULT 0")
                )
                if eng.dialect.name == "sqlite":
                    conn.execute(
                        text("UPDATE conversation_messages SET order_index = rowid WHERE order_index = 0")
                    )
                conn.commit()

    with get_session() as session:
        seed_agents(session)


# --- Public Database Query & Mutation API ---


def list_agents() -> list[dict[str, Any]]:
    with get_session() as session:
        dept_order = case(
            (Agent.department == "Management", 0),
            (Agent.department == "Engineering", 1),
            (Agent.department == "Design", 2),
            (Agent.department == "Research", 3),
            else_=4,
        )
        stmt = select(Agent).order_by(dept_order, Agent.created_at, Agent.name)
        agents = session.scalars(stmt).all()
        return [agent.to_dict() for agent in agents]


def create_agent(payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    agent_id = f"agent-{uuid4().hex[:10]}"
    record = {
        "id": agent_id,
        "name": payload["name"],
        "role": payload["role"],
        "department": payload["department"],
        "status": "idle",
        "room": payload["room"],
        "color": payload.get("color") or "#8c9bc8",
        "current_task": "Available — awaiting assignment",
        "created_at": now,
        "updated_at": now,
    }
    with get_session() as session:
        agent = Agent(**record)
        session.add(agent)
    return record


def list_tasks(status: str | None = None) -> list[dict[str, Any]]:
    with get_session() as session:
        stmt = select(Task)
        if status:
            stmt = stmt.where(Task.status == status)
        prio_order = case(
            (Task.priority == "urgent", 0),
            (Task.priority == "high", 1),
            (Task.priority == "normal", 2),
            else_=3,
        )
        stmt = stmt.order_by(prio_order, Task.created_at.desc())
        tasks = session.scalars(stmt).all()
        return [task.to_dict() for task in tasks]


def create_task(payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    task_id = str(uuid4())
    assigned_agent_id = payload.get("assigned_agent_id")
    with get_session() as session:
        assigned_agent_name = None
        assigned_agent_role = None
        if assigned_agent_id:
            agent = session.get(Agent, assigned_agent_id)
            if agent is None:
                raise ValueError("The selected employee does not exist.")
            assigned_agent_name = agent.name
            assigned_agent_role = agent.role

        task = Task(
            id=task_id,
            title=payload["title"],
            description=payload.get("description", ""),
            priority=payload.get("priority", "normal"),
            status="queued",
            assigned_agent_id=assigned_agent_id,
            created_at=now,
            updated_at=now,
        )
        session.add(task)
    return {
        "id": task_id,
        "title": payload["title"],
        "description": payload.get("description", ""),
        "priority": payload.get("priority", "normal"),
        "status": "queued",
        "assigned_agent_id": assigned_agent_id,
        "assigned_agent_name": assigned_agent_name,
        "assigned_agent_role": assigned_agent_role,
        "created_at": now,
        "updated_at": now,
    }


def cancel_task(task_id: str) -> dict[str, Any] | None:
    now = utc_now()
    with get_session() as session:
        task = session.get(Task, task_id)
        if task is None:
            return None
        if task.status == "queued":
            task.status = "cancelled"
            task.updated_at = now
            session.flush()
        return task.to_dict()


def get_agent(agent_id: str) -> dict[str, Any] | None:
    with get_session() as session:
        agent = session.get(Agent, agent_id)
        return agent.to_dict() if agent else None


def set_agent_activity(agent_id: str, status: str, current_task: str) -> None:
    now = utc_now()
    with get_session() as session:
        agent = session.get(Agent, agent_id)
        if agent is not None:
            agent.status = status
            agent.current_task = current_task
            agent.updated_at = now


def create_conversation(agent_id: str, title: str) -> dict[str, Any]:
    now = utc_now()
    conversation_id = str(uuid4())
    safe_title = " ".join(title.split())[:72] or "New conversation"
    with get_session() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            raise ValueError("The selected employee does not exist.")
        conversation = Conversation(
            id=conversation_id,
            agent_id=agent_id,
            title=safe_title,
            created_at=now,
            updated_at=now,
        )
        session.add(conversation)
    return {
        "id": conversation_id,
        "agent_id": agent_id,
        "title": safe_title,
        "created_at": now,
        "updated_at": now,
    }


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    with get_session() as session:
        conv = session.get(Conversation, conversation_id)
        return conv.to_dict() if conv else None


def list_conversations(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with get_session() as session:
        stmt = (
            select(Conversation)
            .order_by(Conversation.updated_at.desc())
            .limit(safe_limit)
        )
        rows = session.scalars(stmt).all()
        return [c.to_dict() for c in rows]


def list_conversation_messages(conversation_id: str, limit: int = 40) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with get_session() as session:
        subq = (
            select(
                ConversationMessage.id,
                ConversationMessage.conversation_id,
                ConversationMessage.role,
                ConversationMessage.content,
                ConversationMessage.created_at,
                ConversationMessage.order_index,
            )
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(
                ConversationMessage.created_at.desc(),
                ConversationMessage.order_index.desc(),
                ConversationMessage.id.desc(),
            )
            .limit(safe_limit)
            .subquery()
        )
        stmt = select(subq).order_by(
            subq.c.created_at.asc(),
            subq.c.order_index.asc(),
            subq.c.id.asc(),
        )
        rows = session.execute(stmt).fetchall()
        return [
            {
                "id": row.id,
                "conversation_id": row.conversation_id,
                "role": row.role,
                "content": row.content,
                "order_index": row.order_index,
                "created_at": row.created_at,
            }
            for row in rows
        ]


def add_conversation_message(conversation_id: str, role: str, content: str) -> dict[str, Any]:
    now = utc_now()
    message_id = str(uuid4())
    with get_session() as session:
        conv = session.get(Conversation, conversation_id)
        if conv is None:
            raise ValueError("Conversation not found.")

        max_order = session.scalar(
            select(func.coalesce(func.max(ConversationMessage.order_index), 0))
            .where(ConversationMessage.conversation_id == conversation_id)
        ) or 0
        order_index = max_order + 1

        message = ConversationMessage(
            id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            order_index=order_index,
            created_at=now,
        )
        session.add(message)
        conv.updated_at = now
    return {
        "id": message_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "order_index": order_index,
        "created_at": now,
    }


def get_or_create_runtime_conversation(
    agent_id: str,
    session_id: str,
    title: str = "Hermes3D conversation",
) -> str:
    """Persist the mapping from a Hermes3D session key to an AgentHQ conversation."""
    safe_session_id = session_id.strip()[:200]
    if not safe_session_id:
        raise ValueError("Runtime session ID is required.")
    now = utc_now()
    with get_session() as session:
        agent = session.get(Agent, agent_id)
        if agent is None:
            raise ValueError("The selected employee does not exist.")

        existing = session.get(RuntimeSession, safe_session_id)
        if existing:
            if existing.agent_id != agent_id:
                raise ValueError("Runtime session belongs to a different employee.")
            conv = session.get(Conversation, existing.conversation_id)
            if conv:
                existing.updated_at = now
                return str(existing.conversation_id)
            session.delete(existing)
            session.flush()

        conversation_id = str(uuid4())
        safe_title = " ".join(title.split())[:72] or "Hermes3D conversation"
        conversation = Conversation(
            id=conversation_id,
            agent_id=agent_id,
            title=safe_title,
            created_at=now,
            updated_at=now,
        )
        runtime_session = RuntimeSession(
            session_id=safe_session_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            created_at=now,
            updated_at=now,
        )
        session.add(conversation)
        session.add(runtime_session)
        return conversation_id
