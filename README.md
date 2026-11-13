# AgentHQ — 3D AI Startup Office (starter)

AgentHQ is a local-first prototype for a 3D startup office inhabited by specialized AI employees. This starter contains **Phase 1**: the interactive office scene, management UI shell, and a small local FastAPI health/API service.

> Important: the employees and metrics shown in this Phase 1 starter are preview data. The app does not yet autonomously execute tasks. AI orchestration, employee memory, tool permissions, persistent tasks, and real task-driven animation are later milestones.

## Hardware target

Initial target: Windows 10/11, Intel i7-11850H, 32 GB RAM, NVIDIA RTX A2000 Laptop GPU (4 GB VRAM). The frontend is GPU-rendered in the browser. Ollama is expected at `http://127.0.0.1:11434` with `qwen3:4b` already installed.

## 1. Folder layout

```text
AgentHQ/
  frontend/        React + TypeScript + Vite + React Three Fiber
  backend/         FastAPI local API and Ollama health check
  assets/models/   Add licensed GLB/GLTF models here in a later phase
  workspace/       Isolated working folder for agent-created files
```

## 2. Start the backend

Open PowerShell:

```powershell
cd E:\AgentHQ\backend
Set-ExecutionPolicy -Scope Process Bypass
.\run.ps1
```

The API listens only on `127.0.0.1:8000`.

Useful endpoints:

- `http://127.0.0.1:8000/api/health`
- `http://127.0.0.1:8000/api/agents`
- `http://127.0.0.1:8000/api/ollama/status`
- `http://127.0.0.1:8000/docs`
- WebSocket: `ws://127.0.0.1:8000/ws/office`

## 3. Start the frontend

Open a **second** PowerShell window:

```powershell
cd E:\AgentHQ\frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

If npm reports a dependency or TypeScript issue, copy the full terminal output before changing package versions.

## 4. Ollama

Make sure Ollama is running and that the model exists:

```powershell
ollama list
ollama show qwen3:4b
```

The backend checks Ollama's local `/api/tags` endpoint. It does not send data to a hosted AI provider.

## 5. Current Phase 1 controls

- Drag to orbit the camera; scroll to zoom.
- Use Overview / Explore to change the camera position.
- Click an employee in the 3D scene or team list to select them.
- Toggle the team panel.
- The backend indicator changes when the local API starts.

## 6. Next milestones

1. Replace preview employees with SQLite-backed employee records.
2. Add a real task inbox and CEO assignment flow.
3. Connect the Orchestrator to Ollama using `/api/chat`.
4. Add a bounded task queue and agent concurrency controls.
5. Add sandboxed tools, approval gates, logs, and result artifacts.
6. Drive character states and office movement from real backend events.

## Local safety boundary

The initial API binds to loopback only. Later agents should operate only within `workspace/agent-generated-files` by default. Shell execution, file deletion, external network access, and deployment should require explicit permission and audit logs.
