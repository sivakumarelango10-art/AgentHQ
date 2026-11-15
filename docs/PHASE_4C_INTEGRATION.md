# Phase 4C unified integration — AgentHQ + Hermes3D

This integration commit pins the Hermes3D UI that exposes the founder-approved GitHub PR workflow.

## Task delivery path

1. A founder syncs a Hermes3D task to AgentHQ and queues an employee execution.
2. AgentHQ generates bounded text deliverables for founder review.
3. The founder previews the files and approves or rejects them.
4. Approved files are persisted to configured S3-compatible object storage when `AGENTHQ_WORKSPACE_STORAGE=s3`.
5. The founder may request a GitHub PR from the approved execution. AgentHQ pushes the artifact set to a deterministic `agenthq/execution-...` branch and opens a PR against the target repository's default branch.
6. Hermes3D displays the PR link in the task panel.

## Required environment configuration

- S3 storage: `AGENTHQ_WORKSPACE_STORAGE=s3`, `AWS_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optional HTTPS `AWS_ENDPOINT_URL_S3`.
- GitHub publishing: `AGENTHQ_GITHUB_REPOSITORY=owner/repository` and `AGENTHQ_GITHUB_TOKEN`.
- GitHub token permissions: Metadata read, Contents read/write, Pull requests read/write, scoped to the one target repository.
- Keep the bucket private and limit the credentials to only the required bucket/repository.

## Boundaries

- Only founder-approved executions can be published to GitHub.
- AgentHQ does not modify the default branch directly, merge the PR, or deploy it.
- CI belongs to the target repository's GitHub Actions workflows.
- AgentHQ does not run untrusted generated code in the web process.
- S3/GitHub live access must be verified against the actual Render settings; CI uses mocked S3/GitHub clients.

## CI strategy

- Hermes3D independently runs typecheck, unit tests, and its Next.js production build for the merged code.
- AgentHQ verifies the exact Hermes3D gitlink SHA used by its Docker build. The Hermes3D repository is private, so the default AgentHQ Actions token cannot recursively clone that submodule.


## Phase 4D — worker reliability and founder retries

The AgentHQ backend now tracks worker leases and heartbeats for execution attempts. Expired worker leases are marked failed and move the parent task to `needs_attention`. Founders can explicitly retry a failed or rejected attempt; each retry creates a new history record, carries prior failure/rejection feedback forward, and is capped at five attempts per task.

Hermes3D exposes the attempt number, lineage, and retry action in the task details panel. The action is only shown for failed or rejected executions, and AgentHQ revalidates the conditions server-side.

- AgentHQ PR #26 merged with backend recovery, Alembic migration 0008, and 172 passing backend tests (36 environment-dependent skips).
- Hermes3D PR #4 merged with retry controls; typecheck, all unit tests, and production build passed.
- The unified Docker container now pins Hermes3D merge commit `531bd1051dd164559b27ba6325e9b9b38cb1f68e`.
- No automatic retry loop is enabled. Each additional attempt requires an explicit founder action.
