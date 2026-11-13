# AgentHQ implementation status

Current version: **0.5.0 — Hermes3D-first architecture**

## Product architecture decision

Hermes3D is the primary user-facing application and visual foundation. AgentHQ FastAPI + SQLite + Ollama is the authoritative company runtime and data service. The older AgentHQ Vite/React application is retained as a legacy/reference dashboard during migration; it is not the normal startup target and must not be nested around Hermes3D.

Daily browser entry: `http://localhost:3000/office`.

Start both services with `E:\AgentHQ\start-agenthq-stack.ps1`. See `README.md` and `docs/HERMES3D_FIRST_AUDIT_AND_MIGRATION.md`.

## Working foundations
- Legacy React + TypeScript + Vite management shell and React Three Fiber office preview retained for reference during migration.
- Hermes3D native Studio is the intended product UI; its actual 3D office, native panels and chat should be preserved rather than recreated in the Vite shell.
- Persistent employee directory and task queue stored in local SQLite.
- Add employee workflow with department, room and color fields.
- Create, assign, list and cancel queued tasks.
- FastAPI backend with local Ollama health checks.
- Local Qwen3 model integration through Ollama.
- Role-aware AI employee chat using each employee's name, role, department and office.
- Persistent conversations and message history in SQLite.
- Conversation workspace with employee selection, recent chats, message history and local-model status.
- Chat responses update the employee's working/idle status while the model is responding.

## Phase 3 scope and boundaries
- AI employees can reason about requests, discuss plans, answer questions and draft text/code in chat.
- The last 16 messages in a conversation are included as context.
- Conversation history is stored locally in `backend/data/agenthq.db`.
- The backend calls the locally configured Ollama model; no hosted AI provider or API key is required.
- Chat requests have a bounded 180-second timeout and use a 4K context setting by default.

Not implemented yet:
- Automatic task claiming, execution, completion, retries or progress reporting.
- Agent-to-agent delegation and autonomous scheduling.
- Sandboxed file tools, terminal tools, approvals and audit logs.
- Live web research or access to local project files.
- Rigged character models and task-driven walking/typing animations.
- Conversation search, deletion, export and configurable memory management.

A task marked **Queued** is still only saved in the local database. Chatting with an employee does not execute queued tasks.

## Local run commands

Backend:
```powershell
cd E:\AgentHQ\backend
Set-ExecutionPolicy -Scope Process Bypass -Force
.\run.ps1
```

Frontend:
```powershell
cd E:\AgentHQ\frontend
npm run dev
```

URLs:
- Frontend: http://127.0.0.1:5173
- API health: http://127.0.0.1:8000/api/health
- API docs: http://127.0.0.1:8000/docs

Ollama:
- Configured model: `qwen3:4b` by default.
- The model must be installed locally and Ollama must be running.
- Set `OLLAMA_MODEL` or `OLLAMA_BASE_URL` in `backend/.env` to override defaults.

## Phase 3 API endpoints
- `GET /api/conversations` — list recent conversations.
- `GET /api/conversations/{conversation_id}/messages` — retrieve stored messages.
- `POST /api/agents/{agent_id}/chat` — send a message to one employee and receive a local-model response.

Example chat request:
```json
{
  "message": "Help me plan the next steps for AgentHQ.",
  "conversation_id": null
}
```

## Hermes3D custom runtime integration
- AgentHQ exposes GET /health, GET /state, GET /registry, and POST /v1/chat/completions for Hermes3D's Custom backend profile.
- Hermes3D roster entries are generated from real SQLite employee records using stable name-derived runtime IDs.
- The configured local Ollama model is exposed through the runtime registry.
- Hermes3D session IDs are mapped to persistent AgentHQ conversation rows using the runtime_sessions table.
- Chat requests are routed through the existing role-aware AgentHQ Ollama chat handler; no second agent database is created.
- Streaming chat, Kanban task synchronization, tool approvals, files, cron and autonomous execution are not yet supported.

## Safety and privacy boundary
The backend binds to `127.0.0.1:8000`; conversations and employee records are stored on the local machine. This phase does not execute shell commands, modify files, browse the live internet, deploy applications or autonomously complete tasks. Role prompts explicitly tell employees not to claim that they performed those actions. Later execution capabilities must use scoped permissions, explicit approvals and audit logs.


## 3D Office Rendering Refinement (Hermes3D-inspired)

- Improved the React Three Fiber office environment with layered timber floor surfaces, architectural perimeter walls, glass partitions, mullions, refined lighting and a modern lounge area.
- Added cinematic ACES tone mapping and city environment lighting.
- Added Balanced and Ultra render-quality controls; Balanced is the default and uses reduced pixel ratio and 1024 shadow maps for laptop GPUs.
- Preserved AgentHQ's room-aware employee positioning and existing API/database/AI logic.
- No Hermes3D runtime, gateway, server, or agent backend has been imported. AgentHQ remains a standalone FastAPI + Ollama application.
- Added third-party notice documenting the Hermes3D MIT-licensed inspiration.

Validation required:
- Frontend production build and TypeScript compile.
- Browser test for camera controls, employee selection, room labels, and layout.
- Performance check on the RTX A2000 4GB at Balanced; Ultra is optional and should be used only after measuring frame rate.
