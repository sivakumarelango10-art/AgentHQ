from __future__ import annotations

import hashlib
import os
import re
from typing import Any
from urllib.parse import quote

import httpx

from .execution import ArtifactValidationError, _safe_relative_path

_API_BASE = "https://api.github.com"
_API_VERSION = "2022-11-28"
_MAX_FILES = 5
_MAX_FILE_BYTES = 48 * 1024
_MAX_TOTAL_BYTES = 96 * 1024


class GitHubIntegrationConfigurationError(RuntimeError):
    """Raised when founder-approved GitHub publishing is not configured."""


class GitHubIntegrationError(RuntimeError):
    """Raised when GitHub cannot accept or complete a publication request."""


def _configuration() -> tuple[str, str, str, str]:
    repository = (os.getenv("AGENTHQ_GITHUB_REPOSITORY") or "").strip()
    token = (os.getenv("AGENTHQ_GITHUB_TOKEN") or "").strip()
    if not repository or not token:
        raise GitHubIntegrationConfigurationError(
            "GitHub publishing is not configured. Set AGENTHQ_GITHUB_REPOSITORY and AGENTHQ_GITHUB_TOKEN on the AgentHQ service."
        )
    if len(repository) > 200 or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repository):
        raise GitHubIntegrationConfigurationError("AGENTHQ_GITHUB_REPOSITORY must use the owner/repository format.")
    owner, name = repository.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise GitHubIntegrationConfigurationError("AGENTHQ_GITHUB_REPOSITORY is invalid.")
    return owner, name, repository, token


def _validated_files(artifacts: list[dict[str, Any]]) -> list[tuple[str, str]]:
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= _MAX_FILES:
        raise GitHubIntegrationError("The approved execution must contain between 1 and 5 files.")
    seen: set[str] = set()
    output: list[tuple[str, str]] = []
    total = 0
    for item in artifacts:
        if not isinstance(item, dict):
            raise GitHubIntegrationError("An approved artifact record is invalid.")
        try:
            path = _safe_relative_path(item.get("path")).as_posix()
        except ArtifactValidationError as error:
            raise GitHubIntegrationError("An approved artifact path failed validation.") from error
        if path in seen:
            raise GitHubIntegrationError("The approved execution contains duplicate file paths.")
        seen.add(path)
        content = item.get("content")
        if not isinstance(content, str):
            raise GitHubIntegrationError("An approved artifact must contain UTF-8 text.")
        size = len(content.encode("utf-8"))
        if size <= 0 or size > _MAX_FILE_BYTES:
            raise GitHubIntegrationError("An approved artifact is empty or exceeds 48 KB.")
        total += size
        if total > _MAX_TOTAL_BYTES:
            raise GitHubIntegrationError("The approved execution exceeds 96 KB in total.")
        output.append((path, content))
    return output


async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    try:
        response = await client.request(method, path, json=payload, params=params)
    except httpx.TimeoutException as error:
        raise GitHubIntegrationError("GitHub did not respond before the request timed out.") from error
    except httpx.HTTPError as error:
        raise GitHubIntegrationError("GitHub could not be reached from AgentHQ.") from error

    if response.status_code < 200 or response.status_code >= 300:
        message = ""
        try:
            detail = response.json()
            message = detail.get("message", "") if isinstance(detail, dict) else ""
        except ValueError:
            message = ""
        safe_message = str(message).strip()[:240]
        raise GitHubIntegrationError(
            f"GitHub API rejected the request (HTTP {response.status_code})"
            + (f": {safe_message}" if safe_message else ".")
        )
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError as error:
        raise GitHubIntegrationError("GitHub returned an invalid API response.") from error


async def create_review_pull_request(
    *,
    execution_id: str,
    task_title: str,
    summary: str,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a dedicated GitHub branch and PR; never writes to the base branch."""
    owner, repository_name, repository, token = _configuration()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", execution_id or ""):
        raise GitHubIntegrationError("Execution identifier is invalid.")

    files = _validated_files(artifacts)
    branch_suffix = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:16]
    branch = f"agenthq/execution-{branch_suffix}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": _API_VERSION,
        "User-Agent": "AgentHQ-Reviewed-Execution",
    }
    timeout = httpx.Timeout(30.0, connect=8.0)

    async with httpx.AsyncClient(base_url=_API_BASE, headers=headers, timeout=timeout) as client:
        # Reuse a PR if a previous request completed but AgentHQ did not persist the result.
        existing = await _request(
            client,
            "GET",
            f"/repos/{repository}/pulls",
            params={"state": "all", "head": f"{owner}:{branch}", "per_page": "1"},
        )
        if isinstance(existing, list) and existing:
            pr = existing[0]
            head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
            return {
                "github_repo": repository,
                "github_branch": branch,
                "github_commit_sha": str(head.get("sha") or "")[:64],
                "github_pr_url": str(pr.get("html_url") or "")[:500],
                "github_pr_number": int(pr.get("number") or 0),
                "github_pr_state": str(pr.get("state") or "open")[:20],
            }

        repo_info = await _request(client, "GET", f"/repos/{repository}")
        base_branch = str(repo_info.get("default_branch") or "").strip()
        if not base_branch or len(base_branch) > 255:
            raise GitHubIntegrationError("The target repository does not expose a valid default branch.")

        encoded_base = quote(base_branch, safe="")
        base_ref = await _request(client, "GET", f"/repos/{repository}/git/ref/heads/{encoded_base}")
        base_sha = str((base_ref.get("object") or {}).get("sha") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", base_sha):
            raise GitHubIntegrationError("GitHub returned an invalid base branch commit.")

        base_commit = await _request(client, "GET", f"/repos/{repository}/git/commits/{base_sha}")
        base_tree_sha = str((base_commit.get("tree") or {}).get("sha") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", base_tree_sha):
            raise GitHubIntegrationError("GitHub returned an invalid base tree.")

        tree_items: list[dict[str, str]] = []
        for path, content in files:
            blob = await _request(
                client,
                "POST",
                f"/repos/{repository}/git/blobs",
                {"content": content, "encoding": "utf-8"},
            )
            blob_sha = str(blob.get("sha") or "")
            if not re.fullmatch(r"[0-9a-fA-F]{40}", blob_sha):
                raise GitHubIntegrationError("GitHub returned an invalid artifact blob identifier.")
            tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})

        tree = await _request(
            client,
            "POST",
            f"/repos/{repository}/git/trees",
            {"base_tree": base_tree_sha, "tree": tree_items},
        )
        new_tree_sha = str(tree.get("sha") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", new_tree_sha):
            raise GitHubIntegrationError("GitHub returned an invalid commit tree.")

        safe_title = " ".join((task_title or "AgentHQ task").split())[:160]
        commit = await _request(
            client,
            "POST",
            f"/repos/{repository}/git/commits",
            {
                "message": f"[AgentHQ] {safe_title} (execution {execution_id[:8]})",
                "tree": new_tree_sha,
                "parents": [base_sha],
            },
        )
        commit_sha = str(commit.get("sha") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
            raise GitHubIntegrationError("GitHub returned an invalid commit identifier.")

        await _request(
            client,
            "POST",
            f"/repos/{repository}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": commit_sha},
        )

        file_list = "\n".join(f"- `{path}`" for path, _ in files)
        body = (
            "## AgentHQ reviewed deliverables\n\n"
            f"{(summary or 'Founder-approved AgentHQ deliverables.')[:4000]}\n\n"
            "### Files\n"
            f"{file_list}\n\n"
            f"Execution ID: `{execution_id}`\n\n"
            "This pull request was created from a founder-approved AgentHQ execution. "
            "Review the changes and the repository's CI results before merging. "
            "AgentHQ did not merge this pull request or deploy the changes."
        )
        try:
            pr = await _request(
                client,
                "POST",
                f"/repos/{repository}/pulls",
                {
                    "title": f"[AgentHQ] {safe_title}",
                    "head": branch,
                    "base": base_branch,
                    "body": body,
                    "draft": False,
                },
            )
        except GitHubIntegrationError:
            # Avoid leaving an orphaned branch when PR creation is rejected.
            try:
                await _request(client, "DELETE", f"/repos/{repository}/git/refs/heads/{quote(branch, safe='/')}")
            except GitHubIntegrationError:
                pass
            raise

        return {
            "github_repo": repository,
            "github_branch": branch,
            "github_commit_sha": commit_sha,
            "github_pr_url": str(pr.get("html_url") or "")[:500],
            "github_pr_number": int(pr.get("number") or 0),
            "github_pr_state": str(pr.get("state") or "open")[:20],
        }
