"""Phase 2E - Production Integration Verification Test Suite.

Covers:
- Part 2: Canonical status vocabulary & query filter validation (rejects invalid status filters with 400).
- Part 3: Optimistic concurrency control across independent DB connections, required expected_version,
          stale version 409 rejection, and guarantee that failed updates create zero audit records.
- Part 4: Complete 15-step real Founder workflow against authoritative AgentHQ backend & Hermes3D contract.
- Part 5: Full security verification (Founder authentication, session persistence, Bearer token, WebSocket tickets, zero secret leakage).
"""

from __future__ import annotations

import concurrent.futures
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from app import db, security
from app.main import app

TEST_USERNAME = "founder@agenthq.internal"
TEST_PASSWORD = "Test-Founder-Password-2026!"
RUNTIME_TOKEN = "test-runtime-token-phase2e-secret-xyz-987"


class Phase2EProductionVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="phase2e_test_")
        self.db_path = Path(self.temp_dir) / "agenthq_phase2e.db"

        password_hash = security.hash_password(TEST_PASSWORD)
        self.env_patch = patch.dict(
            os.environ,
            {
                "AGENTHQ_DB_PATH": str(self.db_path),
                "DATABASE_URL": f"sqlite:///{self.db_path.as_posix()}",
                "OWNER_USERNAME": TEST_USERNAME,
                "OWNER_PASSWORD_HASH": password_hash,
                "SESSION_SECRET": "test-session-secret-phase2e-32bytes-long-key-xyz-12345",
                "RUNTIME_API_TOKEN": RUNTIME_TOKEN,
                "AGENTHQ_ENFORCE_AUTH": "true",
            },
        )
        self.env_patch.start()

        db.reset_engine()
        db.init_db()

        self.client = TestClient(app)
        self.auth_headers = {"Authorization": f"Bearer {RUNTIME_TOKEN}"}

    def tearDown(self):
        db.reset_engine()
        self.env_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # PART 2: Canonical Status Vocabulary & Query Filter Validation
    # =========================================================================
    def test_part2_canonical_status_vocabulary_and_filter_rejection(self):
        """Verify status vocabulary consistency and ensure unknown states are rejected with 400."""
        # 1. Valid statuses
        self.assertEqual(
            db.VALID_TASK_STATUSES,
            {"inbox", "queued", "scheduled", "working", "needs_attention", "done", "cancelled"},
        )

        # 2. Creating a task with invalid status must be rejected with 400
        res_bad_create = self.client.post(
            "/api/tasks",
            json={"title": "Bad Status Task", "status": "corrupted_status"},
            headers=self.auth_headers,
        )
        self.assertEqual(res_bad_create.status_code, 400)
        self.assertIn("Invalid task status", res_bad_create.json()["detail"])

        # 3. Filtering GET /api/tasks by invalid status must be rejected with 400 (do not silently convert)
        res_bad_filter = self.client.get(
            "/api/tasks?status=gibberish_status",
            headers=self.auth_headers,
        )
        self.assertEqual(res_bad_filter.status_code, 400)
        self.assertIn("Invalid task status filter", res_bad_filter.json()["detail"])

        # 4. Filtering GET /api/tasks by invalid employee must be rejected with 400
        res_bad_emp = self.client.get(
            "/api/tasks?assigned_agent_id=unknown_agent",
            headers=self.auth_headers,
        )
        self.assertEqual(res_bad_emp.status_code, 400)
        self.assertIn("Invalid employee filter", res_bad_emp.json()["detail"])

        # 5. Valid legacy statuses normalize cleanly
        res_legacy = self.client.post(
            "/api/tasks",
            json={"title": "Legacy Todo Task", "status": "todo"},
            headers=self.auth_headers,
        )
        self.assertEqual(res_legacy.status_code, 201)
        self.assertEqual(res_legacy.json()["item"]["status"], "inbox")

    # =========================================================================
    # PART 3: Optimistic Concurrency Control Across Independent Connections
    # =========================================================================
    def test_part3_occ_expected_version_required_and_no_audit_on_failure(self):
        """Verify expected_version is required, stale version returns 409, and failed writes create no audit records."""
        # 1. Create task
        res_create = self.client.post(
            "/api/tasks",
            json={"title": "OCC Task", "status": "inbox"},
            headers=self.auth_headers,
        )
        self.assertEqual(res_create.status_code, 201)
        task = res_create.json()["item"]
        task_id = task["id"]
        self.assertEqual(task["version"], 1)

        # Baseline audit count = 1 ('created')
        task_data = db.get_task(task_id)
        self.assertEqual(len(task_data["audit_history"]), 1)

        # 2. Update without 'version' must fail with 400
        res_no_ver = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"title": "Update Without Version"},
            headers=self.auth_headers,
        )
        self.assertEqual(res_no_ver.status_code, 400)
        self.assertIn("expected_version is required", res_no_ver.json()["detail"])

        # Audit history must NOT have increased
        task_data = db.get_task(task_id)
        self.assertEqual(len(task_data["audit_history"]), 1)

        # 3. Update with stale version (e.g. 99) must fail with 409 Conflict
        res_stale = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"title": "Update Stale", "version": 99},
            headers=self.auth_headers,
        )
        self.assertEqual(res_stale.status_code, 409)
        self.assertIn("Conflict: Task version mismatch", res_stale.json()["detail"])

        # Audit history must NOT have increased
        task_data = db.get_task(task_id)
        self.assertEqual(len(task_data["audit_history"]), 1)

        # 4. Failed update due to illegal status jump must fail with 409 and NOT create audit log
        res_bad_jump = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "done", "version": 1},
            headers=self.auth_headers,
        )
        self.assertEqual(res_bad_jump.status_code, 409)
        self.assertIn("Invalid status transition", res_bad_jump.json()["detail"])
        task_data = db.get_task(task_id)
        self.assertEqual(len(task_data["audit_history"]), 1)

        # 5. Valid update succeeds and creates exactly 1 audit record
        res_valid = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "working", "version": 1},
            headers=self.auth_headers,
        )
        self.assertEqual(res_valid.status_code, 200)
        task_data = db.get_task(task_id)
        self.assertEqual(task_data["version"], 2)
        self.assertEqual(len(task_data["audit_history"]), 2)

        # 6. Cancellation without version must fail with 400
        res_no_ver_cancel = self.client.post(
            f"/api/tasks/{task_id}/cancel",
            headers=self.auth_headers,
        )
        self.assertEqual(res_no_ver_cancel.status_code, 400)
        self.assertIn("expected_version is required", res_no_ver_cancel.json()["detail"])
        task_data = db.get_task(task_id)
        self.assertEqual(len(task_data["audit_history"]), 2)

        # 7. Cancellation with stale version must fail with 409
        res_stale_cancel = self.client.post(
            f"/api/tasks/{task_id}/cancel",
            json={"version": 1},
            headers=self.auth_headers,
        )
        self.assertEqual(res_stale_cancel.status_code, 409)
        self.assertIn("Conflict: Task version mismatch", res_stale_cancel.json()["detail"])
        task_data = db.get_task(task_id)
        self.assertEqual(len(task_data["audit_history"]), 2)

    def test_part3_concurrent_updates_independent_connections(self):
        """Simulate concurrent updates across independent database sessions; exactly one wins and audit count is strictly conserved."""
        res_create = self.client.post(
            "/api/tasks",
            json={"title": "Parallel Race Task", "status": "inbox"},
            headers=self.auth_headers,
        )
        self.assertEqual(res_create.status_code, 201)
        task_id = res_create.json()["item"]["id"]

        # Advance to working (version 1 -> 2)
        r_work = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "working", "version": 1},
            headers=self.auth_headers,
        )
        self.assertEqual(r_work.status_code, 200)
        self.assertEqual(r_work.json()["item"]["version"], 2)

        def worker_update(assigned_agent: str):
            # Each worker uses an independent Client / HTTP request
            c = TestClient(app)
            return c.patch(
                f"/api/tasks/{task_id}",
                json={"assigned_agent_id": assigned_agent, "version": 2},
                headers=self.auth_headers,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            f1 = executor.submit(worker_update, "pm")
            f2 = executor.submit(worker_update, "dev")
            f3 = executor.submit(worker_update, "qa")
            f4 = executor.submit(worker_update, "design")

            responses = [f.result() for f in (f1, f2, f3, f4)]

        statuses = [r.status_code for r in responses]
        # Exactly one must succeed with 200; the remaining three must receive 409 Conflict
        self.assertEqual(statuses.count(200), 1, f"Expected exactly one 200, got: {statuses}")
        self.assertEqual(statuses.count(409), 3, f"Expected three 409s, got: {statuses}")

        # Verify database state: version must be exactly 3, and audit history has exactly 3 entries (created, status_changed, assigned)
        task_record = db.get_task(task_id)
        self.assertEqual(task_record["version"], 3)
        self.assertEqual(len(task_record["audit_history"]), 3)

    # =========================================================================
    # PART 4: Real Founder Workflow Verification (15 Steps)
    # =========================================================================
    def test_part4_complete_15_step_real_founder_workflow(self):
        """Execute and verify the exact 15-step Founder workflow through AgentHQ APIs and database."""
        # 1. Founder logs into Hermes3D / AgentHQ
        login_res = self.client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        self.assertEqual(login_res.status_code, 200)
        session_cookie = login_res.cookies.get(security.COOKIE_NAME)
        self.assertIsNotNone(session_cookie)
        session_headers = {"Cookie": f"{security.COOKIE_NAME}={session_cookie}"}

        # 2. Opens the 3D office (verifies state and health)
        health_res = self.client.get("/health", headers=session_headers)
        self.assertEqual(health_res.status_code, 200)
        self.assertEqual(health_res.json()["status"], "ok")

        # 3. Opens Kanban (retrieves initial tasks)
        kanban_res = self.client.get("/api/tasks", headers=session_headers)
        self.assertEqual(kanban_res.status_code, 200)
        initial_count = kanban_res.json()["total"]

        # 4. Creates a task
        create_res = self.client.post(
            "/api/tasks",
            json={
                "title": "Build Autonomous Workspace Engine",
                "description": "Architect the unified 3D runtime and persistent AI core",
                "priority": "normal",
                "status": "inbox",
            },
            headers=session_headers,
        )
        self.assertEqual(create_res.status_code, 201)
        task = create_res.json()["item"]
        task_id = task["id"]
        self.assertEqual(task["version"], 1)

        # 5. Assigns it to Mira (pm)
        assign_mira = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"assigned_agent_id": "pm", "version": 1},
            headers=session_headers,
        )
        self.assertEqual(assign_mira.status_code, 200)
        item_mira = assign_mira.json()["item"]
        self.assertEqual(item_mira["assigned_agent_id"], "pm")
        self.assertEqual(item_mira["assigned_agent_name"], "Mira")
        self.assertEqual(item_mira["version"], 2)

        # 6. Updates its priority to high
        prio_res = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"priority": "high", "version": 2},
            headers=session_headers,
        )
        self.assertEqual(prio_res.status_code, 200)
        item_prio = prio_res.json()["item"]
        self.assertEqual(item_prio["priority"], "high")
        self.assertEqual(item_prio["version"], 3)

        # 7. Reassigns it to Arin (dev)
        reassign_arin = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"assigned_agent_id": "dev", "version": 3},
            headers=session_headers,
        )
        self.assertEqual(reassign_arin.status_code, 200)
        item_arin = reassign_arin.json()["item"]
        self.assertEqual(item_arin["assigned_agent_id"], "dev")
        self.assertEqual(item_arin["assigned_agent_name"], "Arin")
        self.assertEqual(item_arin["version"], 4)

        # 8. Changes status to working
        work_res = self.client.patch(
            f"/api/tasks/{task_id}",
            json={"status": "working", "version": 4},
            headers=session_headers,
        )
        self.assertEqual(work_res.status_code, 200)
        item_work = work_res.json()["item"]
        self.assertEqual(item_work["status"], "working")
        self.assertEqual(item_work["version"], 5)

        # 9. Reloads the browser (fresh client instance using same session cookie)
        fresh_browser = TestClient(app)

        # 10. Confirms task persistence
        reload_res = fresh_browser.get(f"/api/tasks/{task_id}", headers=session_headers)
        self.assertEqual(reload_res.status_code, 200)
        reloaded = reload_res.json()["item"]
        self.assertEqual(reloaded["id"], task_id)
        self.assertEqual(reloaded["assigned_agent_id"], "dev")
        self.assertEqual(reloaded["priority"], "high")
        self.assertEqual(reloaded["status"], "working")
        self.assertEqual(reloaded["version"], 5)

        # 11. Inspects the audit history
        history = reloaded.get("audit_history") or reloaded.get("history") or []
        actions = [entry["action"] for entry in history]
        self.assertEqual(actions[0], "created")
        self.assertIn("assigned", actions)
        self.assertIn("updated", actions)
        self.assertIn("status_changed", actions)

        # 12. Completes the task
        done_res = fresh_browser.patch(
            f"/api/tasks/{task_id}",
            json={"status": "done", "version": 5},
            headers=session_headers,
        )
        self.assertEqual(done_res.status_code, 200)
        done_item = done_res.json()["item"]
        self.assertEqual(done_item["status"], "done")
        self.assertEqual(done_item["version"], 6)

        # 13. Verifies completed_at
        self.assertIsNotNone(done_item["completed_at"])
        self.assertIsNone(done_item["cancelled_at"])

        # 14. Cancels a separate task
        separate_task_res = fresh_browser.post(
            "/api/tasks",
            json={"title": "Deprecate Legacy Modules", "status": "inbox"},
            headers=session_headers,
        )
        self.assertEqual(separate_task_res.status_code, 201)
        sep_id = separate_task_res.json()["item"]["id"]

        cancel_sep = fresh_browser.post(
            f"/api/tasks/{sep_id}/cancel",
            json={"version": 1, "note": "Cancelled by Founder during review."},
            headers=session_headers,
        )
        self.assertEqual(cancel_sep.status_code, 200)
        cancelled_item = cancel_sep.json()["item"]
        self.assertEqual(cancelled_item["status"], "cancelled")
        self.assertEqual(cancelled_item["version"], 2)

        # 15. Verifies cancelled_at
        self.assertIsNotNone(cancelled_item["cancelled_at"])
        self.assertIsNone(cancelled_item["completed_at"])

        # Cancelled task is terminal
        mod_terminal = fresh_browser.patch(
            f"/api/tasks/{sep_id}",
            json={"title": "Attempted Revive", "version": 2},
            headers=session_headers,
        )
        self.assertEqual(mod_terminal.status_code, 409)
        self.assertIn("Cannot modify a cancelled task", mod_terminal.json()["detail"])

    # =========================================================================
    # PART 5: Complete Application Security Verification
    # =========================================================================
    def test_part5_comprehensive_security_verification(self):
        """Verify Founder authentication, session persistence, Bearer token, WebSocket tickets, and secret leakage prevention."""
        # 1. Founder authentication rejects wrong credentials
        bad_auth = self.client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": "WrongPassword-123!"},
        )
        self.assertEqual(bad_auth.status_code, 401)

        # Rate limiting triggers on repeated brute force
        for _ in range(4):
            self.client.post(
                "/api/auth/login",
                json={"username": TEST_USERNAME, "password": "WrongPassword-123!"},
            )
        brute_force = self.client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": "WrongPassword-123!"},
        )
        self.assertEqual(brute_force.status_code, 429)
        self.assertIn("Too many failed login attempts", brute_force.json()["detail"])

        # 2. Session persistence
        session_token, csrf_token, session_data = security.create_session(
            username=TEST_USERNAME,
            role="founder",
            ip_address="10.0.0.1",
            user_agent="agent-security-test",
        )
        session_info = security.verify_session_token(session_token)
        self.assertIsNotNone(session_info)
        self.assertEqual(session_info["username"], TEST_USERNAME)

        # Instant revocation on logout
        security.revoke_session(session_data["session_id"])
        self.assertIsNone(security.verify_session_token(session_token))

        # 3. Runtime Bearer token authorization
        unauth = self.client.get("/api/tasks")
        self.assertEqual(unauth.status_code, 401)

        bad_bearer = self.client.get("/api/tasks", headers={"Authorization": "Bearer fake-token"})
        self.assertEqual(bad_bearer.status_code, 401)

        good_bearer = self.client.get("/api/tasks", headers={"Authorization": f"Bearer {RUNTIME_TOKEN}"})
        self.assertEqual(good_bearer.status_code, 200)

        # 4. WebSocket ticket authorization
        # Issue single-use ticket
        ticket_raw, ttl = security.create_ws_ticket(username=TEST_USERNAME)
        self.assertIsNotNone(ticket_raw)

        # Consume ticket
        is_valid, user = security.verify_and_consume_ws_ticket(ticket_raw)
        self.assertTrue(is_valid)
        self.assertEqual(user, TEST_USERNAME)

        # Re-consuming the same ticket fails (single-use guarantee)
        reconsumed, reason = security.verify_and_consume_ws_ticket(ticket_raw)
        self.assertFalse(reconsumed)

        # 5. Zero secrets in responses
        task_res = self.client.get("/api/tasks", headers=self.auth_headers)
        raw_text = task_res.text
        self.assertNotIn(RUNTIME_TOKEN, raw_text)
        self.assertNotIn(TEST_PASSWORD, raw_text)


if __name__ == "__main__":
    unittest.main()
