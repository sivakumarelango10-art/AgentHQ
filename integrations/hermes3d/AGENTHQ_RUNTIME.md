# AgentHQ runtime for Hermes3D

AgentHQ exposes a compatibility API for Hermes3D Custom backend. The adapter runs inside the existing FastAPI service and keeps SQLite + Ollama as the source of truth.

## Architecture
- Hermes3D Studio: http://127.0.0.1:3000
- AgentHQ frontend: http://127.0.0.1:5173
- AgentHQ FastAPI: http://127.0.0.1:8000
- Ollama: http://127.0.0.1:11434

Hermes3D sends runtime requests to AgentHQ through its same-origin server proxy. No second database or agent framework is created.

## Supported runtime contract
| Method | Purpose |
|---|---|
| GET /health | Runtime and Ollama health |
| GET /state | Agent roster and runtime metadata |
| GET /registry | Configured local model registry |
| POST /v1/chat/completions | Role-aware non-streaming employee chat |

Each AgentHQ employee is published under a stable name-derived key: Atlas -> atlas, Kiran -> kiran, etc. Hermes3D currently derives display names from these keys. Incoming chat is mapped back to the real SQLite employee ID.

## Persistent chat mapping
Hermes3D sends a session key in session_id / conversation_id. AgentHQ persists a mapping from that key to the existing SQLite conversation in runtime_sessions. Repeated messages reuse the same conversation and retain the existing employee system prompt and message history.

Only the server-configured AgentHQ model is invoked. A model supplied by Hermes3D cannot select an arbitrary model.

## Enable Hermes3D
1. Start Ollama.
2. Start AgentHQ FastAPI:

   ```powershell
   cd E:\AgentHQ\backend
   Set-ExecutionPolicy -Scope Process Bypass -Force
   .\run.ps1
   ```

3. Confirm http://127.0.0.1:8000/health, /state and /registry.
4. Start Hermes3D in a separate terminal:

   ```powershell
   cd E:\Hermes3D
   npm run dev
   ```

5. In Hermes3D runtime/backend settings, choose Custom backend / Custom runtime and set the URL to http://127.0.0.1:8000.
6. Leave the token empty unless an authenticated reverse proxy is separately configured. Choose Custom backend, not Demo backend.

In local production mode, add this to E:\Hermes3D\.env and restart Studio:

```dotenv
CUSTOM_RUNTIME_ALLOWLIST=127.0.0.1,localhost
```

Do not bind the AgentHQ development API to a public interface. These local development routes have no authentication.

## PowerShell smoke tests
Show the real employee roster:

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/state).active
```

Show the registered model:

```powershell
(Invoke-RestMethod http://127.0.0.1:8000/registry).models
```

Send a smoke-test message to Atlas (this creates a persistent conversation):

```powershell
$body = @{
  model = "qwen3:4b"
  stream = $false
  role = "atlas"
  lane = "atlas"
  session_id = "agent:atlas:main"
  conversation_id = "agent:atlas:main"
  messages = @(@{ role = "user"; content = "Introduce yourself as the AgentHQ CEO Orchestrator." })
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/chat/completions" -Method Post -ContentType "application/json" -Body $body
```

## Current limitations
- Hermes3D custom runtime session state is held in its Studio process; AgentHQ conversation contents are persisted in SQLite.
- The first integration supports roster, model metadata and chat. It does not yet map AgentHQ tasks into Hermes3D Kanban, stream tokens, or map approvals/files/cron.
- Chat uses Ollama non-streaming responses.
- Queued tasks are not executed; no shell commands or tools are exposed.
- Employee status comes from AgentHQ records; task-driven walking and room transitions are future work.

## Data and safety
- Existing employees, tasks and conversations are not deleted or migrated.
- The adapter uses the existing AgentHQ chat logic and employee-specific system prompt.
- It does not expose filesystem, terminal, arbitrary URL fetch, deployment, or external network tools.
- Do not expose the unauthenticated development FastAPI service to a LAN or public network.