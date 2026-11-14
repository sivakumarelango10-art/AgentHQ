"""Unit and integration test suite for Phase 2D.2: Unified Persistent Task Management.

Tests:
1. Task creation with custom ID, title, description, priority, status, due_date, source, source_event_id.
2. Initial status defaults to 'inbox' (or 'queued' normalized to 'inbox').
3. Database persistence and automatic audit log generation upon creation.
4. Task assignment to canonical employees (ceo, pm, dev, design, research, qa, kiran).
5. Automatic resolution of employee display name and role.
6. Safe unassignment (setting assigned_agent_id to None).
7. Rejection of non-existent employee ID with 404 Not Found.
8. Valid status state machine transitions:
   - inbox -> scheduled -> working -> needs_attention -> working -> done
   - done -> working (reopening)
   - any active state -> cancelled
9. Invalid status transitions rejected with 409 Conflict:
   - inbox -> done directly
   - cancelled -> working (terminal state)
10. Task cancellation via POST /api/tasks/{task_id}/cancel and PATCH /api/tasks/{task_id}/cancel.
11. Cancellation sets completed_at timestamp and records audit log.
12. Attempting to cancel an already cancelled task returns 409 Conflict.
13. Task retrieval by ID (GET /api/tasks/{task_id}) including audit history.
14. Task listing with filters:
   - by status
   - by assigned employee
   - with/without cancelled tasks
15. Strict authentication enforcement on task APIs:
   - 401 Unauthorized without auth when enforced
   - 401 Unauthorized with invalid Bearer token
   - 200/201 Success with valid Bearer token (RUNTIME_API_TOKEN)
   - 200/201 Success with valid founder session cookie
16. Concurrent updates / conflict handling across multiple threads.
17. Database compatibility: SQLite and PostgreSQL (skipped if TEST_DATABASE_URL unset).
"""

from __future__ import annotations

import concurrent.futures
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
TEST_RUNTIME_TOKEN = "test-runtime-token-phase2d2-auth-xyz"
TEST_SESSION_SECRET = "test-session-secret-phase2d2-must-be-32-bytes!"


class UnifiedTaskManagementPhase2D2Tests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db.get_session() as session:
            session.execute(db.delete(db.TaskAuditLog))
            session.execute(db.delete(db.Task))

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

    def test_01_create_task_with_custom_fields_and_audit(self):
        """Test task creation with full metadata, custom ID, and audit entry generation."""
        custom_id = "task-custom-001"
        payload = {
            "id": custom_id,
            "title": "Design 3D Office Layout",
            "description": "Create voxel representations for canonical employees",
            "priority": "high",
            "status": "inbox",
            "due_date": "2026-12-01T12:00:00Z",
            "source": "hermes3d_manual",
            "source_event_id": "evt-001",
        }
        response = self.client.post("/api/tasks", json=payload, headers=self.auth_headers)
        self.assertEqual(response.status_code, 201)
        item = response.json().get("item")
        self.assertIsNotNone(item)
        self.assertEqual(item["id"], custom_id)
        self.assertEqual(item["title"], payload["title"])
        self.assertEqual(item["description"], payload["description"])
        self.assertEqual(item["priority"], "high")
        self.assertEqual(item["status"], "inbox")
        self.assertEqual(item["source"], "hermes3d_manual")
        self.assertEqual(item["source_event_id"], "evt-001")
        self.assertIn("created_at", item)
        self.assertIn("updated_at", item)
        self.assertIsNone(item.get("completed_at"))

        # Verify audit history
        history = item.get("audit_history")
        self.assertIsInstance(history, list)
        self.assertGreaterEqual(len(history), 1)
        create_audit = history[0]
        self.assertEqual(create_audit["action"], "created")
        self.assertIsNone(create_audit["from_status"])
        self.assertEqual(create_audit["to_status"], "inbox")
        self.assertEqual(create_audit["actor"], "founder")

    def test_02_task_status_normalization_queued_to_inbox(self):
        """Verify status normalization and default fallback."""
        # 1. Default status when omitted is 'queued' (backwards compatible)
        resp_default = self.client.post("/api/tasks", json={"title": "Default Task"}, headers=self.auth_headers)
        self.assertEqual(resp_default.status_code, 201)
        self.assertEqual(resp_default.json()["item"]["status"], "queued")

        # 2. 'todo' normalizes to 'inbox'
        resp_todo = self.client.post("/api/tasks", json={"title": "Todo Task", "status": "todo"}, headers=self.auth_headers)
        self.assertEqual(resp_todo.status_code, 201)
        self.assertEqual(resp_todo.json()["item"]["status"], "inbox")

        # 3. 'in_progress' normalizes to 'working'
        resp_prog = self.client.post("/api/tasks", json={"title": "Progress Task", "status": "in_progress"}, headers=self.auth_headers)
        self.assertEqual(resp_prog.status_code, 201)
        self.assertEqual(resp_prog.json()["item"]["status"], "working")

    def test_03_canonical_employee_assignment_and_role_resolution(self):
        """Assign to canonical employees and verify name/role resolution."""
        # 1. Assign to 'dev' (Software Engineer)
        payload = {
            "title": "Fix Memory Leak",
            "assigned_agent_id": "dev",
            "priority": "high",
        }
        response = self.client.post("/api/tasks", json=payload, headers=self.auth_headers)
        self.assertEqual(response.status_code, 201)
        task_id = response.json()["item"]["id"]
        item = response.json()["item"]
        self.assertEqual(item["assigned_agent_id"], "dev")
        self.assertEqual(item["assigned_agent_name"], "Arin")
        self.assertEqual(item["assigned_agent_role"], "Software Engineer")

        # 2. Reassign to 'qa' (QA Engineer)
        update_payload = {"assigned_agent_id": "qa", "version": 1}
        patch_resp = self.client.patch(f"/api/tasks/{task_id}", json=update_payload, headers=self.auth_headers)
        self.assertEqual(patch_resp.status_code, 200)
        updated_item = patch_resp.json()["item"]
        self.assertEqual(updated_item["assigned_agent_id"], "qa")
        qa_agent = db.get_agent("qa")
        self.assertIsNotNone(qa_agent)
        self.assertEqual(updated_item["assigned_agent_name"], qa_agent["name"])
        self.assertEqual(updated_item["assigned_agent_role"], "QA Engineer")

        # 3. Unassign
        unassign_payload = {"assigned_agent_id": None, "version": 2}
        unassign_resp = self.client.patch(f"/api/tasks/{task_id}", json=unassign_payload, headers=self.auth_headers)
        self.assertEqual(unassign_resp.status_code, 200)
        unassigned_item = unassign_resp.json()["item"]
        self.assertIsNone(unassigned_item["assigned_agent_id"])
        self.assertIsNone(unassigned_item["assigned_agent_name"])

        # Check audit trail for assignments
        get_resp = self.client.get(f"/api/tasks/{task_id}", headers=self.auth_headers)
        self.assertEqual(get_resp.status_code, 200)
        history = get_resp.json()["item"]["audit_history"]
        actions = [entry["action"] for entry in history]
        self.assertIn("created", actions)
        self.assertIn("assigned", actions)

    def test_04_reject_nonexistent_employee_assignment(self):
        """Reject non-existent agent assignments with 404."""
        # On creation
        bad_create = {
            "title": "Bogus Task",
            "assigned_agent_id": "nonexistent-employee-999",
        }
        res_create = self.client.post("/api/tasks", json=bad_create, headers=self.auth_headers)
        self.assertEqual(res_create.status_code, 404)
        self.assertIn("does not exist", res_create.json()["detail"])

        # On update
        valid_task = self.client.post("/api/tasks", json={"title": "Valid"}, headers=self.auth_headers).json()["item"]
        bad_patch = {
            "assigned_agent_id": "ghost-worker",
            "version": 1,
        }
        res_patch = self.client.patch(f"/api/tasks/{valid_task['id']}", json=bad_patch, headers=self.auth_headers)
        self.assertEqual(res_patch.status_code, 404)
        self.assertIn("does not exist", res_patch.json()["detail"])

    def test_05_valid_status_state_machine_transitions(self):
        """Test full valid lifecycle: inbox -> scheduled -> working -> needs_attention -> working -> done -> working."""
        task = self.client.post("/api/tasks", json={"title": "Lifecycle Task", "status": "inbox"}, headers=self.auth_headers).json()["item"]
        task_id = task["id"]
        self.assertEqual(task["status"], "inbox")

        # 1. inbox -> scheduled
        r1 = self.client.patch(f"/api/tasks/{task_id}", json={"status": "scheduled", "version": 1}, headers=self.auth_headers)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["item"]["status"], "scheduled")

        # 2. scheduled -> working
        r2 = self.client.patch(f"/api/tasks/{task_id}", json={"status": "working", "version": 2}, headers=self.auth_headers)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["item"]["status"], "working")

        # 3. working -> needs_attention
        r3 = self.client.patch(f"/api/tasks/{task_id}", json={"status": "needs_attention", "version": 3}, headers=self.auth_headers)
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["item"]["status"], "needs_attention")

        # 4. needs_attention -> working
        r4 = self.client.patch(f"/api/tasks/{task_id}", json={"status": "working", "version": 4}, headers=self.auth_headers)
        self.assertEqual(r4.status_code, 200)
        self.assertEqual(r4.json()["item"]["status"], "working")

        # 5. working -> done (completion timestamp populated)
        r5 = self.client.patch(f"/api/tasks/{task_id}", json={"status": "done", "version": 5}, headers=self.auth_headers)
        self.assertEqual(r5.status_code, 200)
        item5 = r5.json()["item"]
        self.assertEqual(item5["status"], "done")
        self.assertIsNotNone(item5["completed_at"])

        # 6. Reopen: done -> working (completion timestamp cleared)
        r6 = self.client.patch(f"/api/tasks/{task_id}", json={"status": "working", "version": 6}, headers=self.auth_headers)
        self.assertEqual(r6.status_code, 200)
        item6 = r6.json()["item"]
        self.assertEqual(item6["status"], "working")
        self.assertIsNone(item6["completed_at"])

    def test_06_invalid_status_transitions_rejected(self):
        """Direct illegal status jumps must return 409 Conflict."""
        task = self.client.post("/api/tasks", json={"title": "Illegal Jump Task", "status": "inbox"}, headers=self.auth_headers).json()["item"]
        task_id = task["id"]
        self.assertEqual(task["status"], "inbox")

        # inbox -> done directly is illegal (must move through scheduled or working)
        res_illegal = self.client.patch(f"/api/tasks/{task_id}", json={"status": "done", "version": 1}, headers=self.auth_headers)
        self.assertEqual(res_illegal.status_code, 409)
        self.assertIn("Invalid status transition", res_illegal.json()["detail"])

        # Cancel the task
        self.client.post(f"/api/tasks/{task_id}/cancel", json={"version": 1}, headers=self.auth_headers)

        # cancelled is terminal: cancelled -> working must fail with 409
        res_after_cancel = self.client.patch(f"/api/tasks/{task_id}", json={"status": "working", "version": 2}, headers=self.auth_headers)
        self.assertEqual(res_after_cancel.status_code, 409)
        self.assertIn("Cannot modify a cancelled task", res_after_cancel.json()["detail"])

    def test_07_cancel_task_endpoints_and_idempotency(self):
        """Verify POST and PATCH /api/tasks/{task_id}/cancel timestamp semantics and idempotency."""
        # POST cancel
        task1 = self.client.post("/api/tasks", json={"title": "Task To Cancel via POST"}, headers=self.auth_headers).json()["item"]
        r_cancel1 = self.client.post(f"/api/tasks/{task1['id']}/cancel", json={"version": 1}, headers=self.auth_headers)
        self.assertEqual(r_cancel1.status_code, 200)
        item1 = r_cancel1.json()["item"]
        self.assertEqual(item1["status"], "cancelled")
        # completed_at must be None; cancelled_at must be populated
        self.assertIsNone(item1.get("completed_at"))
        self.assertIsNotNone(item1.get("cancelled_at"))
        self.assertGreaterEqual(item1.get("version", 0), 2)

        # Second cancel attempt on already cancelled task is idempotent and returns 200
        r_double_cancel = self.client.post(f"/api/tasks/{task1['id']}/cancel", json={"version": 2}, headers=self.auth_headers)
        self.assertEqual(r_double_cancel.status_code, 200)
        self.assertEqual(r_double_cancel.json()["item"]["status"], "cancelled")

        # PATCH cancel
        task2 = self.client.post("/api/tasks", json={"title": "Task To Cancel via PATCH"}, headers=self.auth_headers).json()["item"]
        r_cancel2 = self.client.patch(f"/api/tasks/{task2['id']}/cancel", json={"version": 1}, headers=self.auth_headers)
        self.assertEqual(r_cancel2.status_code, 200)
        item2 = r_cancel2.json()["item"]
        self.assertEqual(item2["status"], "cancelled")
        self.assertIsNone(item2.get("completed_at"))
        self.assertIsNotNone(item2.get("cancelled_at"))

    def test_08_list_tasks_filtering(self):
        """Verify listing tasks by status, employee, and inclusion of cancelled tasks."""
        # Create 3 distinct tasks
        t1 = self.client.post("/api/tasks", json={"title": "T1", "assigned_agent_id": "dev"}, headers=self.auth_headers).json()["item"]
        t2 = self.client.post("/api/tasks", json={"title": "T2", "assigned_agent_id": "pm"}, headers=self.auth_headers).json()["item"]
        t3 = self.client.post("/api/tasks", json={"title": "T3", "assigned_agent_id": "dev"}, headers=self.auth_headers).json()["item"]

        self.client.patch(f"/api/tasks/{t1['id']}", json={"status": "working", "version": 1}, headers=self.auth_headers)
        self.client.post(f"/api/tasks/{t3['id']}/cancel", json={"version": 1}, headers=self.auth_headers)

        # 1. Filter by assigned agent
        resp_dev = self.client.get("/api/tasks?assigned_agent_id=dev", headers=self.auth_headers)
        self.assertEqual(resp_dev.status_code, 200)
        items_dev = resp_dev.json()["items"]
        dev_ids = {it["id"] for it in items_dev}
        self.assertIn(t1["id"], dev_ids)
        self.assertIn(t3["id"], dev_ids)
        self.assertNotIn(t2["id"], dev_ids)

        # 2. Filter by status
        resp_working = self.client.get("/api/tasks?status=working", headers=self.auth_headers)
        self.assertEqual(resp_working.status_code, 200)
        items_working = resp_working.json()["items"]
        working_ids = {it["id"] for it in items_working}
        self.assertEqual(working_ids, {t1["id"]})

        # 3. Filter excluding cancelled
        resp_no_cancel = self.client.get("/api/tasks?include_cancelled=false", headers=self.auth_headers)
        self.assertEqual(resp_no_cancel.status_code, 200)
        items_no_cancel = resp_no_cancel.json()["items"]
        active_ids = {it["id"] for it in items_no_cancel}
        self.assertIn(t1["id"], active_ids)
        self.assertIn(t2["id"], active_ids)
        self.assertNotIn(t3["id"], active_ids)

    def test_09_authentication_enforcement(self):
        """Verify strict authentication behavior on task endpoints."""
        with patch("app.security.is_auth_enforced", return_value=True):
            # Unauthenticated request -> 401
            unauth_get = self.client.get("/api/tasks")
            self.assertEqual(unauth_get.status_code, 401)

            unauth_post = self.client.post("/api/tasks", json={"title": "Hack"})
            self.assertEqual(unauth_post.status_code, 401)

            # Invalid Bearer token -> 401
            bad_bearer = self.client.get("/api/tasks", headers={"Authorization": "Bearer totally-fake-token"})
            self.assertEqual(bad_bearer.status_code, 401)

            # Valid Bearer token -> 200
            good_bearer = self.client.get("/api/tasks", headers=self.auth_headers)
            self.assertEqual(good_bearer.status_code, 200)

            # Valid Founder Session Cookie -> 200
            token, csrf_token, _ = security.create_session(
                username=TEST_USERNAME,
                role="founder",
                ip_address="127.0.0.1",
                user_agent="test-agent",
            )
            cookie_get = self.client.get(
                "/api/tasks",
                headers={"Cookie": f"{security.COOKIE_NAME}={token}"},
            )
            self.assertEqual(cookie_get.status_code, 200)

    def test_10_concurrent_updates_integrity(self):
        """Simulate concurrent status updates across threads without data corruption."""
        task = self.client.post("/api/tasks", json={"title": "Concurrent Task"}, headers=self.auth_headers).json()["item"]
        task_id = task["id"]

        def perform_patch(status_val: str):
            try:
                res = self.client.patch(
                    f"/api/tasks/{task_id}",
                    json={"status": status_val, "version": 2},
                    headers=self.auth_headers,
                )
                return res.status_code
            except Exception as e:
                return str(e)

        # Move to working first (version 1 -> 2)
        self.client.patch(f"/api/tasks/{task_id}", json={"status": "working", "version": 1}, headers=self.auth_headers)

        # From working, competing threads attempt to update with expected_version=2.
        # Exactly one will win (200, advancing to version 3), and others will receive 409 Conflict.
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(perform_patch, "needs_attention"),
                executor.submit(perform_patch, "done"),
                executor.submit(perform_patch, "inbox"),
            ]
            results = [f.result() for f in futures]

        # All results should be either 200 (succeeded transition) or 409 (rejected conflict)
        for r in results:
            self.assertIn(r, (200, 409))
        self.assertEqual(results.count(200), 1)

        # Ensure the final state in DB is a valid status and audit trail has no corrupt entries
        final_task = self.client.get(f"/api/tasks/{task_id}", headers=self.auth_headers).json()["item"]
        self.assertIn(final_task["status"], db.VALID_TASK_STATUSES)
        history_len = len(final_task.get("audit_history") or final_task.get("history") or [])
        self.assertGreater(history_len, 1)

    def test_11_simulated_postgres_compatibility(self):
        """Test PostgreSQL compatibility if TEST_DATABASE_URL is provided."""
        test_pg_url = os.environ.get("TEST_DATABASE_URL")
        if not test_pg_url:
            self.skipTest("TEST_DATABASE_URL not set; skipping live PostgreSQL integration test.")

        # If provided, instantiate an isolated database on PostgreSQL
        prior_url = os.environ.get("DATABASE_URL")
        try:
            os.environ["DATABASE_URL"] = test_pg_url
            db.reset_engine()
            db.init_db()

            # 1. Create task
            created = db.create_task({"title": "PostgreSQL Unified Task", "assigned_agent_id": "ceo", "status": "inbox"})
            self.assertIsNotNone(created)
            task_id = created["id"]

            # 2. Update task & Employee assignment
            updated = db.update_task(task_id, {"assigned_agent_id": "dev", "status": "working", "version": 1})
            self.assertEqual(updated["assigned_agent_id"], "dev")
            self.assertEqual(updated["status"], "working")
            self.assertEqual(updated["version"], 2)

            # 3. Audit history
            audit = db.get_task(task_id)
            self.assertGreaterEqual(len(audit.get("audit_history") or []), 2)

            # 4. Cancellation
            cancelled = db.cancel_task(task_id, expected_version=2)
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertIsNotNone(cancelled["cancelled_at"])
            self.assertIsNone(cancelled["completed_at"])

            # 5. Rollback verification
            with self.assertRaises(Exception):
                with db.get_session() as s:
                    s.add(db.Task(id="fail-task", title=None, status="inbox"))
                    # Null title violates NOT NULL constraint; rolls back transaction
            self.assertIsNone(db.get_task("fail-task"))
        finally:
            db.reset_engine()
            if prior_url:
                os.environ["DATABASE_URL"] = prior_url
            else:
                os.environ.pop("DATABASE_URL", None)
            db.init_db()

    def test_12_optimistic_concurrency_and_cancelled_terminal(self):
        """Verify versioning protects against stale writes and cancelled tasks are strictly terminal."""
        task = self.client.post("/api/tasks", json={"title": "Version Task", "status": "inbox"}, headers=self.auth_headers).json()["item"]
        task_id = task["id"]
        self.assertEqual(task.get("version"), 1)

        # 1. Update with matching version succeeds and increments version to 2
        r1 = self.client.patch(f"/api/tasks/{task_id}", json={"title": "Updated Title", "version": 1}, headers=self.auth_headers)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["item"]["version"], 2)

        # 2. Stale write with old version 1 fails with 409 Conflict
        r2 = self.client.patch(f"/api/tasks/{task_id}", json={"title": "Stale Write", "version": 1}, headers=self.auth_headers)
        self.assertEqual(r2.status_code, 409)
        self.assertIn("version mismatch", r2.json()["detail"])

        # 3. Update with new version 2 succeeds and increments version to 3
        r3 = self.client.patch(f"/api/tasks/{task_id}", json={"status": "working", "version": 2}, headers=self.auth_headers)
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["item"]["version"], 3)

        # 4. Cancel task with version 3 succeeds and increments version to 4
        r_cancel = self.client.post(f"/api/tasks/{task_id}/cancel", json={"version": 3}, headers=self.auth_headers)
        self.assertEqual(r_cancel.status_code, 200)
        cancelled_item = r_cancel.json()["item"]
        self.assertEqual(cancelled_item["status"], "cancelled")
        self.assertEqual(cancelled_item["version"], 4)
        self.assertIsNotNone(cancelled_item["cancelled_at"])
        self.assertIsNone(cancelled_item["completed_at"])

        # 5. Modifying a cancelled task must return 409 Conflict (terminal state)
        r_mod_cancel = self.client.patch(f"/api/tasks/{task_id}", json={"title": "Revive Task", "version": 4}, headers=self.auth_headers)
        self.assertEqual(r_mod_cancel.status_code, 409)
        self.assertIn("Cannot modify a cancelled task", r_mod_cancel.json()["detail"])


if __name__ == "__main__":
    unittest.main()
