# AgentHQ implementation and production status

Current release: **0.5.0 — Hermes3D-first, founder-approved task delivery**

Last verified production deployment: **2026-11-15**  
Render service: [agenthq-hermes3d](https://agenthq-hermes3d.onrender.com)  
Deployed AgentHQ commit: `4ab37a24911ce55574e61970b8078b4c89b089bf`  
Pinned Hermes3D commit: `ca3ba1d02fa0d0bfa2e5e249c54f58c1197bb0b1`

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

## Key API routes

- `POST /api/tasks/{task_id}/executions` — queue an execution.
- `GET /api/tasks/{task_id}/executions` — list task executions.
- `GET /api/task-executions/{execution_id}` — retrieve execution status/details.
- `GET /api/task-executions/{execution_id}/artifacts` — list artifacts.
- `GET /api/task-executions/{execution_id}/artifacts/{path}` — download an artifact.
- `POST /api/task-executions/{execution_id}/approve` — founder approval.
- `POST /api/task-executions/{execution_id}/reject` — founder rejection.
- `POST /api/task-executions/{execution_id}/github-pr` — publish an approved execution as a GitHub PR.

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
- `AGENTHQ_GITHUB_TOKEN` — fine-grained token limited to the target repository, with Metadata read, Contents read/write and Pull requests read/write.

Keep object storage private and scope its credentials to the required bucket/prefix. Scope the GitHub token to only the target repository. Do not put secrets in frontend environment variables or browser requests.

## Verification completed

- AgentHQ PR #23 CI: 169 backend tests passed, 36 environment-dependent tests skipped; frontend checks passed. S3/GitHub integrations were mocked in automated tests.
- Hermes3D Phase 4C PR #3 CI: TypeScript typecheck, unit tests and Next.js production build passed.
- AgentHQ PR #24 CI: frontend typecheck/build, backend syntax and exact Hermes3D git-submodule pin checks passed.
- AgentHQ PR #25 synchronized the completed Phase 4B/4C branch into `main`; its CI passed.
- Render deployment for commit `4ab37a2` completed successfully and is marked live.
- Render startup logs confirm production database validation, successful Alembic migrations, AgentHQ `/health` returning HTTP 200, Hermes3D `/api/health` readiness, and the unified stack reporting ready.

## Remaining production acceptance tests

These checks require a founder-authenticated session and the live credentials in Render; mocked CI tests do not replace them:

1. In Render Dashboard, confirm the S3 and GitHub environment variables are present without revealing their values.
2. From the Studio, queue a harmless test task, inspect the generated artifacts, and exercise both approve and reject paths.
3. Confirm the approved artifact survives a service restart by reading it back from the configured private object store.
4. Publish a test approved execution to the configured GitHub repository; verify the dedicated branch, pull request, and target-repository CI result.
5. Verify the GitHub token cannot write outside the one configured repository and the object-storage credentials cannot access unrelated buckets/prefixes.

The production deployment is live, but a real S3 round-trip and real GitHub publication have **not** been claimed as verified here.

## Not yet implemented — next phases

The current deliverable workflow is not an unrestricted autonomous coding agent. These capabilities still require separate implementation and security review:

- Isolated/sandboxed code execution and terminal/file tools.
- Running target-repository test suites and collecting verified results.
- Safe, scoped repository checkout/edit/test workflows before generating a PR.
- Agent-to-agent delegation and coordination.
- Scheduled tasks, retry/backoff and crash-recovery policies for long-running work.
- Persistent employee memory beyond the current conversation/task context.
- Operational dashboards, execution telemetry, retention and admin controls.

Untrusted generated code must not be run inside the public FastAPI/Next.js web process. Any future executor must use a separate isolated runtime with resource limits, network and filesystem policy, explicit approval gates and auditable results.

## Local development

The Windows PowerShell helper and local Ollama instructions in `README.md` are for the local development setup. They are not a description of the Render production provider/database configuration.
