from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "AgentHQ API")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")

# Phase 1 preview employees. Persistent employee records are introduced in a later phase.
AGENTS: list[dict[str, Any]] = [
    {"id": "ceo", "name": "Atlas", "role": "AI Orchestrator", "department": "Management", "status": "working"},
    {"id": "pm", "name": "Mira", "role": "Project Manager", "department": "Management", "status": "working"},
    {"id": "dev", "name": "Arin", "role": "Software Engineer", "department": "Engineering", "status": "working"},
    {"id": "design", "name": "Nia", "role": "UI/UX Designer", "department": "Design", "status": "idle"},
    {"id": "research", "name": "Ira", "role": "Research Analyst", "department": "Research", "status": "idle"},
    {"id": "qa", "name": "Dev", "role": "QA Engineer", "department": "Quality", "status": "meeting"},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title=APP_NAME, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
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
        "ollama_connected": ollama_connected,
        "model": found_model or (OLLAMA_MODEL if ollama_connected else None),
    }


@app.get("/api/agents")
async def list_agents() -> dict[str, Any]:
    return {"items": AGENTS, "total": len(AGENTS), "mode": "preview"}


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
    """Small local-only event channel; task events will be added in later phases."""
    await websocket.accept()
    await websocket.send_json({"type": "connected", "message": "AgentHQ office event channel ready"})
    try:
        while True:
            message = await websocket.receive_json()
            await websocket.send_json({"type": "ack", "received": message})
    except WebSocketDisconnect:
        return
