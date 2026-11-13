# Hermes3D evaluation and integration

This folder documents how AgentHQ evaluates and integrates ideas from [Hermes3D](https://github.com/iamlukethedev/Hermes3D).

## Upstream project

- Repository: https://github.com/iamlukethedev/Hermes3D
- License: MIT (see upstream LICENSE)
- Role: self-hosted agent office UI, visualization, Studio, and gateway/proxy layer.
- Stack: Next.js 16, React 19, Three.js, React Three Fiber, Drei, Phaser, custom Node WebSocket proxy.
- Backend: not included. Hermes3D connects to a running Hermes gateway, custom runtime API, or its demo gateway.

## Decision for AgentHQ

Do not replace the AgentHQ application or FastAPI/Ollama backend with Hermes3D.

AgentHQ currently uses:
- React + Vite + React Three Fiber for the existing premium interface and office.
- FastAPI for local application APIs.
- SQLite as the durable source of truth for employees, tasks, and conversations.
- Ollama for local Qwen3 reasoning.

Hermes3D is a separate full Studio application with its own Next.js server, routing, state model, visual office, backend adapter/proxy assumptions, and UI. Copying its whole repository into AgentHQ would create two application shells, competing office models, duplicated runtime state, and additional memory/CPU usage.

## Integration strategy

Use Hermes3D as a separately installed, MIT-licensed sibling application during evaluation and as a source of upstream implementation patterns. The preferred production strategy is to adapt its 3D office renderer/presentation patterns into AgentHQ's existing React Three Fiber office, not embed the entire Next.js Studio in the Vite application.

A later optional sidecar could run Hermes3D on port 3000. It must not replace the AgentHQ frontend on port 5173 or FastAPI on port 8000.

## Adapter boundary required before using Hermes3D as AgentHQ's office

Hermes3D's direct custom runtime seam expects:
- GET /health
- GET /state
- GET /registry
- POST /v1/chat/completions

AgentHQ's current API instead has local-specific FastAPI routes for health, employees, tasks, conversations and Ollama chat. Therefore, create a dedicated AgentHQ adapter that translates these contracts. Do not rewrite or duplicate the SQLite source of truth inside Hermes3D.

The adapter must:
- Read employee and runtime state from AgentHQ FastAPI/SQLite.
- Map employee IDs/roles/rooms/status into the Hermes3D runtime agent schema.
- Map chat completions to the AgentHQ local Ollama chat service.
- Return explicit unsupported capability responses for tools, approvals, sessions or files until those are implemented.
- Expose only the loopback interface (127.0.0.1) in local development.
- Validate requests and cap message/body sizes.
- Never accept arbitrary upstream URLs from the browser.
- Never proxy shell, filesystem, browser or deployment actions.
- Keep AgentHQ's database authoritative.

## Asset/source reuse rules

The upstream project is MIT licensed. Preserve its copyright and license notice for any copied or modified files, and review any separately licensed assets under their own terms. Prefer small, isolated adaptations over wholesale copying.

## Local Windows installation

Run from a separate folder, for example E:\Hermes3D:

```powershell
cd E:\
git clone https://github.com/iamlukethedev/Hermes3D.git
cd E:\Hermes3D
npm ci
Copy-Item .env.example .env
npm run dev
```

Open http://127.0.0.1:3000. For a visual-only evaluation, use Demo backend and run:

```powershell
npm run demo-gateway
```

This is only a demo gateway; it does not use AgentHQ data. Do not point Hermes3D at AgentHQ until the adapter is implemented and contract-tested.

## AgentHQ local services remain

- AgentHQ frontend: http://127.0.0.1:5173
- AgentHQ FastAPI: http://127.0.0.1:8000
- AgentHQ health: http://127.0.0.1:8000/api/health
- Ollama: http://127.0.0.1:11434

## Next integration milestones

1. Run Hermes3D separately in demo mode and compare office rendering, performance, controls and UX.
2. Document a normalized AgentHQ runtime contract (employee roster, live status, activities, messages, tasks).
3. Implement and test a dedicated local AgentHQ-to-Hermes3D runtime adapter.
4. Evaluate adapting selected licensed 3D components into AgentHQ's existing app so the Founder dashboard remains unified.
5. Only after performance and functional acceptance should a user-facing renderer switch be considered.

## Acceptance criteria

- Existing AgentHQ 5173/8000/Ollama services continue working.
- Employee and task records remain unchanged.
- Hermes3D can be started and stopped without affecting AgentHQ.
- Adapter contract tests pass.
- No duplicate database or agent state is introduced.
- No public network exposure or secrets in client storage.
- 3D performance is measured on the RTX A2000 4GB laptop GPU before adopting heavy effects/assets.
