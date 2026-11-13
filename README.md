# AgentHQ — Local AI Company Runtime

AgentHQ is the local company runtime behind a Hermes3D-powered AI office. **Hermes3D is the primary application and user interface**; AgentHQ provides the employee directory, local model routing, SQLite persistence, conversations and the runtime API.

The intended daily experience is the native Hermes3D Studio at `http://127.0.0.1:3000/office`, connected to the AgentHQ FastAPI service at `http://127.0.0.1:8000`. The older Vite application in `frontend/` is retained as a legacy/reference dashboard while its remaining useful features are migrated. Do not launch it as a second product shell for normal use.

## Architecture

```text
Browser
  |
  v
Hermes3D Studio (Next.js, Three.js, React Three Fiber)
  |  Custom runtime provider
  v
AgentHQ FastAPI (loopback only)
  |---- SQLite: employees, tasks, conversations, runtime sessions
  |---- Ollama: qwen3:4b
  |---- Future: guarded task workers and audit records
```

Hermes3D is the visual and interaction foundation. Avoid rebuilding its office, chat, panels or visual language in the legacy Vite app. AgentHQ remains the source of truth for company data and AI runtime behavior.

## Local hardware target

Initial target: Windows 10/11, Intel i7-11850H, 32 GB RAM, NVIDIA RTX A2000 Laptop GPU (4 GB VRAM). Ollama is expected at `http://127.0.0.1:11434` with `qwen3:4b` installed.

## 1. Recommended startup

The repository includes a Windows PowerShell 5.1 helper that starts only the AgentHQ backend and Hermes3D. It does **not** start the legacy Vite frontend.

From PowerShell:

```powershell
cd E:\AgentHQ
Set-ExecutionPolicy -Scope Process Bypass -Force
.\start-agenthq-stack.ps1
```

If Hermes3D is installed somewhere other than `E:\Hermes3D`:

```powershell
.\start-agenthq-stack.ps1 -Hermes3DPath "D:\Projects\Hermes3D"
```

The script:
- checks Ollama and the configured model;
- starts AgentHQ FastAPI if it is not already running;
- starts Hermes3D Studio if it is not already serving the office;
- refuses to silently reuse an unrelated process on ports 8000 or 3000;
- opens the Hermes3D office in the browser.

Daily entry point: **`http://127.0.0.1:3000/office`**.

## 2. Hermes3D Custom runtime connection

On the first connection for the canonical Hermes3D browser origin:

1. Choose **Custom backend** (not Demo, Hermes or Hermes3D gateway).
2. Set the upstream URL to `http://127.0.0.1:8000`.
3. Leave the token empty for this loopback-only development setup.
4. Connect and verify the seven AgentHQ employees and local model.

The backend exposes the current Custom runtime compatibility endpoints:

- `GET /health`
- `GET /state`
- `GET /registry`
- `POST /v1/chat/completions`

The AgentHQ API is intentionally bound to `127.0.0.1`. Do not expose it to a LAN or public internet without authentication, request authorization and a security review.

## 3. Manual service startup

Use this only when troubleshooting the startup helper.

**Terminal 1 — AgentHQ backend**

```powershell
cd E:\AgentHQ\backend
Set-ExecutionPolicy -Scope Process Bypass -Force
.\run.ps1
```

**Terminal 2 — Hermes3D Studio**

```powershell
cd E:\Hermes3D
npm run dev
```

Open `http://127.0.0.1:3000/office`.

Do not start `E:\AgentHQ\frontend` for normal use. Its Vite app on port 5173 is retained temporarily for reference and for management features not yet migrated into Hermes3D.

## 4. Ollama

Check the installed model:

```powershell
ollama list
ollama show qwen3:4b
```

Useful endpoints:

- `http://127.0.0.1:8000/health` — Hermes3D Custom runtime health.
- `http://127.0.0.1:8000/state` — AgentHQ runtime and employee roster.
- `http://127.0.0.1:8000/registry` — configured model registry.
- `http://127.0.0.1:8000/api/health` — AgentHQ application health.
- `http://127.0.0.1:8000/api/ollama/status` — Ollama model status.
- `http://127.0.0.1:8000/docs` — FastAPI documentation.

The model is local; AgentHQ does not need a hosted AI API key.

## 5. Current capability boundary

Working foundations:
- SQLite-backed employee, task and conversation records.
- AgentHQ Custom runtime compatibility for roster discovery and non-streaming chat.
- Runtime session IDs mapped to persistent AgentHQ conversation records.
- Local Ollama generation with a bounded context and request timeout.
- Hermes3D provides the office, chat UI, 3D interactions and native Studio panels.

Not yet complete:
- Hermes3D session history fully hydrated from SQLite after browser restart.
- Normalized streaming events and live presence updates.
- Single-source task/Kanban synchronization between Hermes3D and AgentHQ.
- Agent-to-agent delegation, task claiming, execution, completion, retries and result verification.
- Sandboxed file/terminal tools, approvals and execution audit records.

A queued task is a saved record, not completed AI work. Do not describe AgentHQ as autonomous until the worker lifecycle, permissions and audit layers are implemented and tested.

## 6. Repository layout

```text
AgentHQ/
  backend/                     FastAPI, SQLite and Ollama runtime
  frontend/                    Legacy Vite dashboard (not the primary UI)
  integrations/hermes3d/       Runtime contract and integration notes
  docs/                        Architecture audit and migration plan
  workspace/                   Future isolated agent workspace
  start-agenthq-stack.ps1      Hermes3D-first local startup helper

E:\Hermes3D/                   Hermes3D Studio working tree (separate checkout)
```

Hermes3D is MIT-licensed. Preserve its license and third-party asset notices when maintaining an owned fork or copying any upstream source.

## 7. Safety and data preservation

- Keep AgentHQ FastAPI on loopback (`127.0.0.1`).
- Back up `backend\data\agenthq.db` before schema or employee changes.
- Do not overwrite the local Hermes3D working tree before inspecting `git status` and `git diff`; it contains an AgentHQ compatibility patch for session behavior.
- File writes, shell execution, external network access, deployment and autonomous task execution must remain disabled until scoped permissions, approval gates, isolation and audit logs are implemented.
