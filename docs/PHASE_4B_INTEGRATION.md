# Phase 4B integration — AgentHQ + Hermes3D

This PR advances AgentHQ's `hermes3d` Git submodule to the merged Phase 4B implementation.

## Included UI/API workflow

- Task details panel discovers canonical AgentHQ employees.
- Selecting an employee and queueing a task synchronizes the same task ID into AgentHQ, then creates a founder-reviewable execution.
- Execution history refreshes while work is queued or running.
- The founder can preview private artifacts, approve or reject them, and see the updated execution state.
- The server-side proxy keeps `RUNTIME_API_TOKEN` out of browser code.

## Verification evidence

- Hermes3D PR #1 merged as commit `f8046e204890f59b88f9f31dbc74cbda1f3c7c8e`.
- Hermes3D CI passed TypeScript typecheck, all 1,242 unit tests, and the Next.js production build for the exact commit before merge.
- AgentHQ CI verifies that its production submodule pin matches that tested Hermes3D commit.
- AgentHQ's own backend and frontend CI run separately on this PR.

The Hermes3D repository is private. The default GitHub Actions token issued to AgentHQ cannot clone a different private repository. For that reason, AgentHQ CI verifies the gitlink SHA rather than claiming to re-run the Hermes3D tests from inside AgentHQ. Hermes3D's own CI is the authoritative source for those checks.

## Production constraints

- AgentHQ's current Render blueprint has `autoDeploy: false`; merging this PR will not deploy it automatically.
- The current Render blueprint selects the Free service plan. Render Free services cannot attach persistent disks and have ephemeral local filesystems. AgentHQ execution artifacts stored under `AGENTHQ_WORKSPACE_DIR` will be lost on restart/redeploy/spin-down unless moved to durable object storage.
- Render Free services spin down after inactivity and can take about a minute to start again. Upgrade compute and configure persistent storage before relying on durable execution artifacts or production SLA.
- Phase 4A/4B generates bounded text deliverables and requires founder approval. It does not execute arbitrary code, commit files to a repository, create downstream GitHub PRs, or deploy applications.
