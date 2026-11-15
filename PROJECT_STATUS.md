# AgentHQ implementation and production status

Current release: **0.5.0 — Hermes3D-first, founder-approved task delivery**

Last verified production deployment: **2026-11-15**  
Render service: [agenthq-hermes3d](https://agenthq-hermes3d.onrender.com)  
Deployed AgentHQ commit: `d8ce0f2c684439ed4e2b04b6894b35cac9973171`  
Pinned Hermes3D commit: `531bd1051dd164559b27ba6325e9b9b38cb1f68e`

## Architecture

- **Hermes3D Studio** is the primary user interface (`/office`), including the 3D office and task board.
- **AgentHQ FastAPI** is the employee/task execution API and runtime.
- **PostgreSQL** is the configured production database; Alembic migrations run at startup.
- **Cloudflare Workers AI** is the configured hosted AI provider in the Render blueprint.
- **S3-compatible object storage** is the production artifact-storage mode selected by the Render blueprint. The bucket must remain private.
- The browser calls Hermes3D server routes; server-side proxies keep runtime and GitHub credentials out of browser code.

## Delivered phases

### Phase 4A — founder-approved task deliverables

- A founder can queue an execution for a task's assigned canonical AgentHQ employee.
- The worker asks the configured AI provider for structured summaries and bounded text/code-file drafts.
- Execution state and task transitions are stored in the database.
- Files are path/extension/size validated and stored in a private execution workspace.
- Python files receive AST parsing and JSON files receive JSON parsing. This is static syntax validation, **not execution or test verification**.
- Founder can preview artifacts and approve or reject them. Approval copies artifacts to the approved workspace; rejection returns the task to `needs_attention`.

### Phase 4B — Hermes3D task-board integration

- The task details panel loads canonical AgentHQ employees.
- A task is synchronized to AgentHQ before its execution is queued, keeping the execution attached to the authoritative task ID.
- Execution status/history refreshes in the Studio.
- The founder can preview artifacts, approve or reject work, and see status changes.
- Server-side proxying prevents the runtime token from being sent to the browser.

### Phase 4C — durable artifacts and GitHub pull requests

- Production storage mode supports S3-compatible object storage under private pending/approved execution prefixes.
- SHA-256 and byte-length checks protect artifact reads and approvals.
- Only founder-approved executions can be published to GitHub.
- Publishing creates a dedicated `agenthq/execution-...` branch and opens a pull request against the configured repository's default branch.
- Repeated publishing requests for the same execution reuse existing PR metadata rather than creating duplicate PRs.
- The Studio shows the resulting validated GitHub pull-request link.
- AgentHQ does not merge that PR, modify the target repository's default branch directly, or deploy the target project.

### Phase 4D — worker recovery and founder retries

- Worker leases and heartbeats detect interrupted executions; stale attempts become failed and move the task to `needs_attention`.
- A founder can retry failed/rejected attempts with revised instructions; each retry creates a new linked history record, retains prior errors, and is capped at five attempts per task.
- Hermes3D displays attempt number, retry lineage, and an explicit retry action for failed/rejected work.
- There is no automatic retry loop. Each retry requires a founder action.

### Phase 5A — ephemeral GitHub-hosted repository tests

- Only founder-approved execution artifacts are committed to a deterministic `agenthq/execution-<hash>` branch.
- A trusted `.github/workflows/agenthq-sandbox.yml` workflow is installed in the configured target repository through a Founder-reviewed setup PR.
- GitHub Actions checks out the exact generated commit on a fresh `ubuntu-24.04` hosted runner, verifies its SHA, and runs the supported Node.js or Python test profile with a 15-minute timeout.
- The test job receives `contents: read` only, does not persist checkout credentials, and receives no repository/environment secrets or AgentHQ/S3/Cloudflare token.
- A separate trusted workflow job receives `statuses: write` and publishes the result; the project test process does not receive that token.
- Only a successful status for the exact tested commit unlocks implementation-PR publishing. AgentHQ verifies the branch SHA and the resulting PR head SHA before recording the PR.
- The runner is ephemeral but **not network-isolated**: test scripts and dependency hooks can access the public internet and checked-out repository files. Do not use this phase for confidential source that must not be exposed to code being tested.

## Key API routes

- `POST /api/tasks/{task_id}/executions` — queue an execution.
- `GET /api/tasks/{task_id}/executions` — list task executions.
- `GET /api/task-executions/{execution_id}` — retrieve execution status/details.
- `GET /api/task-executions/{execution_id}/artifacts` — list artifacts.
- `GET /api/task-executions/{execution_id}/artifacts/{path}` — download an artifact.
- `POST /api/task-executions/{execution_id}/approve` — founder approval.
- `POST /api/task-executions/{execution_id}/reject` — founder rejection.
- `POST /api/task-executions/{execution_id}/github-pr` — publish an approved execution as a GitHub PR.
- `POST /api/task-executions/{execution_id}/retry` — create a new founder-authorized attempt from a failed or rejected execution.
- `GET /api/github-runner/status` — inspect target repository workflow installation.
- `POST /api/github-runner/install` — create/reuse the trusted runner workflow setup PR.
- `POST /api/task-executions/{execution_id}/sandbox-run` and `GET /api/task-executions/{execution_id}/sandbox-run` — dispatch tests and refresh the result.

## Production configuration

The Render Blueprint selects the following modes. Secret values must be set in the Render Dashboard and must never be committed to source control.

**AI and worker**
- `AI_PROVIDER=cloudflare`
- `AGENTHQ_TASK_EXECUTION_ENABLED=true`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`

**Artifact storage**
- `AGENTHQ_WORKSPACE_STORAGE=s3`
- `AWS_S3_BUCKET`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- Optional `AWS_ENDPOINT_URL_S3` (HTTPS for S3-compatible endpoints)
- `AWS_REGION`

**GitHub publishing**
- `AGENTHQ_GITHUB_REPOSITORY=owner/repository`
- `AGENTHQ_GITHUB_TOKEN` — fine-grained token scoped to the one target repository, with Actions write, Contents write, Workflows write, Pull requests write, Commit statuses read and Metadata read.

Keep object storage private and scope its credentials to the required bucket/prefix. Scope the GitHub token to only the target repository. Do not put secrets in frontend environment variables or browser requests.

## Verification completed

- AgentHQ PR #23 CI: 169 backend tests passed, 36 environment-dependent tests skipped; frontend checks passed. S3/GitHub integrations were mocked in automated tests.
- Hermes3D Phase 4C PR #3 CI: TypeScript typecheck, unit tests and Next.js production build passed.
- AgentHQ PR #24 CI: frontend typecheck/build, backend syntax and exact Hermes3D git-submodule pin checks passed.
- AgentHQ PR #26: 172 backend tests passed; 36 environment-dependent PostgreSQL/external-credential tests were skipped. Worker recovery, heartbeat, retry lineage, duplicate prevention, and five-attempt cap tests passed.
- Hermes3D PR #4: typecheck, unit tests and Next.js production build passed for the founder retry controls.
- AgentHQ PR #28: backend tests/syntax, frontend typecheck/build and exact Hermes3D retry-UI pin checks passed.
- AgentHQ PR #26: 172 backend tests passed; 36 environment-dependent PostgreSQL/external-credential tests were skipped. Worker recovery, heartbeat, retry lineage, duplicate prevention, and five-attempt cap tests passed.
- Hermes3D PR #4: typecheck, unit tests and Next.js production build passed for the founder retry controls.
- AgentHQ PR #28: backend tests/syntax, frontend typecheck/build and the exact Hermes3D retry-UI pin checks passed.
- AgentHQ PR #25 synchronized the completed Phase 4B/4C branch into `main`; its CI passed.
- Render deployment for commit `d8ce0f2` completed successfully and is marked live.
- Render startup logs confirm Alembic migrations completed successfully, AgentHQ `/health` returned HTTP 200, Hermes3D health readiness succeeded, and the unified stack reported live/ready.
- Render startup logs confirm production database validation, successful Alembic migrations, AgentHQ `/health` returning HTTP 200, Hermes3D `/api/health` readiness, and the unified stack reporting ready.

## Remaining production acceptance tests

These checks require a founder-authenticated session and the live credentials in Render; mocked CI tests do not replace them:

1. In Render Dashboard, confirm the S3 and GitHub environment variables are present without revealing their values.
2. From the Studio, queue a harmless test task, inspect the generated artifacts, and exercise both approve and reject paths.
3. Confirm the approved artifact survives a service restart by reading it back from the configured private object store.
4. Publish a test approved execution to the configured GitHub repository; verify the dedicated branch, pull request, and target-repository CI result.
5. Verify the GitHub token cannot write outside the one configured repository and the object-storage credentials cannot access unrelated buckets/prefixes.

The Phase 4A–4D production deployment is live. Phase 5A requires the target repository runner setup PR to be merged and the Render GitHub token permissions to be expanded before live dispatch can succeed. A real S3 round-trip, real runner dispatch, and actual implementation PR remain acceptance tests; mocked CI does not replace them.

## Not yet implemented — next phases

The current deliverable workflow is not an unrestricted autonomous coding agent. These capabilities still require separate implementation and security review:

- General-purpose shell/terminal and arbitrary repository editing tools are not exposed to agents or the Render web process.
- Strong network-egress isolation for the hosted test runner; Phase 5A runner is ephemeral but can access public internet and checked-out source.
- Additional reviewed project test profiles beyond the constrained Node.js and Python profiles.
- Agent-to-agent delegation and coordination.
- Automatic retry/backoff loops and horizontal worker-queue scaling (Phase 4D supports only a founder-requested retry, capped at five attempts).
- Scheduled tasks, retry/backoff and crash-recovery policies for long-running work.
- Persistent employee memory beyond the current conversation/task context.
- Operational dashboards, execution telemetry, retention and admin controls.

Untrusted generated code must not be run inside the public FastAPI/Next.js web process. Any future executor must use a separate isolated runtime with resource limits, network and filesystem policy, explicit approval gates and auditable results.

## Local development

The Windows PowerShell helper and local Ollama instructions in `README.md` are for the local development setup. They are not a description of the Render production provider/database configuration.
