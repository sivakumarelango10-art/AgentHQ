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
