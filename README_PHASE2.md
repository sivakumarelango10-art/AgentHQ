# AgentHQ Phase 2 — Persistent Employees & Task Inbox

This update adds the first real management layer to AgentHQ. It replaces the hard-coded employee API with SQLite-backed employee records and adds task creation, assignment, listing, and cancellation.

## Scope of this milestone

Included:
- SQLite database stored at `backend/data/agenthq.db` by default.
- Six initial employee records seeded on first startup.
- Add employee form and persistent employee directory.
- Create task form with title, description, priority, and optional employee assignment.
- Task inbox with queued/cancelled states and cancellation.
- Frontend refresh/polling so changes appear in the office dashboard.
- Additional employee markers receive deterministic positions in the 3D office.

Not included yet:
- AI reasoning or employee chat.
- Automatic task claiming, execution, completion, or retries.
- Agent-to-agent delegation, tool use, file editing, or terminal commands.
- Real human character rigs or task-driven walking/typing animations.

A task marked **Queued** is only saved in the local database. It has not been executed by an AI employee.

## Apply the update on Windows

1. Stop both running PowerShell terminals with `Ctrl+C`.
2. Make a backup of your current project folder. For example:

   ```powershell
   Copy-Item E:\AgentHQ E:\AgentHQ_backup_phase1 -Recurse
   ```

   If you already have a `backend\data\agenthq.db`, back it up too. The update does not include or overwrite that database.

3. Extract `AgentHQ_Phase2_Update.zip` directly into `E:\AgentHQ` and choose **Replace files** when Windows asks. The ZIP contains only changed/new source files and this README; it does not contain `node_modules`, `.venv`, or your local `.env` files.

4. Start the backend in PowerShell window 1:

   ```powershell
   cd E:\AgentHQ\backend
   .\run.ps1
   ```

   On first run, the backend creates `backend\data\agenthq.db` and inserts the six default employees. If your backend virtual environment already exists, the runner reuses it and checks the requirements.

5. Start the frontend in PowerShell window 2:

   ```powershell
   cd E:\AgentHQ\frontend
   npm run dev
   ```

   No new frontend package was added in this phase, so the existing `node_modules` should be reused. If Vite reports a missing dependency, run `npm install` in the frontend folder and retry.

6. Open `http://127.0.0.1:5173` and refresh once.

## Phase 2 test checklist

1. Open **Employees**. You should see six employees loaded from SQLite.
2. Select **Add employee**, add a test employee, and save.
3. Confirm the employee count increases and the new employee appears in the directory and team panel.
4. Refresh the browser. Confirm the new employee remains.
5. Open **Tasks** and select **Create task**.
6. Enter a title, choose a priority, assign the test employee, and save.
7. Confirm the task appears with **Queued · not started**.
8. Refresh the browser. Confirm the task remains and the assignee is still correct.
9. Cancel the queued task and confirm its status changes to **Cancelled**.
10. Restart the backend and refresh. Confirm the employee and task records remain.

## API endpoints

- `GET /api/health` — backend, database, and Ollama status.
- `GET /api/agents` — persisted employee directory.
- `POST /api/agents` — create an employee.
- `GET /api/tasks` — list tasks.
- `GET /api/tasks?status=queued` — list queued tasks.
- `POST /api/tasks` — create a queued task.
- `PATCH /api/tasks/{task_id}/cancel` — cancel a queued task.
- `GET /docs` — interactive local API documentation.

The backend continues to bind to `127.0.0.1:8000`. The SQLite database is local to your computer. The frontend does not call a hosted AI provider.

## Troubleshooting

- **Backend offline:** Check that the backend terminal still shows Uvicorn running at `http://127.0.0.1:8000`.
- **Ollama disconnected:** Employee and task management still work. Ollama will be needed for the next AI reasoning milestone.
- **New employee does not appear:** Click the refresh icon in the top bar or reload the page, then check `http://127.0.0.1:8000/api/agents`.
- **Task not saved:** Open the backend terminal and inspect the error. You can also inspect the request/response at `http://127.0.0.1:8000/docs`.
- **Frontend build errors:** Run `npm run build` in `E:\AgentHQ\frontend` and share the complete output. Do not delete `node_modules` or the SQLite database as a first troubleshooting step.

## Local safety boundary

This phase only stores employee metadata and task descriptions. It does not execute shell commands, modify arbitrary project files, access the public internet, or deploy anything. Those capabilities will be introduced separately with explicit permission gates and audit logs.
