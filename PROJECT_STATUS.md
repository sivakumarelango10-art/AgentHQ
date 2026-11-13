# AgentHQ implementation status

Current version: **0.2.0** (UI refresh)

## Working foundations
- React + TypeScript + Vite application shell.
- Interactive React Three Fiber office with procedural floor, walls, partitions, desks, chairs, meeting table and plants.
- Selectable 3D employee figures and name tags.
- Employee directory backed by local SQLite records.
- Add employee workflow with department, room and color fields.
- Task creation with title, description, priority and optional employee assignment.
- Task inbox with queued/cancelled states and cancellation.
- Frontend refresh/polling for local employee and task data.
- FastAPI health endpoint, SQLite status and local Ollama reachability checks.
- Local WebSocket event channel foundation.
- Local Qwen3 model available through Ollama.

## Current UI refinement
The premium UI redesign has been merged into `main`:
- Higher-contrast typography and clearer hierarchy.
- More consistent spacing, larger controls and accessible focus states.
- Refined sidebar, navigation, workspace header and metric cards.
- Larger office viewport with a more balanced employee panel.
- Improved employee directory and task inbox cards.
- Reworked dialogs with a darker, opaque backdrop so 3D labels do not bleed through.
- Responsive layouts for desktop, tablet and mobile.
- No paid UI libraries or remote runtime dependencies.

## Not implemented yet
- AI reasoning/chat initiated from the dashboard.
- Automatic task claiming, execution, completion, retries or progress reporting.
- Agent-to-agent delegation and autonomous scheduling.
- Sandboxed file tools, terminal tools, approvals and audit logs.
- Rigged human character models and task-driven walking/typing animations.
- Conversation history and full settings screens.

A task marked **Queued** is only saved in the local database. It has not been executed by an AI employee.

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

## Safety boundary
The current phase stores employee metadata and task descriptions locally. It does not yet execute arbitrary shell commands, modify arbitrary project files, access the public internet on behalf of agents, or deploy projects. Execution features will be introduced separately with scoped permissions, explicit approvals and audit logs.
