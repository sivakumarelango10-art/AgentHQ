from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import db

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "AgentHQ API")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=48)
    role: str = Field(min_length=1, max_length=80)
    department: str = Field(min_length=1, max_length=48)
    room: str = Field(min_length=1, max_length=64)
    color: str = Field(default="#8c9bc8", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("name", "role", "department", "room")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty.")
        return value


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2500)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    assigned_agent_id: str | None = Field(default=None, max_length=64)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Task title cannot be empty.")
        return value

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return value.strip()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title=APP_NAME, version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


async def get_ollama_status() -> tuple[bool, str | None]:
    """Check the local Ollama tags endpoint without blocking the API process."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.5)) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            response.raise_for_status()
            payload = response.json()
        available = [item.get("name", "") for item in payload.get("models", [])]
        selected_model = next(
            (name for name in available if name == OLLAMA_MODEL or name.startswith(f"{OLLAMA_MODEL}:")),
            None,
        )
        return True, selected_model
    except (httpx.HTTPError, ValueError, TypeError):
        return False, None


@app.get("/api/health")
async def health() -> dict[str, Any]:
    ollama_connected, found_model = await get_ollama_status()
    return {
        "status": "ok" if ollama_connected else "degraded",
        "app": APP_NAME,
        "database": "connected",
        "ollama_connected": ollama_connected,
        "model": found_model or (OLLAMA_MODEL if ollama_connected else None),
    }


@app.get("/api/agents")
async def get_agents() -> dict[str, Any]:
    items = db.list_agents()
    return {"items": items, "total": len(items), "mode": "sqlite"}


@app.post("/api/agents", status_code=201)
async def post_agent(payload: AgentCreate) -> dict[str, Any]:
    record = db.create_agent(payload.model_dump())
    return {"item": record}


@app.get("/api/tasks")
async def get_tasks(status: Literal["queued", "cancelled"] | None = Query(default=None)) -> dict[str, Any]:
    items = db.list_tasks(status=status)
    return {"items": items, "total": len(items)}


@app.post("/api/tasks", status_code=201)
async def post_task(payload: TaskCreate) -> dict[str, Any]:
    try:
        record = db.create_task(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"item": record}


@app.patch("/api/tasks/{task_id}/cancel")
async def patch_cancel_task(task_id: str) -> dict[str, Any]:
    task = db.cancel_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task.get("status") != "cancelled":
        raise HTTPException(status_code=409, detail="Only queued tasks can be cancelled in this milestone.")
    return {"item": task}


@app.get("/api/ollama/status")
async def ollama_status() -> dict[str, Any]:
    connected, model = await get_ollama_status()
    return {
        "connected": connected,
        "base_url": OLLAMA_BASE_URL,
        "configured_model": OLLAMA_MODEL,
        "model_found": model is not None,
        "model": model,
    }


@app.websocket("/ws/office")
async def office_socket(websocket: WebSocket) -> None:
    """Local event channel; live task/agent events will be added with execution workers."""
    await websocket.accept()
    await websocket.send_json({"type": "connected", "message": "AgentHQ office event channel ready"})
    try:
        while True:
            message = await websocket.receive_json()
            await websocket.send_json({"type": "ack", "received": message})
    except WebSocketDisconnect:
        return
