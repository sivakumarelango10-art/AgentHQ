
# AgentHQ + Hermes3D — Architecture Audit and Hermes3D-First Migration

Audit date: 2026-11-13

## Executive decision

## Migration implementation status

The follow-up Hermes3D-first cleanup is being applied in the AgentHQ repository:
- the temporary `HermesOfficeView` iframe wrapper has been removed from the Vite frontend;
- the Vite proxy routes added only for the iframe have been removed;
- the old Vite frontend remains available as a legacy/reference app, but is no longer started by the normal launcher;
- `start-agenthq-stack.ps1` starts AgentHQ FastAPI and the separately installed Hermes3D Studio, then opens the native Hermes3D office;
- `start-frontend.ps1` now uses Hermes3D-first startup by default; pass `-Legacy` only to run the old Vite dashboard;
- the canonical fresh-database employee seed now includes Kiran as the seventh employee, with a regression test.

The actual Hermes3D custom-provider changes remain a separate migration task. The local `sessions.patch` change must be preserved and moved to an AgentHQ-owned Hermes3D fork/patch before any upstream update. The remaining session-history, task/Kanban, streaming and orchestration gaps below are still open.


Use **Hermes3D as the primary application and UI**. Use **AgentHQ as the local company runtime and data service** (FastAPI, SQLite, Ollama, employee identity, conversations and eventually task orchestration).

Do not keep the current AgentHQ Vite application as the product shell with Hermes3D nested inside an iframe. That was a useful connectivity proof, but it is not the requested product architecture and it creates two competing shells.

The intended developer experience is:
- Open the Hermes3D Studio directly as the only browser application.
- Keep AgentHQ FastAPI as a local background service.
- Connect Hermes3D's Custom runtime to AgentHQ.
- Preserve Hermes3D's own layout, visual design, office controls, chat, panels and interaction patterns. Only add AgentHQ-specific identity, runtime and data adapters where required.
- Do not create a replacement visual design in the old AgentHQ Vite app.

## Audit scope and limitations

Reviewed:
- The GitHub AgentHQ default branch, including backend, Vite frontend, project status, CI and recent integration pull requests.
- The public upstream Hermes3D default branch, including its package manifest, office route, office screen, retro-office renderer, gateway connection UI, Studio settings and custom runtime provider.
- Screenshots and terminal output supplied in the working conversation.

The user's local E:\Hermes3D working tree is not directly mounted or readable from GitHub. A compatibility patch was previously applied locally to src/lib/runtime/custom/provider.ts to support sessions.patch; its current local contents and commit state must be verified before replacing, rebasing or forking that working tree. Do not overwrite it.

## Current architecture observed

### AgentHQ repository

- Frontend: React 19 + TypeScript + Vite 7 + React Three Fiber.
- Backend: FastAPI + SQLite + Ollama.
- Local model default: qwen3:4b.
- Local API default: 127.0.0.1:8000.
- Vite dashboard default: 127.0.0.1:5173.
- Persistent tables include employees, queued tasks, conversations, conversation messages and Hermes3D runtime-session mappings.
- The current AgentHQ Vite app has its own sidebar, overview dashboard, employee cards, task inbox, conversation UI, 3D office preview and custom CSS.

### Hermes3D upstream

- Frontend/application: Next.js 16 + React 19.
- Office rendering: Three.js, React Three Fiber, Drei and Phaser.
- The /office route loads the full Studio Office experience, including the office scene, chat panel, employee fleet, HQ panels and settings.
- It has a runtime-adapter architecture. The Custom runtime provider implements the Studio-facing runtime contract and calls the configured external runtime endpoints.
- The upstream repository is substantially larger and more feature-rich than the current AgentHQ Vite UI. It is the correct UI foundation for the requested product.

## Findings

### P0 — Two competing application shells

The merged embedded-office change added a Vite sidebar entry and placed Hermes3D's /office page inside an iframe. This keeps the old AgentHQ page structure and visual system around Hermes3D.

Consequences:
- Two navigation systems and two office experiences are present.
- The AgentHQ Employees, Tasks and Conversations views are separate from Hermes3D's own Studio panels.
- The nested viewport creates additional sizing, scrolling and onboarding/origin concerns.
- The top-level UI remains AgentHQ's previous design instead of using Hermes3D as the product shell.

Decision: treat the iframe as a temporary proof of connectivity only. It must not be the target architecture.

### P0 — Retry client lifecycle bug (fixed in PR #13)

The response-sanitization retry had been placed outside the async with httpx.AsyncClient(...) context. A contaminated first answer caused the retry to use a closed client and raise:

    RuntimeError: Cannot send a request, as the client has been closed.

PR #13 moves validation and retry inside the live client context, adds a regression test reproducing the closed-client failure, and improves frontend API error formatting. CI passed before merge.

### P1 — Runtime compatibility is partial, not a full AgentHQ/Hermes3D feature mapping

The AgentHQ adapter currently exposes:
- GET /health
- GET /state
- GET /registry
- POST /v1/chat/completions

This proves employee discovery and non-streaming chat. It does not yet provide a complete mapping for:
- task creation, assignment, status transitions and Kanban synchronization;
- streamed assistant responses and live runtime events;
- approvals and execution lifecycle;
- durable runtime session patch/update semantics;
- file/workspace tools, scheduled runs or autonomous execution.

Do not label the product as an autonomous AI company until these contracts and workers exist.

### P1 — Local Hermes3D patch drift

A previous local patch was applied to the Hermes3D custom runtime provider to support sessions.patch. The upstream provider source reviewed here does not contain that AgentHQ-specific patch. Unless it is committed to an owned fork/branch and documented, reinstalling or updating Hermes3D can silently remove it.

Action: preserve the current local Hermes3D folder, inspect its Git status and diff, and move the patch into an owned Hermes3D fork or a clearly versioned patch set before any reinstall/update.

### P1 — AgentHQ database seed does not match the seven-person live roster

The current AgentHQ SEED_AGENTS list contains six default employees (Atlas, Mira, Arin, Nia, Ira and Dev). Kiran was added to the working SQLite database later, which is why the existing machine shows seven employees. A fresh database created from the current seed will not reproduce the seven-person team.

Action: add Kiran to the canonical seed and add tests for the expected roster without overwriting or reseeding an existing database.

### P1 — Chat quality enforcement is a guard, not a guarantee

The sanitizer rejects known internal-draft markers and unclosed reasoning tags, then retries once. This is safer than displaying the first response, but marker lists cannot guarantee that a small local model will always follow exact-output instructions.

Action:
- keep rejected drafts out of the assistant message table;
- record safe diagnostic metadata only (model, retry count, finish reason, latency);
- keep the API honest when no clean final answer is available;
- add regression tests for escaped/unmatched reasoning markers and common self-narration;
- later evaluate a model/prompt configuration suitable for role-following on the local hardware.

### P2 — Duplicate conversation and task surfaces

AgentHQ's Vite Conversations view is separate from Hermes3D's chat surface. AgentHQ SQLite stores the authoritative conversation. Hermes3D's Custom provider also maintains client-side session state and expects runtime methods beyond chat. These responsibilities must be clearly separated.

Target ownership:
- AgentHQ SQLite: authoritative employees, task records, conversation records, approvals, execution records and audit events.
- Hermes3D Studio: presentation, office state, user interaction, chat controls, visual task/status views.
- AgentHQ runtime adapter: maps Hermes3D contract to the authoritative AgentHQ service.

### P2 — Task records are not executable work

Current AgentHQ tasks have only queued and cancelled statuses. There is no worker that claims tasks, no in-progress/review/completed lifecycle, no retry/dead-letter policy, and no durable result artifact. A task in the current UI is a saved queue item, not executed work.

Action: implement a state machine and worker only after task ownership, permissions, cancellation, timeouts, idempotency and audit logging are designed.

### P2 — Browser origin and connection settings

Hermes3D saves connection settings in browser storage scoped to the page origin. Settings saved while using localhost:3000 are not automatically the same settings for 127.0.0.1:5173 or an embedded iframe. This explains why the connection wizard can appear again when changing origin.

Decision: make Hermes3D the primary browser origin and choose one canonical URL for daily use. Keep AgentHQ API on loopback and configure the Custom runtime there once.

### Security boundary

AgentHQ's local backend has no user authentication and is intentionally bound to loopback. Keep it on 127.0.0.1; do not expose it to a LAN or public internet. Before file, terminal, browser or autonomous tools are enabled, add scoped permissions, explicit approval gates, isolated workspaces, audit trails and hard execution limits.

## Target architecture

    Browser
      |
      v
    Hermes3D Studio (primary UI, Next.js)
      |  Custom runtime adapter
      v
    AgentHQ FastAPI (loopback-only runtime/API)
      |
      +--> SQLite (employees, conversations, tasks, runs, approvals, audit)
      |
      +--> Ollama (qwen3:4b initially)
      |
      +--> Bounded task workers (future milestone, disabled until guarded)

Do not use the AgentHQ Vite app as a second shell. Keep it temporarily for reference and for any management features not yet migrated; do not delete it until Hermes3D feature coverage has been verified.

## Migration sequence

### Stage 0 — Stabilize and protect current data
- Keep PR #13's client-lifecycle fix.
- Back up the SQLite database and both working trees.
- Capture local Git status and diffs, especially the Hermes3D sessions.patch change.
- Verify a fresh chat, a retry chat, a persisted conversation reload, and a direct Custom runtime connection.
- Do not delete contaminated historical conversations automatically.

### Stage 1 — Make Hermes3D the only product UI
- Use Hermes3D's own Office route as the default entry page.
- Remove the iframe wrapper and duplicate Vite shell from the normal startup path only after direct Hermes3D + AgentHQ runtime connection works reliably.
- Preserve Hermes3D's original Studio layout and components. Avoid recreating these screens in AgentHQ CSS.
- Set the office/company title and AgentHQ employee identities through the supported Hermes3D settings/runtime APIs rather than maintaining duplicate fake roster data.

### Stage 2 — Complete the runtime contract
- Version the AgentHQ Custom runtime API contract.
- Implement persistent session update/patch semantics and test them.
- Ensure employee identifiers remain stable and collision-safe.
- Add message streaming and event/presence state in a contract-compatible way.
- Add task/Kanban read/write mapping so the Hermes3D board and AgentHQ task store share a single source of truth.
- Test API behaviour against the actual Custom runtime provider, not only isolated HTTP calls.

### Stage 3 — Company orchestration
- Add explicit project intake and structured plans.
- Atlas can propose delegation; Mira can create/assign tasks.
- Keep the Founder approval gate for any task with side effects.
- Add worker leases, idempotency keys, cancellation, timeouts, retries, result artifacts and audit logs.
- Make avatars/status/room movement reflect verified task events, not pretend activity.

### Stage 4 — Safe local tool execution
- Create a constrained workspace per project.
- Add read/write allowlists, path traversal protections, process sandboxing, resource/time limits and a kill switch.
- Require approval for file mutations, commands, external network access, deployment and other side effects.
- Store input, tool, approval, output and verification records.

## Definition of done for the Hermes3D-first migration

- The daily entry URL opens Hermes3D directly; no nested iframe is required.
- Only one office, one team list, one chat history and one task board are shown.
- The seven AgentHQ employees load from the AgentHQ runtime with stable IDs.
- A new chat and an existing conversation both work and persist through reload.
- The local Custom runtime connection survives restart using one canonical browser origin.
- A task created in the Studio board is the same task record shown by AgentHQ's API/SQLite.
- The UI uses Hermes3D's native design and interaction model; no parallel AgentHQ redesign is layered over it.
- No autonomous side-effecting tool is enabled before the approval and audit layers are tested.

## Required local verification before changing the user's working folders

Run git status --short in both E:\AgentHQ and E:\Hermes3D. Save or commit any uncommitted work before pulling changes. Verify the exact path and content of the local custom provider patch. Back up backend\data\agenthq.db before any schema migration.
