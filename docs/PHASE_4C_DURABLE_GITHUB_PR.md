# Phase 4C — durable artifacts and reviewed GitHub pull requests

This phase adds durable, private object-storage for execution deliverables and a founder-triggered GitHub PR publication path.

## Durable artifact storage

- Set `AGENTHQ_WORKSPACE_STORAGE=s3` for production. The Render blueprint now selects this mode.
- Objects are stored under the private `agenthq/executions/{pending|approved}/{execution_id}/` prefixes in the configured `AWS_S3_BUCKET`.
- Each artifact is validated before upload and integrity-checked by SHA-256 and byte length when read or approved.
- Local filesystem storage remains the default for development and tests.
- Production S3 configuration requires `AWS_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and, for S3-compatible storage, an HTTPS `AWS_ENDPOINT_URL_S3`.
- Keep the bucket private and restrict the credentials to the configured bucket and AgentHQ execution prefix.

## GitHub PR publishing

- Configure `AGENTHQ_GITHUB_REPOSITORY` as `owner/repository` and `AGENTHQ_GITHUB_TOKEN` as a fine-grained token limited to that repository.
- Required token permissions: Contents read/write, Pull requests read/write, and Metadata read.
- Only founder-approved executions can be published.
- AgentHQ creates a dedicated branch named for the execution, commits the validated artifact files, and opens a pull request against the repository's default branch.
- The default branch is never modified directly. Repository CI runs through the repository's existing pull-request workflows.
- The operation is idempotent for an execution: if a matching PR already exists, AgentHQ returns it rather than creating another.
- GitHub publication is disabled until the two configuration values are present.

## Explicit limitations

- This is reviewed repository publishing, not unrestricted shell execution.
- AgentHQ does not run generated code inside the web process.
- CI feedback is produced by GitHub Actions configured in the target repository; not every repository has the same checks.
- The founder remains responsible for reviewing the PR and merging it.
