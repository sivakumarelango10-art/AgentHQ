# Phase 5A — ephemeral GitHub-hosted repository test runner

Phase 5A moves project test execution out of the public AgentHQ/Render web process. It uses a fresh GitHub-hosted Actions runner in the configured target repository.

## Workflow

1. A task execution must first reach \`approved\`. Draft artifacts remain private until the Founder approves them.
2. AgentHQ writes the approved artifacts to a dedicated branch named \`agenthq/execution-<hash>\`. It does not open a PR yet.
3. AgentHQ checks that \`.github/workflows/agenthq-sandbox.yml\` exists on the target repository's default branch.
4. If it is missing, the Founder can request installation. AgentHQ opens a setup PR containing the trusted workflow template. Review and merge that PR into the target repository's default branch.
5. AgentHQ dispatches the workflow with the execution ID, generated branch, exact commit SHA and selected profile.
6. GitHub Actions checks out exactly that SHA on a fresh \`ubuntu-24.04\` hosted runner and verifies the checkout SHA before running tests.
7. The workflow publishes a commit status using the context \`AgentHQ / isolated repository tests\`. AgentHQ polls that status and records the result.
8. Only a successful status unlocks the existing founder-reviewed GitHub PR publication endpoint. The default branch is never modified directly.

## Supported test profiles

- \`auto\`: selects Node.js when \`package.json\` exists, otherwise Python when \`pyproject.toml\` or \`requirements.txt\` exists.
- \`node\`: requires \`package.json\` plus \`package-lock.json\` or \`npm-shrinkwrap.json\`; runs \`npm ci\`, \`npm test\`, and optional \`typecheck\` and \`build\` scripts.
- \`python\`: requires \`pyproject.toml\` or \`requirements.txt\`; installs pytest and listed requirements, compiles Python files, then runs \`pytest\`.

The workflow has a 15-minute job timeout. If a project uses a different test command or dependency manager, a later phase will add explicitly reviewed repository profiles rather than accepting arbitrary shell commands from the model.

## Security boundaries

- Tests run on a GitHub-hosted ephemeral VM, not in the Render web process.
- The test job's \`GITHUB_TOKEN\` is limited to \`contents: read\`.
- Checkout sets \`persist-credentials: false\`; the checkout token is not persisted in the repository's Git configuration.
- No repository secrets, environment secrets, AgentHQ tokens, S3 credentials or Cloudflare credentials are passed to the test job.
- The workflow's status-publishing jobs are separate from the test job. They run trusted GitHub-script code from the default-branch workflow and receive only \`statuses: write\`. The untrusted test process never receives the status-writing token.
- The workflow does not write branches, create PRs, merge, modify the default branch or deploy.
- AgentHQ verifies the exact target branch and SHA before running. A mismatched checkout fails before tests start.
- The runner setup workflow is installed through a Founder-reviewed PR before dispatch is enabled.

### Important limitation

This is an ephemeral hosted-runner boundary, **not a network-isolated sandbox**. Test scripts and dependency-install hooks execute arbitrary project code inside the disposable VM and can access the public internet and the repository checkout. They receive no secrets and no repository write token, but they could still disclose source files from the checkout over the network. Do not use this phase for repositories whose source must not be exposed to code being tested. A future hardened runner can add egress allowlists and stronger isolation controls.

## Required GitHub token permissions

The fine-grained token configured as \`AGENTHQ_GITHUB_TOKEN\` must be scoped to the single target repository and include:

- Actions: **write** (dispatch the workflow)
- Contents: **write** (create the execution branch and setup branch)
- Workflows: **write** (create the workflow file under \`.github/workflows\`)
- Pull requests: **write** (open the workflow-installation and approved implementation PRs)
- Commit statuses: **read** (read the runner result)
- Metadata: **read**

The status-writing permission belongs to the short-lived workflow token in the separate status jobs; it is not required on AgentHQ's token.

Update the token in Render's environment settings. Keep its value secret; never commit it or expose it in browser code. AgentHQ never returns the token in API responses.

## API

- \`GET /api/github-runner/status\` — founder-only workflow installation status and required permission names.
- \`POST /api/github-runner/install\` — founder-only action to create/reuse the workflow setup PR.
- \`POST /api/task-executions/{execution_id}/sandbox-run\` — founder-only branch preparation and workflow dispatch for an approved execution.
- \`GET /api/task-executions/{execution_id}/sandbox-run\` — retrieve and refresh the status for the exact sandbox commit.
- \`POST /api/task-executions/{execution_id}/github-pr\` — now rejects publication unless the linked isolated test status is \`success\`.

Sandbox states: \`not_run\`, \`queued\`, \`pending\`, \`success\`, \`failure\`, and \`error\`.

## Production enablement checklist

1. Confirm \`AGENTHQ_GITHUB_REPOSITORY\` points to the intended single target repository.
2. Create/update the fine-grained token with the permissions above and replace the Render \`AGENTHQ_GITHUB_TOKEN\` value.
3. In Hermes3D, request runner installation and review the generated workflow setup PR.
4. Merge the setup PR into the target repository's default branch.
5. Refresh runner status in Hermes3D and verify the workflow is marked installed.
6. Run an approved, harmless execution. Confirm the exact SHA checked out, a workflow run URL appears, and the commit status becomes \`success\`.
7. Confirm that the GitHub PR action remains blocked while tests are pending or failing, and becomes available only after success.

## What Phase 5A does not do

- It does not run shell commands in the AgentHQ FastAPI process or Render container.
- It does not accept model-supplied shell commands or arbitrary workflow YAML.
- It does not merge PRs, push to the default branch, or deploy applications.
- It does not yet enforce network egress restrictions or support arbitrary test profiles.
