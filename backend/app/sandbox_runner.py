from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from . import github_integration

_STATUS_CONTEXT = "AgentHQ / isolated repository tests"
_INSTALL_BRANCH = "agenthq/install-sandbox-runner-v1"
_WORKFLOW_FILE = "agenthq-sandbox.yml"
_MAX_EXECUTION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


class SandboxWorkflowNotInstalled(github_integration.GitHubIntegrationError):
    """Raised when the target repository has not merged the trusted runner workflow."""


def _workflow_filename() -> str:
    value = (os.getenv("AGENTHQ_SANDBOX_WORKFLOW") or _WORKFLOW_FILE).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}\.yml", value):
        raise github_integration.GitHubIntegrationConfigurationError(
            "AGENTHQ_SANDBOX_WORKFLOW must be a .yml filename."
        )
    return value


def _workflow_path() -> str:
    return f".github/workflows/{_workflow_filename()}"


def _template_content() -> str:
    path = Path(__file__).resolve().parent / "workflow_templates" / _WORKFLOW_FILE
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        raise github_integration.GitHubIntegrationError(
            "The AgentHQ isolated-runner workflow template is missing from this deployment."
        ) from error
    if not content.strip():
        raise github_integration.GitHubIntegrationError("The isolated-runner workflow template is empty.")
    return content


def _client_config() -> tuple[str, str, str, dict[str, str]]:
    owner, _, repository, token = github_integration._configuration()
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": github_integration._API_VERSION,
        "User-Agent": "AgentHQ-Isolated-Repository-Runner",
    }
    return owner, repository, token, headers


async def _repository_context(
    client: httpx.AsyncClient,
    repository: str,
) -> tuple[str, str, str]:
    repo_info = await github_integration._request(client, "GET", f"/repos/{repository}")
    default_branch = str(repo_info.get("default_branch") or "").strip()
    if not default_branch or len(default_branch) > 255:
        raise github_integration.GitHubIntegrationError(
            "The target repository does not expose a valid default branch."
        )
    encoded = quote(default_branch, safe="")
    branch_info = await github_integration._request(
        client, "GET", f"/repos/{repository}/git/ref/heads/{encoded}"
    )
    base_sha = str((branch_info.get("object") or {}).get("sha") or "")
    if not _SHA.fullmatch(base_sha):
        raise github_integration.GitHubIntegrationError(
            "GitHub returned an invalid default-branch commit."
        )
    return default_branch, base_sha, str(repo_info.get("html_url") or f"https://github.com/{repository}")


async def get_runner_workflow_status() -> dict[str, Any]:
    """Check whether the configured repository has merged the trusted runner workflow."""
    owner, repository, _, headers = _client_config()
    async with httpx.AsyncClient(
        base_url=github_integration._API_BASE,
        headers=headers,
        timeout=httpx.Timeout(20.0, connect=8.0),
    ) as client:
        default_branch, _, repo_url = await _repository_context(client, repository)
        workflow = await github_integration._request(
            client,
            "GET",
            f"/repos/{repository}/contents/{quote(_workflow_path(), safe='/')}",
            params={"ref": default_branch},
            allow_not_found=True,
        )
        setup_prs = await github_integration._request(
            client,
            "GET",
            f"/repos/{repository}/pulls",
            params={
                "state": "open",
                "head": f"{owner}:{_INSTALL_BRANCH}",
                "per_page": "1",
            },
        )
        setup_pr_url = None
        if isinstance(setup_prs, list) and setup_prs:
            setup_pr_url = str(setup_prs[0].get("html_url") or "") or None
        return {
            "repository": repository,
            "repository_url": repo_url,
            "default_branch": default_branch,
            "workflow_file": _workflow_path(),
            "installed": isinstance(workflow, dict) and bool(workflow.get("sha")),
            "setup_pr_url": setup_pr_url,
            "required_token_permissions": [
                "Actions: write",
                "Contents: write",
                "Workflows: write",
                "Pull requests: write",
                "Commit statuses: read",
                "Metadata: read",
            ],
        }


async def install_runner_workflow() -> dict[str, Any]:
    """Open a founder-reviewable PR that installs the trusted, secret-free runner workflow."""
    owner, repository, _, headers = _client_config()
    status = await get_runner_workflow_status()
    if status["installed"]:
        return {"installed": True, "setup_pr_url": None, "message": "The isolated runner workflow is already installed.", **status}
    if status.get("setup_pr_url"):
        return {"installed": False, "setup_pr_url": status["setup_pr_url"], "message": "The runner installation pull request is already open.", **status}

    template = _template_content()
    async with httpx.AsyncClient(
        base_url=github_integration._API_BASE,
        headers=headers,
        timeout=httpx.Timeout(30.0, connect=8.0),
    ) as client:
        default_branch, base_sha, _ = await _repository_context(client, repository)
        encoded_install_branch = quote(_INSTALL_BRANCH, safe="")
        existing_branch = await github_integration._request(
            client,
            "GET",
            f"/repos/{repository}/git/ref/heads/{encoded_install_branch}",
            allow_not_found=True,
        )
        if existing_branch is not None:
            branch_obj = existing_branch.get("object") if isinstance(existing_branch, dict) else {}
            commit_sha = str((branch_obj or {}).get("sha") or "")
            if not _SHA.fullmatch(commit_sha):
                raise github_integration.GitHubIntegrationError("The existing runner-install branch has an invalid commit.")
        else:
            base_commit = await github_integration._request(
                client, "GET", f"/repos/{repository}/git/commits/{base_sha}"
            )
            base_tree = str((base_commit.get("tree") or {}).get("sha") or "")
            if not _SHA.fullmatch(base_tree):
                raise github_integration.GitHubIntegrationError("GitHub returned an invalid default-branch tree.")
            blob = await github_integration._request(
                client,
                "POST",
                f"/repos/{repository}/git/blobs",
                {"content": template, "encoding": "utf-8"},
            )
            blob_sha = str(blob.get("sha") or "")
            if not _SHA.fullmatch(blob_sha):
                raise github_integration.GitHubIntegrationError("GitHub returned an invalid workflow blob.")
            tree = await github_integration._request(
                client,
                "POST",
                f"/repos/{repository}/git/trees",
                {
                    "base_tree": base_tree,
                    "tree": [{"path": _workflow_path(), "mode": "100644", "type": "blob", "sha": blob_sha}],
                },
            )
            tree_sha = str(tree.get("sha") or "")
            if not _SHA.fullmatch(tree_sha):
                raise github_integration.GitHubIntegrationError("GitHub returned an invalid runner workflow tree.")
            commit = await github_integration._request(
                client,
                "POST",
                f"/repos/{repository}/git/commits",
                {
                    "message": "chore(agenthq): install isolated repository test workflow",
                    "tree": tree_sha,
                    "parents": [base_sha],
                },
            )
            commit_sha = str(commit.get("sha") or "")
            if not _SHA.fullmatch(commit_sha):
                raise github_integration.GitHubIntegrationError("GitHub returned an invalid runner workflow commit.")
            try:
                await github_integration._request(
                    client,
                    "POST",
                    f"/repos/{repository}/git/refs",
                    {"ref": f"refs/heads/{_INSTALL_BRANCH}", "sha": commit_sha},
                )
            except github_integration.GitHubIntegrationError:
                current = await github_integration._request(
                    client,
                    "GET",
                    f"/repos/{repository}/git/ref/heads/{encoded_install_branch}",
                )
                branch_obj = current.get("object") if isinstance(current, dict) else {}
                commit_sha = str((branch_obj or {}).get("sha") or "")
                if not _SHA.fullmatch(commit_sha):
                    raise

        pr = await github_integration._request(
            client,
            "POST",
            f"/repos/{repository}/pulls",
            {
                "title": "chore(agenthq): install isolated repository test workflow",
                "head": _INSTALL_BRANCH,
                "base": default_branch,
                "draft": False,
                "body": (
                    "## AgentHQ isolated repository runner\n\n"
                    "This PR installs a manually-dispatched workflow used to run approved AgentHQ deliverables "
                    "on a fresh GitHub-hosted runner before AgentHQ opens the implementation pull request.\n\n"
                    "### Security boundaries\n"
                    "- The test job runs on a fresh GitHub-hosted virtual machine with a 15-minute timeout.\n"
                    "- The test job receives only contents: read; it receives no repository or environment secrets.\n"
                    "- Checkout does not persist Git credentials.\n"
                    "- The status-reporting job is separate and receives only statuses: write after tests finish.\n"
                    "- The workflow never writes repository files, pushes branches, merges pull requests, or deploys.\n\n"
                    "Review this workflow and merge it into the default branch before using AgentHQ isolated tests."
                ),
            },
        )
        return {
            "installed": False,
            "setup_pr_url": str(pr.get("html_url") or "") or None,
            "setup_pr_number": int(pr.get("number") or 0),
            "repository": repository,
            "default_branch": default_branch,
            "workflow_file": _workflow_path(),
            "message": "Runner installation pull request created. Merge it into the target repository's default branch, then refresh runner status.",
        }


async def prepare_execution_branch(
    *,
    execution_id: str,
    task_title: str,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Commit approved text artifacts to a deterministic branch without opening a PR."""
    if not _MAX_EXECUTION_ID.fullmatch(execution_id or ""):
        raise github_integration.GitHubIntegrationError("Execution identifier is invalid.")
    _, repository, _, headers = _client_config()
    files = github_integration._validated_files(artifacts)
    branch_suffix = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:16]
    branch = f"agenthq/execution-{branch_suffix}"

    async with httpx.AsyncClient(
        base_url=github_integration._API_BASE,
        headers=headers,
        timeout=httpx.Timeout(30.0, connect=8.0),
    ) as client:
        default_branch, base_sha, _ = await _repository_context(client, repository)
        encoded_branch = quote(branch, safe="")
        existing_branch = await github_integration._request(
            client,
            "GET",
            f"/repos/{repository}/git/ref/heads/{encoded_branch}",
            allow_not_found=True,
        )
        if existing_branch is not None:
            branch_obj = existing_branch.get("object") if isinstance(existing_branch, dict) else {}
            commit_sha = str((branch_obj or {}).get("sha") or "")
            if not _SHA.fullmatch(commit_sha):
                raise github_integration.GitHubIntegrationError("GitHub returned an invalid execution branch commit.")
        else:
            base_commit = await github_integration._request(
                client, "GET", f"/repos/{repository}/git/commits/{base_sha}"
            )
            base_tree_sha = str((base_commit.get("tree") or {}).get("sha") or "")
            if not _SHA.fullmatch(base_tree_sha):
                raise github_integration.GitHubIntegrationError("GitHub returned an invalid base tree.")
            tree_items: list[dict[str, str]] = []
            for path, content in files:
                blob = await github_integration._request(
                    client,
                    "POST",
                    f"/repos/{repository}/git/blobs",
                    {"content": content, "encoding": "utf-8"},
                )
                blob_sha = str(blob.get("sha") or "")
                if not _SHA.fullmatch(blob_sha):
                    raise github_integration.GitHubIntegrationError("GitHub returned an invalid artifact blob identifier.")
                tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})
            tree = await github_integration._request(
                client,
                "POST",
                f"/repos/{repository}/git/trees",
                {"base_tree": base_tree_sha, "tree": tree_items},
            )
            tree_sha = str(tree.get("sha") or "")
            if not _SHA.fullmatch(tree_sha):
                raise github_integration.GitHubIntegrationError("GitHub returned an invalid execution tree.")
            safe_title = " ".join((task_title or "AgentHQ task").split())[:160]
            commit = await github_integration._request(
                client,
                "POST",
                f"/repos/{repository}/git/commits",
                {
                    "message": f"[AgentHQ sandbox] {safe_title} (execution {execution_id[:8]})",
                    "tree": tree_sha,
                    "parents": [base_sha],
                },
            )
            commit_sha = str(commit.get("sha") or "")
            if not _SHA.fullmatch(commit_sha):
                raise github_integration.GitHubIntegrationError("GitHub returned an invalid execution commit.")
            await github_integration._request(
                client,
                "POST",
                f"/repos/{repository}/git/refs",
                {"ref": f"refs/heads/{branch}", "sha": commit_sha},
            )

    return {
        "github_repo": repository,
        "sandbox_branch": branch,
        "sandbox_commit_sha": commit_sha,
        "sandbox_profile": "auto",
        "sandbox_default_branch": default_branch,
    }


async def dispatch_sandbox_run(
    *,
    execution_id: str,
    target_ref: str,
    target_sha: str,
    profile: str = "auto",
) -> dict[str, Any]:
    if not _MAX_EXECUTION_ID.fullmatch(execution_id or ""):
        raise github_integration.GitHubIntegrationError("Execution identifier is invalid.")
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", target_ref or "") or ".." in target_ref.split("/"):
        raise github_integration.GitHubIntegrationError("Sandbox target branch is invalid.")
    if not _SHA.fullmatch(target_sha or ""):
        raise github_integration.GitHubIntegrationError("Sandbox target commit is invalid.")
    if profile not in {"auto", "node", "python"}:
        raise github_integration.GitHubIntegrationError("Sandbox profile must be auto, node, or python.")

    _, repository, _, headers = _client_config()
    status = await get_runner_workflow_status()
    if not status["installed"]:
        raise SandboxWorkflowNotInstalled(
            "The isolated runner workflow is not installed on the target repository's default branch. "
            "Create or merge the runner setup pull request first."
        )
    default_branch = str(status["default_branch"])
    async with httpx.AsyncClient(
        base_url=github_integration._API_BASE,
        headers=headers,
        timeout=httpx.Timeout(30.0, connect=8.0),
    ) as client:
        await github_integration._request(
            client,
            "POST",
            f"/repos/{repository}/actions/workflows/{quote(_workflow_filename(), safe='')}/dispatches",
            {
                "ref": default_branch,
                "inputs": {
                    "execution_id": execution_id,
                    "target_ref": target_ref,
                    "target_sha": target_sha,
                    "profile": profile,
                },
            },
        )
    return {
        "repository": repository,
        "workflow_file": _workflow_path(),
        "target_ref": target_ref,
        "target_sha": target_sha,
        "status": "pending",
        "message": "Isolated repository checks were dispatched to a fresh GitHub-hosted runner.",
    }


async def get_commit_sandbox_status(commit_sha: str) -> dict[str, Any] | None:
    if not _SHA.fullmatch(commit_sha or ""):
        raise github_integration.GitHubIntegrationError("Sandbox commit identifier is invalid.")
    _, repository, _, headers = _client_config()
    async with httpx.AsyncClient(
        base_url=github_integration._API_BASE,
        headers=headers,
        timeout=httpx.Timeout(20.0, connect=8.0),
    ) as client:
        statuses = await github_integration._request(
            client,
            "GET",
            f"/repos/{repository}/commits/{commit_sha}/statuses",
            params={"per_page": "100"},
        )
    if not isinstance(statuses, list):
        raise github_integration.GitHubIntegrationError("GitHub returned an invalid commit-status response.")
    matching = [
        item for item in statuses
        if isinstance(item, dict) and item.get("context") == _STATUS_CONTEXT
    ]
    if not matching:
        return None
    matching.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    latest = matching[0]
    state = str(latest.get("state") or "").casefold()
    if state not in {"pending", "success", "failure", "error"}:
        state = "error"
    target_url = str(latest.get("target_url") or "")
    if target_url and not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[0-9]+", target_url):
        target_url = ""
    return {
        "status": state,
        "target_url": target_url or None,
        "description": str(latest.get("description") or "")[:140],
        "updated_at": str(latest.get("updated_at") or "")[:40],
        "context": _STATUS_CONTEXT,
    }
