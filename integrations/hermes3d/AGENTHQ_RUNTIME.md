# AgentHQ runtime for Hermes3D Studio

Hermes3D is the primary application and UI. AgentHQ FastAPI is the local company runtime and the authoritative data service. Do not use the AgentHQ Vite frontend as an outer shell or embed Hermes3D in an iframe for normal operation.

## Canonical local architecture

| Service | Purpose | Address |
|---|---|---|
| Hermes3D Studio | Primary browser application: office, avatars, chat, Studio panels and settings | `http://localhost:3000/office` |
| AgentHQ FastAPI | Employee, chat, task and runtime API | `http://127.0.0.1:8000` |
| Ollama | Local model runtime | `http://127.0.0.1:11434` |
| AgentHQ legacy Vite UI | Retained only for reference during migration; not started in the normal workflow | `http://127.0.0.1:5173` |

The browser connects to Hermes3D directly. Hermes3D's Custom runtime server-side proxy forwards runtime requests to AgentHQ. SQLite remains the single durable source of truth. No second employee database or AI framework is created.

## Current Custom runtime contract

| Method | Purpose |
|---|---|
| `GET /health` | AgentHQ and Ollama health |
| `GET /state` | Runtime identity, active employee keys and model metadata |
| `GET /registry` | Configured local model registry |
| `POST /v1/chat/completions` | Role-aware non-streaming employee chat |

AgentHQ publishes stable name-derived runtime IDs (Atlas → `atlas`, Kiran → `kiran`, etc.) and maps incoming chat requests back to SQLite employee IDs. Only the server-configured model is invoked; a browser-supplied model cannot select an arbitrary Ollama model.

## Start the stack

Recommended from PowerShell 5.1:

```powershell
cd E:\AgentHQ
Set-ExecutionPolicy -Scope Process Bypass -Force
.\start-agenthq-stack.ps1
```

If Hermes3D is in a different folder:

```powershell
.\start-agenthq-stack.ps1 -Hermes3DPath "D:\Projects\Hermes3D"
```

The helper starts AgentHQ FastAPI and Hermes3D if they are not already running. It does not start the legacy Vite UI. Manual startup is documented in the root README.

## Configure Hermes3D once

Use a single canonical browser origin: `http://127.0.0.1:3000`.

In Hermes3D's connection wizard/settings:
1. Select **Custom backend**.
2. Set the URL to `http://127.0.0.1:8000`.
3. Leave the token empty for the loopback-only development setup.
4. Connect and verify the roster/model.

Browser storage is origin-scoped. Settings saved for `localhost:3000`, `127.0.0.1:3000` and the old embedded `127.0.0.1:5173` origin are separate. Always use the canonical `127.0.0.1:3000` address after configuration.

For a production-mode local Hermes3D process, add this to `E:\Hermes3D\.env` and restart Studio:

```dotenv
CUSTOM_RUNTIME_ALLOWLIST=127.0.0.1,localhost
```

Do not bind AgentHQ's development API to a LAN or public interface. The local development routes do not have authentication.

## Smoke tests

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/health)
(Invoke-RestMethod http://127.0.0.1:8000/state).active
(Invoke-RestMethod http://127.0.0.1:8000/registry).models
```

A chat smoke test creates a persistent SQLite conversation:

```powershell
$body = @{
  model = "qwen3:4b"
  stream = $false
  role = "atlas"
  lane = "atlas"
  session_id = "agent:atlas:main"
  conversation_id = "agent:atlas:main"
  messages = @(@{ role = "user"; content = "Introduce yourself as the AgentHQ AI Orchestrator." })
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/chat/completions" -Method Post -ContentType "application/json" -Body $body
```

## Current limitations

The Custom runtime compatibility layer is intentionally partial:
- employee roster and model metadata are exposed;
- chat uses non-streaming Ollama responses and persists the AgentHQ conversation;
- Hermes3D session list/history is not yet fully hydrated from AgentHQ SQLite after a Studio restart;
- AgentHQ queued tasks are not yet mapped to Hermes3D Kanban as one authoritative board;
- streaming events, approvals, tool execution, files, cron and autonomous task workers are not implemented;
- queued tasks are records only and are not executed.

Do not advertise autonomous execution until the runtime contract, task state machine, permission checks, workers and audit trail exist and pass end-to-end tests.

## Data ownership and safety

- AgentHQ SQLite owns employees, tasks, conversations and runtime-session mappings.
- Hermes3D owns UI state and presentation only.
- The AgentHQ configured Ollama model is the only model used for chat.
- No shell, filesystem, arbitrary URL-fetch, deployment or external network tools are exposed by the current chat endpoint.
- Back up `backend\data\agenthq.db` before schema migrations.
- Preserve the local Hermes3D `sessions.patch` compatibility change until it is inspected and ported into an owned, versioned fork/patch set.
