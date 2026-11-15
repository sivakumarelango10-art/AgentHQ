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


if __name__ == "__main__":
    unittest.main()
