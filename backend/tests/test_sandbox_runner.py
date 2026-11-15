from __future__ import annotations

import asyncio
import hashlib
import json
import os
import unittest
from unittest.mock import patch

import httpx

from app import sandbox_runner


class SandboxRunnerTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "AGENTHQ_GITHUB_REPOSITORY": "example/project",
            "AGENTHQ_GITHUB_TOKEN": "sandbox-test-token",
            "AGENTHQ_SANDBOX_WORKFLOW": "agenthq-sandbox.yml",
        })
        self.env.start()
        self.real_async_client = httpx.AsyncClient

    def tearDown(self):
        self.env.stop()

    def _patch_client(self, handler):
        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return self.real_async_client(*args, **kwargs)
        return patch("app.github_integration.httpx.AsyncClient", side_effect=factory)

    def test_installs_secret_free_runner_workflow_through_reviewable_pull_request(self):
        calls = []
        workflow_blob_content = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            calls.append((request.method, path))
            if request.method == "GET" and path == "/repos/example/project":
                return httpx.Response(200, json={
                    "default_branch": "main",
                    "html_url": "https://github.com/example/project",
                })
            if request.method == "GET" and path.endswith("/git/ref/heads/main"):
                return httpx.Response(200, json={"object": {"sha": "a" * 40}})
            if request.method == "GET" and "/contents/.github/workflows/agenthq-sandbox.yml" in path:
                return httpx.Response(404, json={"message": "Not Found"})
            if request.method == "GET" and path.endswith("/pulls"):
                return httpx.Response(200, json=[])
            if request.method == "GET" and "/git/ref/heads/" in path:
                return httpx.Response(404, json={"message": "Not Found"})
            if request.method == "GET" and path.endswith("/git/commits/" + "a" * 40):
                return httpx.Response(200, json={"tree": {"sha": "b" * 40}})
            if request.method == "POST" and path.endswith("/git/blobs"):
                payload = json.loads(request.content)
                workflow_blob_content.append(payload.get("content", ""))
                return httpx.Response(201, json={"sha": "c" * 40})
            if request.method == "POST" and path.endswith("/git/trees"):
                payload = json.loads(request.content)
                self.assertEqual(payload["tree"][0]["path"], ".github/workflows/agenthq-sandbox.yml")
                return httpx.Response(201, json={"sha": "d" * 40})
            if request.method == "POST" and path.endswith("/git/commits"):
                return httpx.Response(201, json={"sha": "e" * 40})
            if request.method == "POST" and path.endswith("/git/refs"):
                return httpx.Response(201, json={"ref": "refs/heads/agenthq/install-sandbox-runner-v1"})
            if request.method == "POST" and path.endswith("/pulls"):
                payload = json.loads(request.content)
                self.assertEqual(payload["base"], "main")
                self.assertEqual(payload["head"], "agenthq/install-sandbox-runner-v1")
                return httpx.Response(201, json={
                    "html_url": "https://github.com/example/project/pull/41",
                    "number": 41,
                    "state": "open",
                })
            return httpx.Response(500, json={"message": f"Unexpected {request.method} {path}"})

        with self._patch_client(handler):
            result = asyncio.run(sandbox_runner.install_runner_workflow())

        self.assertFalse(result["installed"])
        self.assertEqual(result["setup_pr_url"], "https://github.com/example/project/pull/41")
        self.assertEqual(result["setup_pr_number"], 41)
        self.assertEqual(result["workflow_file"], ".github/workflows/agenthq-sandbox.yml")
        self.assertEqual(len(workflow_blob_content), 1)
        workflow = workflow_blob_content[0]
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("timeout-minutes: 15", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("statuses: write", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertTrue(any(method == "POST" and path.endswith("/pulls") for method, path in calls))

    def test_prepares_private_execution_branch_and_dispatches_only_to_installed_workflow(self):
        calls = []
        dispatch_payloads = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            calls.append((request.method, path))
            if request.method == "GET" and path == "/repos/example/project":
                return httpx.Response(200, json={"default_branch": "main"})
            if request.method == "GET" and path.endswith("/git/ref/heads/main"):
                return httpx.Response(200, json={"object": {"sha": "a" * 40}})
            if request.method == "GET" and "/contents/.github/workflows/agenthq-sandbox.yml" in path:
                return httpx.Response(200, json={"sha": "f" * 40})
            if request.method == "GET" and "/git/ref/heads/" in path:
                return httpx.Response(404, json={"message": "Not Found"})
            if request.method == "GET" and path.endswith("/pulls"):
                return httpx.Response(200, json=[])
            if request.method == "GET" and path.endswith("/git/commits/" + "a" * 40):
                return httpx.Response(200, json={"tree": {"sha": "b" * 40}})
            if request.method == "POST" and path.endswith("/git/blobs"):
                return httpx.Response(201, json={"sha": "c" * 40})
            if request.method == "POST" and path.endswith("/git/trees"):
                return httpx.Response(201, json={"sha": "d" * 40})
            if request.method == "POST" and path.endswith("/git/commits"):
                return httpx.Response(201, json={"sha": "e" * 40})
            if request.method == "POST" and path.endswith("/git/refs"):
                return httpx.Response(201, json={"ref": "refs/heads/agenthq/execution-123"})
            if request.method == "POST" and path.endswith("/actions/workflows/agenthq-sandbox.yml/dispatches"):
                dispatch_payloads.append(json.loads(request.content))
                return httpx.Response(204)
            if request.method == "GET" and path.endswith("/commits/" + "e" * 40 + "/statuses"):
                return httpx.Response(200, json=[{
                    "context": "AgentHQ / isolated repository tests",
                    "state": "success",
                    "description": "Isolated repository tests passed.",
                    "target_url": "https://github.com/example/project/actions/runs/12345",
                    "updated_at": "2026-11-15T14:00:00Z",
                }])
            return httpx.Response(500, json={"message": f"Unexpected {request.method} {path}"})

        with self._patch_client(handler):
            branch = asyncio.run(sandbox_runner.prepare_execution_branch(
                execution_id="12345678-1234-1234-1234-123456789abc",
                task_title="Prepare API tests",
                artifacts=[{"path": "README.md", "content": "# Draft API plan\n"}],
            ))
            dispatched = asyncio.run(sandbox_runner.dispatch_sandbox_run(
                execution_id="12345678-1234-1234-1234-123456789abc",
                target_ref=branch["sandbox_branch"],
                target_sha=branch["sandbox_commit_sha"],
                profile="node",
            ))
            status = asyncio.run(sandbox_runner.get_commit_sandbox_status(branch["sandbox_commit_sha"]))

        self.assertTrue(branch["sandbox_branch"].startswith("agenthq/execution-"))
        self.assertEqual(branch["sandbox_commit_sha"], "e" * 40)
        self.assertEqual(dispatched["status"], "pending")
        self.assertEqual(dispatch_payloads[0]["ref"], "main")
        self.assertEqual(dispatch_payloads[0]["inputs"]["target_ref"], branch["sandbox_branch"])
        self.assertEqual(dispatch_payloads[0]["inputs"]["target_sha"], "e" * 40)
        self.assertEqual(status["status"], "success")
        self.assertEqual(status["target_url"], "https://github.com/example/project/actions/runs/12345")
        self.assertFalse(any(method == "PATCH" and path.endswith("/git/refs/heads/main") for method, path in calls))

    def test_rejects_invalid_sandbox_ref_sha_profile_and_execution_mismatch(self):
        execution_id = "execution-123"
        expected_branch = "agenthq/execution-" + hashlib.sha256(execution_id.encode()).hexdigest()[:16]
        with self.assertRaises(Exception):
            asyncio.run(sandbox_runner.dispatch_sandbox_run(
                execution_id=execution_id,
                target_ref="../main",
                target_sha="a" * 40,
                profile="node",
            ))
        with self.assertRaises(Exception):
            asyncio.run(sandbox_runner.dispatch_sandbox_run(
                execution_id=execution_id,
                target_ref="agenthq/execution-0000000000000000",
                target_sha="a" * 40,
                profile="node",
            ))
        with self.assertRaises(Exception):
            asyncio.run(sandbox_runner.dispatch_sandbox_run(
                execution_id=execution_id,
                target_ref=expected_branch,
                target_sha="not-a-sha",
                profile="node",
            ))
        with self.assertRaises(Exception):
            asyncio.run(sandbox_runner.dispatch_sandbox_run(
                execution_id=execution_id,
                target_ref=expected_branch,
                target_sha="a" * 40,
                profile="shell",
            ))


if __name__ == "__main__":
    unittest.main()
