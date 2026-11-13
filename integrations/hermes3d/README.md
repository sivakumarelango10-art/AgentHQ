# Hermes3D — AgentHQ's primary application

Hermes3D is the primary UI foundation for AgentHQ. AgentHQ's FastAPI service remains the company runtime and authoritative data service (SQLite + Ollama). Keep Hermes3D's native design, office scene, employee interactions, chat, HQ panels, settings and Studio workflows. Do not recreate those experiences in the legacy AgentHQ Vite interface.

## Upstream project

- Repository: https://github.com/iamlukethedev/Hermes3D
- License: MIT (preserve upstream license and third-party notices)
- Stack: Next.js 16, React 19, Three.js, React Three Fiber, Drei, Phaser and the Hermes3D runtime-provider layer.
- User's working tree: `E:\Hermes3D` (separate local checkout)
- AgentHQ runtime: `E:\AgentHQ\backend` (FastAPI, SQLite and Ollama)

## Product ownership

| Area | Source of truth |
|---|---|
| Main application UI, office rendering, camera, interactions and Studio panels | Hermes3D |
| Employee records, canonical roles, departments, rooms and statuses | AgentHQ SQLite |
| Conversations and durable chat history | AgentHQ SQLite |
| Configured model and inference | AgentHQ + Ollama |
| Task records, assignments, execution state and audit records | AgentHQ SQLite (Kanban mapping to be completed) |
| Visual office presentation of status/task events | Hermes3D, driven by AgentHQ runtime events |

There must be one employee roster, one chat history and one task board. Hermes3D must not create a parallel company database.

## Local operation

From the AgentHQ repository:

```powershell
cd E:\AgentHQ
Set-ExecutionPolicy -Scope Process Bypass -Force
.\start-agenthq-stack.ps1
```

This starts only the AgentHQ FastAPI runtime and Hermes3D Studio. Open:

```text
http://127.0.0.1:3000/office
```

In Hermes3D choose **Custom backend** and set:

```text
http://127.0.0.1:8000
```

Leave the token empty for the local loopback-only development environment. Do not start the AgentHQ Vite application on port 5173 as the product UI.

## Custom runtime implementation

Current AgentHQ endpoints:
- `GET /health`
- `GET /state`
- `GET /registry`
- `POST /v1/chat/completions`

See [AGENTHQ_RUNTIME.md](AGENTHQ_RUNTIME.md) for the contract, setup and current limitations.

## Important local patch preservation

A compatibility patch was previously applied in the local Hermes3D checkout to support `sessions.patch`. The upstream default branch reviewed during the audit does not contain that AgentHQ-specific change. Before updating or replacing the Hermes3D checkout:

1. Run `git status --short` and `git diff` in `E:\Hermes3D`.
2. Save the diff and identify the exact provider contract it supports.
3. Preserve it in an AgentHQ-owned Hermes3D fork or versioned patch set.
4. Only then update/rebase the Hermes3D source.

Do not overwrite the user's local Hermes3D folder during this migration.

## Migration roadmap

1. Stabilize the direct Hermes3D Custom runtime connection and preserve the local provider patch.
2. Extend the provider/AgentHQ contract for durable session listing, history reload and session updates.
3. Expose the canonical seven-person employee metadata to Hermes3D (role, department, room, color, status and current task).
4. Synchronize Hermes3D Kanban with AgentHQ's task records and add a verified task lifecycle.
5. Add normalized streaming events and live presence updates.
6. Add guarded orchestration, approvals, isolated tools and audit logs only after the previous contracts are stable.

## Safety

AgentHQ currently binds to loopback. Do not expose its unauthenticated development API to a LAN or public internet. Keep shell, filesystem, browser, external network and deployment capabilities disabled until scoped permissions, approval gates, sandboxing, cancellation, timeouts and audit records are implemented and tested.
