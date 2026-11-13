from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

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
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def database_path() -> Path:
    configured = os.getenv("AGENTHQ_DB_PATH")
    path = Path(configured).expanduser() if configured else DEFAULT_DB_PATH
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


@contextmanager
def connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                department TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'idle'
                    CHECK (status IN ('working', 'idle', 'meeting', 'offline')),
                room TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#8c9bc8',
                current_task TEXT NOT NULL DEFAULT 'Available — awaiting assignment',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT 'normal'
                    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
                status TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'cancelled')),
                assigned_agent_id TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (assigned_agent_id) REFERENCES agents(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_assigned_agent ON tasks(assigned_agent_id);

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS conversation_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_agent_updated
                ON conversations(agent_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
                ON conversation_messages(conversation_id, created_at);

            CREATE TABLE IF NOT EXISTS runtime_sessions (
                session_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            """
        )
        count = connection.execute("SELECT COUNT(*) AS total FROM agents").fetchone()["total"]
        if count == 0:
            now = utc_now()
            connection.executemany(
                """INSERT INTO agents
                   (id, name, role, department, status, room, color, current_task, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        agent["id"], agent["name"], agent["role"], agent["department"],
                        agent["status"], agent["room"], agent["color"], agent["current_task"], now, now,
                    )
                    for agent in SEED_AGENTS
                ],
            )


def list_agents() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM agents ORDER BY CASE department "
            "WHEN 'Management' THEN 0 WHEN 'Engineering' THEN 1 WHEN 'Design' THEN 2 "
            "WHEN 'Research' THEN 3 ELSE 4 END, created_at, name"
        ).fetchall()
        return [dict(row) for row in rows]


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
    with connect() as connection:
        connection.execute(
            """INSERT INTO agents
               (id, name, role, department, status, room, color, current_task, created_at, updated_at)
               VALUES (:id, :name, :role, :department, :status, :room, :color, :current_task, :created_at, :updated_at)""",
            record,
        )
    return record


def list_tasks(status: str | None = None) -> list[dict[str, Any]]:
    query = """SELECT tasks.*, agents.name AS assigned_agent_name, agents.role AS assigned_agent_role
               FROM tasks LEFT JOIN agents ON agents.id = tasks.assigned_agent_id"""
    params: tuple[Any, ...] = ()
    if status:
        query += " WHERE tasks.status = ?"
        params = (status,)
    query += " ORDER BY CASE tasks.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, tasks.created_at DESC"
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, params).fetchall()]


def create_task(payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    task_id = str(uuid4())
    with connect() as connection:
        if payload.get("assigned_agent_id"):
            agent = connection.execute(
                "SELECT id, name, role FROM agents WHERE id = ?",
                (payload["assigned_agent_id"],),
            ).fetchone()
            if agent is None:
                raise ValueError("The selected employee does not exist.")
            assigned_agent_name = agent["name"]
            assigned_agent_role = agent["role"]
        else:
            assigned_agent_name = None
            assigned_agent_role = None
        connection.execute(
            """INSERT INTO tasks
               (id, title, description, priority, status, assigned_agent_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)""",
            (
                task_id, payload["title"], payload.get("description", ""),
                payload.get("priority", "normal"), payload.get("assigned_agent_id"), now, now,
            ),
        )
    return {
        "id": task_id,
        "title": payload["title"],
        "description": payload.get("description", ""),
        "priority": payload.get("priority", "normal"),
        "status": "queued",
        "assigned_agent_id": payload.get("assigned_agent_id"),
        "assigned_agent_name": assigned_agent_name,
        "assigned_agent_role": assigned_agent_role,
        "created_at": now,
        "updated_at": now,
    }


def cancel_task(task_id: str) -> dict[str, Any] | None:
    now = utc_now()
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE tasks SET status = 'cancelled', updated_at = ? WHERE id = ? AND status = 'queued'",
            (now, task_id),
        )
        row = connection.execute(
            """SELECT tasks.*, agents.name AS assigned_agent_name, agents.role AS assigned_agent_role
               FROM tasks LEFT JOIN agents ON agents.id = tasks.assigned_agent_id WHERE tasks.id = ?""",
            (task_id,),
        ).fetchone()
        return dict(row) if row else None



def get_agent(agent_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return dict(row) if row else None


def set_agent_activity(agent_id: str, status: str, current_task: str) -> None:
    now = utc_now()
    with connect() as connection:
        connection.execute(
            "UPDATE agents SET status = ?, current_task = ?, updated_at = ? WHERE id = ?",
            (status, current_task, now, agent_id),
        )


def create_conversation(agent_id: str, title: str) -> dict[str, Any]:
    now = utc_now()
    conversation_id = str(uuid4())
    safe_title = " ".join(title.split())[:72] or "New conversation"
    with connect() as connection:
        agent = connection.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if agent is None:
            raise ValueError("The selected employee does not exist.")
        connection.execute(
            """INSERT INTO conversations (id, agent_id, title, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (conversation_id, agent_id, safe_title, now, now),
        )
    return {
        "id": conversation_id,
        "agent_id": agent_id,
        "title": safe_title,
        "created_at": now,
        "updated_at": now,
    }


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            """SELECT conversations.*, agents.name AS agent_name, agents.role AS agent_role
               FROM conversations JOIN agents ON agents.id = conversations.agent_id
               WHERE conversations.id = ?""",
            (conversation_id,),
        ).fetchone()
        return dict(row) if row else None


def list_conversations(limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with connect() as connection:
        rows = connection.execute(
            """SELECT conversations.*, agents.name AS agent_name, agents.role AS agent_role
               FROM conversations JOIN agents ON agents.id = conversations.agent_id
               ORDER BY conversations.updated_at DESC LIMIT ?""",
            (safe_limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_conversation_messages(conversation_id: str, limit: int = 40) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 100))
    with connect() as connection:
        rows = connection.execute(
            """SELECT id, conversation_id, role, content, created_at FROM (
                 SELECT id, conversation_id, role, content, created_at
                 FROM conversation_messages
                 WHERE conversation_id = ?
                 ORDER BY created_at DESC, rowid DESC
                 LIMIT ?
               ) ORDER BY created_at ASC, id ASC""",
            (conversation_id, safe_limit),
        ).fetchall()
        return [dict(row) for row in rows]


def add_conversation_message(conversation_id: str, role: str, content: str) -> dict[str, Any]:
    now = utc_now()
    message_id = str(uuid4())
    with connect() as connection:
        exists = connection.execute(
            "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if exists is None:
            raise ValueError("Conversation not found.")
        connection.execute(
            """INSERT INTO conversation_messages (id, conversation_id, role, content, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (message_id, conversation_id, role, content, now),
        )
        connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
    return {
        "id": message_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
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
    with connect() as connection:
        agent = connection.execute(
            "SELECT id FROM agents WHERE id = ?", (agent_id,)
        ).fetchone()
        if agent is None:
            raise ValueError("The selected employee does not exist.")

        existing = connection.execute(
            "SELECT agent_id, conversation_id FROM runtime_sessions WHERE session_id = ?",
            (safe_session_id,),
        ).fetchone()
        if existing:
            if existing["agent_id"] != agent_id:
                raise ValueError("Runtime session belongs to a different employee.")
            conversation = connection.execute(
                "SELECT id FROM conversations WHERE id = ?",
                (existing["conversation_id"],),
            ).fetchone()
            if conversation:
                connection.execute(
                    "UPDATE runtime_sessions SET updated_at = ? WHERE session_id = ?",
                    (now, safe_session_id),
                )
                return str(existing["conversation_id"])
            connection.execute(
                "DELETE FROM runtime_sessions WHERE session_id = ?",
                (safe_session_id,),
            )

        conversation_id = str(uuid4())
        safe_title = " ".join(title.split())[:72] or "Hermes3D conversation"
        connection.execute(
            """INSERT INTO conversations (id, agent_id, title, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (conversation_id, agent_id, safe_title, now, now),
        )
        connection.execute(
            """INSERT INTO runtime_sessions
               (session_id, agent_id, conversation_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (safe_session_id, agent_id, conversation_id, now, now),
        )
        return conversation_id
