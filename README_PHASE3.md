# AgentHQ Phase 3 — AI Employee Conversations

> **Historical phase guide:** This document describes the earlier AgentHQ Vite application. The current product direction is Hermes3D-first: use `start-agenthq-stack.ps1` and open `http://127.0.0.1:3000/office`. The Vite UI is retained only as a legacy/reference dashboard. See `docs/HERMES3D_FIRST_AUDIT_AND_MIGRATION.md`.

Phase 3 connects the persisted employee directory to the local Ollama model and adds a persistent conversation workspace.

## What is included

- Local Ollama chat endpoint using the model configured by `OLLAMA_MODEL` (defaults to `qwen3:4b`).
- A separate system prompt for every employee, based on their name, role, department and office.
- Role guidance for the Orchestrator, Project Manager, Software Engineer, UI/UX Designer, Research Analyst and QA Engineer.
- SQLite tables for conversations and conversation messages.
- Conversation history list and message retrieval endpoints.
- A Conversations workspace with employee selection, recent chats, chat history and a message composer.
- Employee status switches to Working while generating a response and returns to Idle afterwards.
- Up to the latest 16 conversation messages are sent as model context.
- 180-second local model request timeout to allow for slower laptop inference.

## What is not included

AI employees do not yet execute queued tasks, run terminal commands, modify project files, browse the live internet, deploy applications, or perform autonomous delegation. They can reason, answer questions, plan work and draft text/code in the chat. They must not claim to have carried out actions they cannot perform.

## Apply / update on Windows

1. Back up the current project folder and SQLite database.
2. Stop the backend and frontend terminals with `Ctrl+C`.
3. Pull the Phase 3 branch (or use the pull request once reviewed):

   ```powershell
   cd E:\AgentHQ
   git fetch origin
   git checkout feature/phase3-employee-intelligence
   git pull
   ```

   If your local project was originally extracted from ZIP and does not have a Git remote yet, clone the repository to a separate folder first, then copy your local `backend\data\agenthq.db` and any local-only files into the corresponding locations. Do not overwrite the only copy of your database.

4. Start the backend:

   ```powershell
   cd E:\AgentHQ\backend
   Set-ExecutionPolicy -Scope Process Bypass -Force
   .\run.ps1
   ```

5. Start the frontend in a second PowerShell window:

   ```powershell
   cd E:\AgentHQ\frontend
   npm install
   npm run dev
   ```

6. Open `http://127.0.0.1:5173`.

The existing SQLite file is preserved. On backend startup, the new conversation tables are created with `CREATE TABLE IF NOT EXISTS`; employee and task tables are not dropped or reset.

## Check Ollama

Open:

- `http://127.0.0.1:8000/api/health`
- `http://127.0.0.1:8000/api/ollama/status`
- `http://127.0.0.1:8000/docs`

Expected health response includes:

```json
{
  "status": "ok",
  "ollama_connected": true,
  "model": "qwen3:4b"
}
```

If needed, check the model in PowerShell:

```powershell
ollama list
ollama run qwen3:4b
```

Keep Ollama running while using employee chat. The model is loaded locally; no cloud credentials are needed.

## Test Phase 3

1. Open the **Conversations** section in AgentHQ.
2. Select Atlas (AI Orchestrator) and send: `Introduce yourself and explain how you can help the company.`
3. Confirm a role-aware answer appears and the response reports Qwen3 as the model.
4. Start a new conversation with Arin (Software Engineer). Ask for a high-level plan to add a feature to a React app.
5. Confirm Arin responds from the software-engineering perspective.
6. Refresh the browser and open **Recent chats**. Confirm both conversations remain.
7. Open an earlier conversation and confirm the prior messages load.
8. Restart the backend and confirm the conversation history remains.
9. During a longer response, check the employee's status in the office/team panel; it should briefly show Working and then return to Idle.

## API

### List conversations

`GET /api/conversations`

### Read conversation messages

`GET /api/conversations/{conversation_id}/messages`

### Chat with an employee

`POST /api/agents/{agent_id}/chat`

Request body:

```json
{
  "message": "Help me plan the next steps for AgentHQ.",
  "conversation_id": null
}
```

Use the returned `conversation_id` for subsequent turns. The frontend does this automatically.

## Hardware notes

The initial default uses a 4096-token context and a maximum response of 700 tokens to limit memory use. Chat is sequential per user interaction; no multiple-model workers are started. Start with one conversation at a time on a laptop GPU with 4 GB VRAM. Ollama may use system RAM when the model does not fit entirely in VRAM.

## Local data and safety

Conversation messages are stored in the same local SQLite database as employee and task records at `backend/data/agenthq.db` by default. The API runner binds to loopback (`127.0.0.1`). Do not expose this development API to a public network without adding authentication and a security review.

The current chat tool is text-only. It cannot run shell commands, read or write files, make live web requests, deploy software, or mark queued tasks complete.
