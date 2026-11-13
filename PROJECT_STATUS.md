# AgentHQ implementation status

Current version: **0.3.0 — AI Employee Conversations**

## Working foundations
- React + TypeScript + Vite application shell with the premium responsive UI.
- Interactive React Three Fiber office with selectable employee figures.
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

## Safety and privacy boundary
The backend binds to `127.0.0.1:8000`; conversations and employee records are stored on the local machine. This phase does not execute shell commands, modify files, browse the live internet, deploy applications or autonomously complete tasks. Role prompts explicitly tell employees not to claim that they performed those actions. Later execution capabilities must use scoped permissions, explicit approvals and audit logs.
