# Phase 4B integration — AgentHQ + Hermes3D

The production container builds Hermes3D from the `hermes3d` Git submodule. This commit pins the Hermes3D integration to the merged Phase 4B implementation.

## Included UI/API workflow

- Task details panel discovers canonical AgentHQ employees.
- Selecting an employee and queueing a task synchronizes the same task ID into AgentHQ, then creates a founder-reviewable execution.
- Execution history refreshes while work is queued or running.
- The founder can preview private artifacts, approve or reject them, and see the updated execution state.
- Server-side proxy keeps `RUNTIME_API_TOKEN` out of browser code.

## Build and release verification

The AgentHQ CI workflow now checks out submodules recursively and runs Hermes3D typecheck, the full unit test suite, and Next.js production build. This ensures the exact Git submodule revision used by the unified AgentHQ container is tested.

## Production constraints

- AgentHQ's current Render blueprint has `autoDeploy: false`; this PR will not deploy itself.
- The current Render blueprint selects the Free service plan. Render Free services cannot attach persistent disks and have ephemeral local filesystems. AgentHQ execution artifacts stored under `AGENTHQ_WORKSPACE_DIR` will be lost on restart/redeploy/spin-down unless moved to durable object storage.
- Render Free services also spin down after inactivity and can take about a minute to start again. Upgrade compute and configure persistent storage before relying on durable execution artifacts or production SLA.
- Phase 4A/4B generates bounded text deliverables and requires founder approval. It does not execute arbitrary code, commit files to a repository, create downstream GitHub PRs, or deploy applications.
