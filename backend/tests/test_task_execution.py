from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from app import db, security
from app.main import app, parse_execution_payload
from app.execution import ArtifactValidationError, write_draft_artifacts, resolve_artifact

TEST_PASSWORD = "FounderTaskExecutionPassword123!"
TEST_HASH = security.hash_password(TEST_PASSWORD)
TEST_TOKEN = "test-runtime-token-task-execution"


class TaskExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        self.env = patch.dict(os.environ, {
            "ENVIRONMENT": "development",
            "STUDIO_USERNAME": "founder",
            "STUDIO_PASSWORD_HASH": TEST_HASH,
            "RUNTIME_API_TOKEN": TEST_TOKEN,
            "SESSION_SECRET": "test-task-execution-session-secret-long-enough",
            "AGENTHQ_TASK_EXECUTION_ENABLED": "false",
            "AGENTHQ_WORKSPACE_DIR": str(self.workspace),
            "AGENTHQ_WORKSPACE_STORAGE": "local",
            "AGENTHQ_GITHUB_REPOSITORY": "",
            "AGENTHQ_GITHUB_TOKEN": "",
        })
        self.env.start()
        db.init_db()
        with db.get_session() as session:
            session.query(db.TaskExecution).delete()
            session.query(db.TaskAuditLog).delete()
            session.query(db.Task).delete()
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {TEST_TOKEN}"}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _create_assigned_task(self):
        response = self.client.post(
            "/api/tasks",
            headers=self.headers,
            json={"title": "Prepare API deliverables", "description": "Write a concise API plan.", "assigned_agent_id": "dev"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["item"]["id"]

    def test_01_execution_requires_authentication(self):
        response = self.client.post("/api/tasks/unknown/executions", json={})
        self.assertEqual(response.status_code, 401)

    def test_02_execution_requires_assigned_employee(self):
        task_id = self.client.post("/api/tasks", headers=self.headers, json={"title": "Unassigned"}).json()["item"]["id"]
        response = self.client.post(f"/api/tasks/{task_id}/executions", headers=self.headers, json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("Assign this task", response.json()["detail"])

    def test_03_execution_is_queued_and_duplicate_active_attempt_is_rejected(self):
        task_id = self._create_assigned_task()
        response = self.client.post(f"/api/tasks/{task_id}/executions", headers=self.headers, json={"instructions": "Include endpoint examples."})
        self.assertEqual(response.status_code, 202, response.text)
        item = response.json()["item"]
        self.assertEqual(item["status"], "queued")
        self.assertEqual(item["agent_id"], "dev")
        duplicate = self.client.post(f"/api/tasks/{task_id}/executions", headers=self.headers, json={})
        self.assertEqual(duplicate.status_code, 409)

    def test_04_validates_json_python_and_rejects_traversal(self):
        manifest = write_draft_artifacts("exec-test-001", [
            {"path": "docs/plan.md", "content": "# Plan\n"},
            {"path": "src/example.py", "content": "def hello():\n    return 'hi'\n"},
            {"path": "config.json", "content": json.dumps({"enabled": True})},
        ])
        self.assertEqual(len(manifest), 3)
        self.assertEqual(manifest[1]["validation"], "python_ast")
        with self.assertRaises(ArtifactValidationError):
            write_draft_artifacts("exec-test-002", [{"path": "../escape.py", "content": "print(1)"}])

    def test_05_rejects_invalid_python_and_non_json(self):
        with self.assertRaises(ArtifactValidationError):
            write_draft_artifacts("exec-test-003", [{"path": "broken.py", "content": "def broken(:\n"}])
        with self.assertRaises(ArtifactValidationError):
            write_draft_artifacts("exec-test-004", [{"path": "broken.json", "content": "{oops"}])

    def test_06_artifacts_are_available_only_for_review_state(self):
        task_id = self._create_assigned_task()
        created = self.client.post(f"/api/tasks/{task_id}/executions", headers=self.headers, json={}).json()["item"]
        db.claim_next_task_execution()
        manifest = write_draft_artifacts(created["id"], [{"path": "README.md", "content": "# Deliverable\n"}])
        db.finish_task_execution(created["id"], "Draft ready", manifest)
        response = self.client.get(f"/api/task-executions/{created['id']}/artifacts/README.md", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "# Deliverable\n")

    def test_07_approval_publishes_artifacts_and_completes_task(self):
        task_id = self._create_assigned_task()
        created = self.client.post(f"/api/tasks/{task_id}/executions", headers=self.headers, json={}).json()["item"]
        db.claim_next_task_execution()
        manifest = write_draft_artifacts(created["id"], [{"path": "README.md", "content": "# Approved\n"}])
        db.finish_task_execution(created["id"], "Ready", manifest)
        response = self.client.post(f"/api/task-executions/{created['id']}/approve", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["item"]["status"], "approved")
        task = db.get_task(task_id)
        self.assertEqual(task["status"], "done")
        approved_file = resolve_artifact(created["id"], "README.md", manifest, approved=True)
        self.assertEqual(approved_file.read_text(encoding="utf-8"), "# Approved\n")

    def test_08_rejection_returns_task_to_attention(self):
        task_id = self._create_assigned_task()
        created = self.client.post(f"/api/tasks/{task_id}/executions", headers=self.headers, json={}).json()["item"]
        db.claim_next_task_execution()
        manifest = write_draft_artifacts(created["id"], [{"path": "README.md", "content": "# Draft\n"}])
        db.finish_task_execution(created["id"], "Ready", manifest)
        response = self.client.post(
            f"/api/task-executions/{created['id']}/reject",
            headers=self.headers,
            json={"note": "Add more details."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["item"]["status"], "rejected")
        self.assertEqual(db.get_task(task_id)["status"], "needs_attention")

    def test_09_model_payload_must_be_json(self):
        payload = parse_execution_payload('{"summary":"Done","files":[{"path":"x.md","content":"ok"}]}')
        self.assertEqual(payload["summary"], "Done")
        with self.assertRaises(ArtifactValidationError):
            parse_execution_payload("Here is your work.")

    def test_10_github_pr_publishing_requires_approved_execution_and_configuration(self):
        task_id = self._create_assigned_task()
        created = self.client.post(
            f"/api/tasks/{task_id}/executions",
            headers=self.headers,
            json={},
        ).json()["item"]
        denied = self.client.post(
            f"/api/task-executions/{created['id']}/github-pr",
            headers=self.headers,
        )
        self.assertEqual(denied.status_code, 409)
        db.claim_next_task_execution()
        manifest = write_draft_artifacts(
            created["id"],
            [{"path": "README.md", "content": "# Approved deliverable\\n"}],
        )
        db.finish_task_execution(created["id"], "Ready", manifest)
        approved = self.client.post(
            f"/api/task-executions/{created['id']}/approve",
            headers=self.headers,
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        not_configured = self.client.post(
            f"/api/task-executions/{created['id']}/github-pr",
            headers=self.headers,
        )
        self.assertEqual(not_configured.status_code, 409)
        self.assertIn("isolated repository tests", not_configured.json()["detail"].lower())

    def test_11_github_pr_metadata_is_persisted_once(self):
        task_id = self._create_assigned_task()
        created = self.client.post(
            f"/api/tasks/{task_id}/executions",
            headers=self.headers,
            json={},
        ).json()["item"]
        db.claim_next_task_execution()
        manifest = write_draft_artifacts(
            created["id"],
            [{"path": "README.md", "content": "# Approved\\n"}],
        )
        db.finish_task_execution(created["id"], "Ready", manifest)
        db.approve_task_execution(created["id"], actor="founder")
        details = {
            "github_repo": "example/project",
            "github_branch": "agenthq/execution-123",
            "github_commit_sha": "a" * 40,
            "github_pr_url": "https://github.com/example/project/pull/12",
            "github_pr_number": 12,
            "github_pr_state": "open",
        }
        saved = db.attach_task_execution_github_pr(created["id"], details)
        self.assertEqual(saved["github_pr_url"], details["github_pr_url"])
        second = db.attach_task_execution_github_pr(
            created["id"],
            {**details, "github_pr_url": "https://github.com/example/project/pull/99", "github_pr_number": 99},
        )
        self.assertEqual(second["github_pr_url"], details["github_pr_url"])
        self.assertEqual(second["github_pr_number"], 12)


    def test_12_expired_worker_lease_moves_attempt_to_needs_attention_and_can_be_retried(self):
        task_id = self._create_assigned_task()
        created = self.client.post(
            f"/api/tasks/{task_id}/executions",
            headers=self.headers,
            json={"instructions": "Create a small API plan."},
        ).json()["item"]
        claimed = db.claim_next_task_execution(lease_seconds=60)
        self.assertEqual(claimed["status"], "running")

        with db.get_session(immediate=True) as session:
            record = session.get(db.TaskExecution, created["id"])
            record.lease_expires_at = "2000-01-01T00:00:00+00:00"
            record.last_heartbeat_at = "2000-01-01T00:00:00+00:00"
            session.flush()

        recovered = db.recover_stale_task_executions()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["status"], "failed")
        self.assertIn("lease expired", recovered[0]["error"].lower())
        self.assertEqual(db.get_task(task_id)["status"], "needs_attention")

        retry = self.client.post(
            f"/api/task-executions/{created['id']}/retry",
            headers=self.headers,
            json={},
        )
        self.assertEqual(retry.status_code, 202, retry.text)
        retry_item = retry.json()["item"]
        self.assertEqual(retry_item["status"], "queued")
        self.assertEqual(retry_item["attempt_number"], 2)
        self.assertEqual(retry_item["retry_of_execution_id"], created["id"])
        self.assertIn("lease expired", retry_item["instructions"].lower())

        duplicate = self.client.post(
            f"/api/task-executions/{created['id']}/retry",
            headers=self.headers,
            json={},
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_13_retry_is_limited_to_failed_or_rejected_attempts_and_five_total_attempts(self):
        task_id = self._create_assigned_task()
        created = self.client.post(
            f"/api/tasks/{task_id}/executions",
            headers=self.headers,
            json={},
        ).json()["item"]

        not_failed = self.client.post(
            f"/api/task-executions/{created['id']}/retry",
            headers=self.headers,
            json={},
        )
        self.assertEqual(not_failed.status_code, 409)

        current_id = created["id"]
        for expected_attempt in range(1, 6):
            db.fail_task_execution(current_id, f"attempt {expected_attempt} failed")
            if expected_attempt == 5:
                break
            retry = self.client.post(
                f"/api/task-executions/{current_id}/retry",
                headers=self.headers,
                json={},
            )
            self.assertEqual(retry.status_code, 202, retry.text)
            current_id = retry.json()["item"]["id"]
            self.assertEqual(retry.json()["item"]["attempt_number"], expected_attempt + 1)

        capped = self.client.post(
            f"/api/task-executions/{current_id}/retry",
            headers=self.headers,
            json={},
        )
        self.assertEqual(capped.status_code, 409)
        self.assertIn("maximum", capped.json()["detail"].lower())

    def test_14_heartbeat_extends_worker_lease_and_does_not_revive_finished_execution(self):
        task_id = self._create_assigned_task()
        created = self.client.post(
            f"/api/tasks/{task_id}/executions",
            headers=self.headers,
            json={},
        ).json()["item"]
        claimed = db.claim_next_task_execution(lease_seconds=60)
        self.assertEqual(claimed["id"], created["id"])
        old_lease = claimed["lease_expires_at"]
        self.assertTrue(db.heartbeat_task_execution(created["id"], lease_seconds=120))
        refreshed = db.get_task_execution(created["id"])
        self.assertGreater(refreshed["lease_expires_at"], old_lease)

        db.fail_task_execution(created["id"], "Test failure.")
        self.assertFalse(db.heartbeat_task_execution(created["id"], lease_seconds=120))


    def test_15_sandbox_metadata_requires_approved_execution_and_valid_status_url(self):
        task_id = self._create_assigned_task()
        created = self.client.post(
            f"/api/tasks/{task_id}/executions",
            headers=self.headers,
            json={},
        ).json()["item"]
        details = {
            "github_repo": "example/project",
            "sandbox_branch": "agenthq/execution-1234567890abcdef",
            "sandbox_commit_sha": "a" * 40,
            "sandbox_profile": "node",
        }

        with self.assertRaises(ValueError):
            db.attach_task_execution_sandbox_branch(created["id"], details)

        db.claim_next_task_execution()
        manifest = write_draft_artifacts(
            created["id"],
            [{"path": "README.md", "content": "# Approved sandbox input\n"}],
        )
        db.finish_task_execution(created["id"], "Ready for isolated tests", manifest)
        db.approve_task_execution(created["id"], actor="founder")

        saved = db.attach_task_execution_sandbox_branch(created["id"], details)
        self.assertEqual(saved["sandbox_status"], "queued")
        self.assertEqual(saved["sandbox_commit_sha"], "a" * 40)

        pending = db.update_task_execution_sandbox_status(
            created["id"],
            "pending",
            target_url="https://github.com/example/project/actions/runs/12345",
        )
        self.assertEqual(pending["sandbox_status"], "pending")
        self.assertEqual(
            pending["sandbox_target_url"],
            "https://github.com/example/project/actions/runs/12345",
        )

        passed = db.update_task_execution_sandbox_status(created["id"], "success")
        self.assertEqual(passed["sandbox_status"], "success")

        with self.assertRaises(ValueError):
            db.update_task_execution_sandbox_status(
                created["id"],
                "success",
                target_url="https://attacker.invalid/result",
            )


if __name__ == "__main__":
    unittest.main()
