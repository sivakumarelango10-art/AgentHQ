from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx

from app import github_integration


class GitHubIntegrationTests(unittest.TestCase):
    def test_requires_repository_and_token_configuration(self):
        with patch.dict(os.environ, {
            "AGENTHQ_GITHUB_REPOSITORY": "",
            "AGENTHQ_GITHUB_TOKEN": "",
        }):
            with self.assertRaises(github_integration.GitHubIntegrationConfigurationError):
                github_integration._configuration()

    def test_creates_a_dedicated_branch_and_pull_request_without_touching_base(self):
        commit_sha = "c" * 40
        counter = {"blob": 0}
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            requests.append((request.method, path))
            if request.method == "GET" and path.endswith("/pulls"):
                return httpx.Response(200, json=[])
            if request.method == "GET" and path == "/repos/example/project":
                return httpx.Response(200, json={"default_branch": "main"})
            if request.method == "GET" and path.endswith("/git/ref/heads/main"):
                return httpx.Response(200, json={"object": {"sha": "a" * 40}})
            if request.method == "GET" and path.endswith("/git/commits/" + "a" * 40):
                return httpx.Response(200, json={"tree": {"sha": "b" * 40}})
            if request.method == "POST" and path.endswith("/git/blobs"):
                counter["blob"] += 1
                return httpx.Response(201, json={"sha": f"{counter['blob']:040x}"})
            if request.method == "POST" and path.endswith("/git/trees"):
                return httpx.Response(201, json={"sha": "d" * 40})
            if request.method == "POST" and path.endswith("/git/commits"):
                return httpx.Response(201, json={"sha": commit_sha})
            if request.method == "POST" and path.endswith("/git/refs"):
                body = json.loads(request.content)
                self.assertTrue(body["ref"].startswith("refs/heads/agenthq/execution-"))
                return httpx.Response(201, json={"ref": body["ref"]})
            if request.method == "POST" and path.endswith("/pulls"):
                body = json.loads(request.content)
                self.assertEqual(body["base"], "main")
                self.assertTrue(body["head"].startswith("agenthq/execution-"))
                return httpx.Response(201, json={
                    "html_url": "https://github.com/example/project/pull/17",
                    "number": 17,
                    "state": "open",
                    "head": {"sha": commit_sha},
                })
            return httpx.Response(500, json={"message": f"Unexpected {request.method} {path}"})

        real_async_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            return real_async_client(*args, transport=httpx.MockTransport(handler), **kwargs)

        with patch.dict(os.environ, {
            "AGENTHQ_GITHUB_REPOSITORY": "example/project",
            "AGENTHQ_GITHUB_TOKEN": "test-token",
        }):
            with patch("app.github_integration.httpx.AsyncClient", side_effect=client_factory):
                result = asyncio.run(github_integration.create_review_pull_request(
                    execution_id="12345678-1234-1234-1234-123456789abc",
                    task_title="Build a small API",
                    summary="Founder-approved API draft.",
                    artifacts=[{"path": "README.md", "content": "# API\\n"}],
                ))

        self.assertEqual(result["github_pr_url"], "https://github.com/example/project/pull/17")
        self.assertEqual(result["github_pr_number"], 17)
        self.assertEqual(result["github_commit_sha"], commit_sha)
        self.assertTrue(any(method == "POST" and path.endswith("/git/refs") for method, path in requests))
        self.assertTrue(any(method == "POST" and path.endswith("/pulls") for method, path in requests))
        self.assertFalse(any(method == "PATCH" and path.endswith("/git/refs/heads/main") for method, path in requests))


    def test_reuses_existing_execution_branch_after_a_previous_partial_attempt(self):
        existing_commit_sha = "e" * 40
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            requests.append((request.method, path))
            if request.method == "GET" and path.endswith("/pulls"):
                return httpx.Response(200, json=[])
            if request.method == "GET" and path == "/repos/example/project":
                return httpx.Response(200, json={"default_branch": "main"})
            if request.method == "GET" and path.endswith("/git/ref/heads/main"):
                return httpx.Response(200, json={"object": {"sha": "a" * 40}})
            if request.method == "GET" and "/git/ref/heads/" in path and not path.endswith("/main"):
                return httpx.Response(200, json={"object": {"sha": existing_commit_sha}})
            if request.method == "POST" and path.endswith("/pulls"):
                body = json.loads(request.content)
                self.assertEqual(body["base"], "main")
                return httpx.Response(201, json={
                    "html_url": "https://github.com/example/project/pull/18",
                    "number": 18,
                    "state": "open",
                    "head": {"sha": existing_commit_sha},
                })
            return httpx.Response(500, json={"message": f"Unexpected {request.method} {path}"})

        real_async_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            return real_async_client(*args, transport=httpx.MockTransport(handler), **kwargs)

        with patch.dict(os.environ, {
            "AGENTHQ_GITHUB_REPOSITORY": "example/project",
            "AGENTHQ_GITHUB_TOKEN": "test-token",
        }):
            with patch("app.github_integration.httpx.AsyncClient", side_effect=client_factory):
                result = asyncio.run(github_integration.create_review_pull_request(
                    execution_id="12345678-1234-1234-1234-123456789abc",
                    task_title="Build a small API",
                    summary="Founder-approved API draft.",
                    artifacts=[{"path": "README.md", "content": "# API\\n"}],
                ))

        self.assertEqual(result["github_pr_url"], "https://github.com/example/project/pull/18")
        self.assertEqual(result["github_commit_sha"], existing_commit_sha)
        self.assertFalse(any(path.endswith("/git/blobs") for method, path in requests))
        self.assertFalse(any(path.endswith("/git/trees") for method, path in requests))
        self.assertFalse(any(path.endswith("/git/commits") for method, path in requests))
        self.assertFalse(any(path.endswith("/git/refs") and method == "POST" for method, path in requests))



if __name__ == "__main__":
    unittest.main()
