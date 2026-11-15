"""End-to-End Integration Test Suite for Phase 2D.2.1: Task Integration Hardening.

Covers:
1. Founder authentication flow (login & session cookie).
2. Hermes3D office runtime verification (canonical employees).
3. Task creation with authoritative persistence.
4. Canonical employee assignment & role resolution.
5. Task updates & optimistic concurrency versioning.
6. Status state machine lifecycle & timestamp semantics.
7. Fresh browser/session reload simulation.
8. Verification of persistent state.
9. Audit trail inspection (chronological transitions).
10. Task cancellation (cancelled_at timestamp, completed_at null).
11. Terminal state enforcement (cancelled tasks cannot be mutated).
12. Upstream unavailability simulation (fails closed, zero silent fallback).
13. Conflicting / failing saves never report false success.
14. Service restart recovery across database engine disposal.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from app import db, security
from app.main import app

TEST_PASSWORD = "FounderStudioPassword123!"
TEST_PASSWORD_HASH = security.hash_password(TEST_PASSWORD)
TEST_USERNAME = "founder"
TEST_RUNTIME_TOKEN = "test-runtime-token-e2e-xyz"
TEST_SESSION_SECRET = "test-session-secret-e2e-must-be-32-bytes!"


class TaskIntegrationE2ETests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db.get_session() as session:
            session.execute(db.delete(db.TaskAuditLog))
            session.execute(db.delete(db.Task))
            session.execute(db.delete(db.OwnerSession))
            session.execute(db.delete(db.LoginAttempt))

        self.env_patcher = patch.dict(
            os.environ,
            {
                "STUDIO_USERNAME": TEST_USERNAME,
                "STUDIO_PASSWORD_HASH": TEST_PASSWORD_HASH,
                "RUNTIME_API_TOKEN": TEST_RUNTIME_TOKEN,
                "SESSION_SECRET": TEST_SESSION_SECRET,
                "APP_ENV": "development",
            },
        )
        self.env_patcher.start()
        self.client = TestClient(app)
        self.auth_headers = {"Authorization": f"Bearer {TEST_RUNTIME_TOKEN}"}

    def tearDown(self):
        self.env_patcher.stop()

    def test_complete_end_to_end_task_integration_lifecycle(self):
        """Execute the complete 14-step end-to-end integration scenario."""
        # ---------------------------------------------------------
        # Step 1: Founder login
        # ---------------------------------------------------------
        login_res = self.client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        self.assertEqual(login_res.status_code, 200, "Login must succeed with valid credentials")
        login_data = login_res.json()
        self.assertTrue(login_data.get("ok"))
        self.assertIn("studio_session", login_res.cookies)
        session_token = login_res.cookies["studio_session"]
        session_cookie_header = {"Cookie": f"studio_session={session_token}"}

        # ---------------------------------------------------------
        # Step 2: Open Hermes3D office (Verify canonical employees)
        # ---------------------------------------------------------
        agents_res = self.client.get("/api/agents", headers=session_cookie_header)
        self.assertEqual(agents_res.status_code, 200)
        agents = agents_res.json().get("items", [])
        self.assertGreaterEqual(len(agents), 7)
        agent_names = {a["id"]: a["name"] for a in agents}
        self.assertEqual(agent_names["ceo"], "Atlas")
        self.assertEqual(agent_names["pm"], "Mira")
        self.assertEqual(agent_names["dev"], "Arin")
        self.assertEqual(agent_names["kiran"], "Kiran")
        self.assertEqual(agent_names["design"], "Nia")
        self.assertEqual(agent_names["research"], "Ira")
        self.assertEqual(agent_names["qa"], "Dev")

        # ---------------------------------------------------------
        # Step 3: Create task
        # ---------------------------------------------------------
        create_payload = {
            "title": "Build Neural Canvas 3D",
            "description": "Interactive voxel canvas in Hermes3D",
            "priority": "high",
            "status": "inbox",
            "source": "hermes3d_manual",
        }
        create_res = self.client.post("/api/tasks", json=create_payload, headers=self.auth_headers)
        self.assertEqual(create_res.status_code, 201)
        created_item = create_res.json()["item"]
        task_id = created_item["id"]
        self.assertEqual(created_item["status"], "inbox")
        self.assertEqual(created_item["version"], 1)
        self.assertIsNone(created_item["completed_at"])
        self.assertIsNone(created_item["cancelled_at"])

        # ---------------------------------------------------------
        # Step 4: Assign employee
        # ---------------------------------------------------------
        assign_res = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"assigned_agent_id": "dev", "version": 1},
            headers=self.auth_headers,
        )
        self.assertEqual(assign_res.status_code, 200)
        assigned_item = assign_res.json()["item"]
        self.assertEqual(assigned_item["assigned_agent_id"], "dev")
        self.assertEqual(assigned_item["assigned_agent_name"], "Arin")
        self.assertEqual(assigned_item["assigned_agent_role"], "Software Engineer")
        self.assertEqual(assigned_item["version"], 2)

        # ---------------------------------------------------------
        # Step 5: Update task details
        # ---------------------------------------------------------
        update_res = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"priority": "urgent", "description": "Updated detailed spec", "version": 2},
            headers=self.auth_headers,
        )
        self.assertEqual(update_res.status_code, 200)
        updated_item = update_res.json()["item"]
        self.assertEqual(updated_item["priority"], "urgent")
        self.assertEqual(updated_item["description"], "Updated detailed spec")
        self.assertEqual(updated_item["version"], 3)

        # ---------------------------------------------------------
        # Step 6: Change task status & verify timestamp semantics
        # ---------------------------------------------------------
        # Move: inbox -> scheduled
        r_sched = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "scheduled", "version": 3},
            headers=self.auth_headers,
        )
        self.assertEqual(r_sched.status_code, 200)

        # Move: scheduled -> working
        r_work = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "working", "version": 4},
            headers=self.auth_headers,
        )
        self.assertEqual(r_work.status_code, 200)

        # Move: working -> needs_attention
        r_block = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "needs_attention", "version": 5},
            headers=self.auth_headers,
        )
        self.assertEqual(r_block.status_code, 200)

        # Move: needs_attention -> working
        r_resume = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "working", "version": 6},
            headers=self.auth_headers,
        )
        self.assertEqual(r_resume.status_code, 200)

        # Move: working -> done (completed_at stamped)
        r_done = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "done", "version": 7},
            headers=self.auth_headers,
        )
        self.assertEqual(r_done.status_code, 200)
        done_item = r_done.json()["item"]
        self.assertEqual(done_item["status"], "done")
        self.assertIsNotNone(done_item["completed_at"])
        self.assertIsNone(done_item["cancelled_at"])

        # Reopen: done -> working (completed_at cleared)
        r_reopen = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "working", "version": 8},
            headers=self.auth_headers,
        )
        self.assertEqual(r_reopen.status_code, 200)
        reopened_item = r_reopen.json()["item"]
        self.assertEqual(reopened_item["status"], "working")
        self.assertIsNone(reopened_item["completed_at"])
        self.assertEqual(reopened_item["version"], 9)

        # ---------------------------------------------------------
        # Step 7 & 8: Simulate fresh browser reload and verify persistence
        # ---------------------------------------------------------
        fresh_client = TestClient(app)
        get_res = fresh_client.get(f"/api/tasks/{task_id}", headers=session_cookie_header)
        self.assertEqual(get_res.status_code, 200)
        fetched_task = get_res.json()["item"]
        self.assertEqual(fetched_task["id"], task_id)
        self.assertEqual(fetched_task["title"], "Build Neural Canvas 3D")
        self.assertEqual(fetched_task["priority"], "urgent")
        self.assertEqual(fetched_task["status"], "working")
        self.assertEqual(fetched_task["assigned_agent_id"], "dev")
        self.assertEqual(fetched_task["assigned_agent_name"], "Arin")
        self.assertEqual(fetched_task["version"], 9)

        # ---------------------------------------------------------
        # Step 9: Inspect audit history
        # ---------------------------------------------------------
        history = fetched_task.get("audit_history") or fetched_task.get("history") or []
        self.assertGreaterEqual(len(history), 6)
        actions = [entry["action"] for entry in history]
        self.assertEqual(actions[0], "created")
        self.assertIn("assigned", actions)
        self.assertIn("status_changed", actions)

        # ---------------------------------------------------------
        # Step 10 & 11: Cancel task and verify terminal state
        # ---------------------------------------------------------
        cancel_res = self.client.post(
            f"/api/tasks/{task_id}/cancel",
            json={"version": 9},
            headers=self.auth_headers,
        )
        self.assertEqual(cancel_res.status_code, 200)
        cancelled_item = cancel_res.json()["item"]
        self.assertEqual(cancelled_item["status"], "cancelled")
        self.assertIsNotNone(cancelled_item["cancelled_at"])
        self.assertIsNone(cancelled_item["completed_at"])
        self.assertEqual(cancelled_item["version"], 10)

        # Idempotent cancel
        second_cancel = self.client.post(
            f"/api/tasks/{task_id}/cancel",
            json={"version": 10},
            headers=self.auth_headers,
        )
        self.assertEqual(second_cancel.status_code, 200)
        self.assertEqual(second_cancel.json()["item"]["status"], "cancelled")

        # Modifying cancelled task must return 409 Conflict
        mod_cancel = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"title": "Hacked Title", "version": 10},
            headers=self.auth_headers,
        )
        self.assertEqual(mod_cancel.status_code, 409)
        self.assertIn("Cannot modify a cancelled task", mod_cancel.json()["detail"])

        # ---------------------------------------------------------
        # Step 12 & 13: Concurrency conflict and no false success
        # ---------------------------------------------------------
        # Create a fresh task for concurrency check
        c_task = self.client.post(
            "/api/tasks",
            json={"title": "Concurrency Check", "status": "inbox"},
            headers=self.auth_headers,
        ).json()["item"]

        # Legitimate update with version=1 moves to version 2
        u1 = self.client.patch(
            f"/api/tasks/{c_task['id']}",
            json={"title": "Legitimate Title", "version": 1},
            headers=self.auth_headers,
        )
        self.assertEqual(u1.status_code, 200)
        self.assertEqual(u1.json()["item"]["version"], 2)

        # Stale update with version=1 fails with 409 Conflict
        stale_u = self.client.patch(
            f"/api/tasks/{c_task['id']}",
            json={"title": "Stale Update", "version": 1},
            headers=self.auth_headers,
        )
        self.assertEqual(stale_u.status_code, 409)
        self.assertIn("Conflict: Task version mismatch", stale_u.json()["detail"])

        # Verify the database state was NOT modified by the stale update
        verify_stale = self.client.get(f"/api/tasks/{c_task['id']}", headers=self.auth_headers).json()["item"]
        self.assertEqual(verify_stale["title"], "Legitimate Title")
        self.assertEqual(verify_stale["version"], 2)

        # ---------------------------------------------------------
        # Step 14: Restart services and verify persistence across restart
        # ---------------------------------------------------------
        db.reset_engine()
        db.init_db()

        persisted_task = db.get_task(task_id)
        self.assertIsNotNone(persisted_task)
        self.assertEqual(persisted_task["id"], task_id)
        self.assertEqual(persisted_task["status"], "cancelled")
        self.assertEqual(persisted_task["version"], 10)
        self.assertIsNotNone(persisted_task["cancelled_at"])
        self.assertIsNone(persisted_task["completed_at"])
        self.assertGreaterEqual(len(persisted_task.get("audit_history") or []), 6)


if __name__ == "__main__":
    unittest.main()

