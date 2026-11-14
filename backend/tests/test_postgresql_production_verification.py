"""PostgreSQL Production Integration Verification Suite.

Tests live Neon PostgreSQL compatibility against TEST_DATABASE_URL:
- Alembic migrations 0001 -> 0002 -> 0003 -> 0004 -> 0005 (upgrade from empty DB & idempotency).
- Canonical employee seeding and verification (all 7 employees).
- Security state persistence (owner_sessions, login_attempts with advisory lock, websocket_tickets single-use).
- Unified task management (CRUD, status state machine, completed_at, cancelled_at terminal).
- Optimistic Concurrency Control (OCC versioning and PostgreSQL row-level locks).
- Cloudflare AI daily quota reservation (atomic INSERT ON CONFLICT + conditional UPDATE).
- Conversation and message persistence.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app import db, security

TEST_PG_URL = os.getenv("TEST_DATABASE_URL", "")


@unittest.skipUnless(
    bool(TEST_PG_URL and TEST_PG_URL.startswith("postgresql")),
    "TEST_DATABASE_URL not configured. Status: NOT RUN (PostgreSQL credentials unavailable).",
)
class PostgreSQLProductionVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Configure DATABASE_URL for the duration of these tests
        cls.prior_db_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = TEST_PG_URL
        os.environ.pop("AGENTHQ_DB_PATH", None)

        db.reset_engine()
        cls.engine = db.get_engine()
        cls.backend_dir = Path(__file__).resolve().parents[1]
        cls.alembic_cfg = Config(str(cls.backend_dir / "alembic.ini"))
        cls.alembic_cfg.set_main_option("script_location", str(cls.backend_dir / "alembic"))

    @classmethod
    def tearDownClass(cls):
        db.reset_engine()
        if cls.prior_db_url:
            os.environ["DATABASE_URL"] = cls.prior_db_url
        else:
            os.environ.pop("DATABASE_URL", None)

    # =========================================================================
    # 1. Alembic Migrations: 0001 -> 0002 -> 0003 -> 0004 -> 0005
    # =========================================================================
    def test_01_alembic_migrations_upgrade_empty_and_existing(self):
        """Run Alembic migrations to head on PostgreSQL and verify table creation and idempotency."""
        # Run upgrade to head
        command.upgrade(self.alembic_cfg, "head")

        with self.engine.connect() as conn:
            inspector = sa.inspect(conn)
            tables = set(inspector.get_table_names())

            expected_tables = {
                "agents",
                "tasks",
                "task_audit_logs",
                "daily_ai_usage",
                "daily_ai_quota_buckets",
                "runtime_sessions",
                "owner_sessions",
                "login_attempts",
                "websocket_tickets",
                "conversations",
                "conversation_messages",
                "alembic_version",
            }
            for table in expected_tables:
                self.assertIn(table, tables, f"Expected table '{table}' in PostgreSQL database.")

            # Verify task columns
            task_cols = {col["name"]: col for col in inspector.get_columns("tasks")}
            self.assertIn("version", task_cols)
            self.assertIn("cancelled_at", task_cols)
            self.assertIn("completed_at", task_cols)
            self.assertIn("due_date", task_cols)

            # Idempotency check: running upgrade again on existing database succeeds without error
            command.upgrade(self.alembic_cfg, "head")

    # =========================================================================
    # 2. Canonical Employee Seeding & Verification
    # =========================================================================
    def test_02_canonical_employees_seeding_and_integrity(self):
        """Verify all seven canonical employees are seeded and persisted in PostgreSQL."""
        db.seed_agents()

        agents = db.list_agents()
        self.assertEqual(len(agents), 7)
        agent_map = {a["id"]: a for a in agents}

        expected_agents = {
            "ceo": ("Atlas", "AI Orchestrator"),
            "pm": ("Mira", "Project Manager"),
            "dev": ("Arin", "Software Engineer"),
            "kiran": ("Kiran", "Software Engineer"),
            "design": ("Nia", "UI/UX Designer"),
            "research": ("Ira", "Research Analyst"),
            "qa": ("Dev", "QA Engineer"),
        }

        for agent_id, (name, role) in expected_agents.items():
            self.assertIn(agent_id, agent_map)
            self.assertEqual(agent_map[agent_id]["name"], name)
            self.assertEqual(agent_map[agent_id]["role"], role)

    # =========================================================================
    # 3. Security State: Sessions, Rate Limiting, & Single-Use WS Tickets
    # =========================================================================
    def test_03_security_state_persistence_and_advisory_locks(self):
        """Verify owner_sessions, login_attempts with advisory lock, and websocket_tickets in PostgreSQL."""
        username = "founder@agenthq.internal"

        # 3.1 Owner Session
        token, csrf, session_data = security.create_session(
            username=username,
            role="founder",
            ip_address="192.168.1.50",
            user_agent="Postgres-Security-Test",
        )
        self.assertIsNotNone(token)
        session_id = session_data["session_id"]

        # Validate from PostgreSQL
        verified = security.verify_session_token(token)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["username"], username)

        # Revoke session
        revoked = security.revoke_session(session_id)
        self.assertTrue(revoked)
        self.assertIsNone(security.verify_session_token(token))

        # 3.2 Login Rate Limiting (Atomic PostgreSQL transaction / advisory lock)
        test_ip = "192.168.1.99"
        db.reset_login_rate_limit(test_ip)

        for _ in range(4):
            db.record_login_attempt(ip_address=test_ip, username=username, success=False)
        is_limited, retry_after = db.check_login_rate_limit(ip_address=test_ip, max_attempts=5, window_seconds=60)
        self.assertFalse(is_limited)
        self.assertEqual(retry_after, 0)

        # 5th failure trips rate limit
        db.record_login_attempt(ip_address=test_ip, username=username, success=False)
        is_limited, retry_after = db.check_login_rate_limit(ip_address=test_ip, max_attempts=5, window_seconds=60)
        self.assertTrue(is_limited)
        self.assertGreater(retry_after, 0)
        db.reset_login_rate_limit(test_ip)

        # 3.3 WebSocket Tickets (Atomic single-use)
        ws_ticket, ttl = security.create_ws_ticket(username=username)
        self.assertIsNotNone(ws_ticket)

        is_valid, user = security.verify_and_consume_ws_ticket(ws_ticket)
        self.assertTrue(is_valid)
        self.assertEqual(user, username)

        # Re-consuming must fail
        reconsumed, _ = security.verify_and_consume_ws_ticket(ws_ticket)
        self.assertFalse(reconsumed)

    # =========================================================================
    # 4. Task Lifecycle, Concurrency, and Audit History on PostgreSQL
    # =========================================================================
    def test_04_task_lifecycle_occ_and_terminal_cancellation(self):
        """Verify task lifecycle, version concurrency, and terminal cancellation on PostgreSQL."""
        # 1. Create task
        created = db.create_task({
            "title": "PostgreSQL Neural Engine Optimization",
            "description": "Optimize query plans and row locks on Neon",
            "priority": "normal",
            "status": "inbox",
            "assigned_agent_id": "pm",
        })
        self.assertIsNotNone(created)
        task_id = created["id"]
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["assigned_agent_name"], "Mira")

        # 2. Update priority & reassign to Arin (version 1 -> 2)
        updated_1 = db.update_task(task_id, {
            "assigned_agent_id": "dev",
            "priority": "high",
            "version": 1,
        })
        self.assertEqual(updated_1["version"], 2)
        self.assertEqual(updated_1["assigned_agent_name"], "Arin")
        self.assertEqual(updated_1["priority"], "high")

        # 3. OCC Stale write rejection: attempting to update with old version 1 must raise Conflict
        with self.assertRaises(ValueError) as ctx:
            db.update_task(task_id, {"title": "Stale Write Attempt", "version": 1})
        self.assertIn("Conflict: Task version mismatch", str(ctx.exception))

        # 4. Advance through state machine: inbox -> working (version 2 -> 3)
        updated_2 = db.update_task(task_id, {"status": "working", "version": 2})
        self.assertEqual(updated_2["status"], "working")
        self.assertEqual(updated_2["version"], 3)

        # 5. Complete task: working -> done (version 3 -> 4)
        completed = db.update_task(task_id, {"status": "done", "version": 3})
        self.assertEqual(completed["status"], "done")
        self.assertEqual(completed["version"], 4)
        self.assertIsNotNone(completed["completed_at"])
        self.assertIsNone(completed["cancelled_at"])

        # 6. Reopen task: done -> working (version 4 -> 5, completed_at cleared)
        reopened = db.update_task(task_id, {"status": "working", "version": 4})
        self.assertEqual(reopened["status"], "working")
        self.assertEqual(reopened["version"], 5)
        self.assertIsNone(reopened["completed_at"])

        # 7. Cancel task (version 5 -> 6, cancelled_at populated)
        cancelled = db.cancel_task(task_id, expected_version=5, note="Cancelled on PostgreSQL.")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["version"], 6)
        self.assertIsNotNone(cancelled["cancelled_at"])
        self.assertIsNone(cancelled["completed_at"])

        # 8. Modifying a cancelled task must raise Conflict (terminal state)
        with self.assertRaises(ValueError) as ctx_term:
            db.update_task(task_id, {"title": "Revive Task", "version": 6})
        self.assertIn("Cannot modify a cancelled task", str(ctx_term.exception))

        # 9. Verify audit trail in PostgreSQL
        task_data = db.get_task(task_id)
        history = task_data.get("audit_history") or []
        self.assertGreaterEqual(len(history), 5)
        actions = [entry["action"] for entry in history]
        self.assertEqual(actions[0], "created")
        self.assertIn("assigned", actions)
        self.assertIn("status_changed", actions)
        self.assertEqual(actions[-1], "cancelled")

    # =========================================================================
    # 5. Cloudflare Quota Reservation on PostgreSQL
    # =========================================================================
    def test_05_cloudflare_quota_atomic_reservation(self):
        """Verify PostgreSQL atomic quota reservation (INSERT ON CONFLICT + conditional UPDATE)."""
        provider = "cloudflare"
        model = "@cf/meta/llama-3.3-70b-instruct"

        status_before = db.get_quota_status(provider=provider)
        current = status_before["current_neurons"]
        test_limit = current + 5000.0

        # Reserve neurons
        res1 = db.reserve_ai_quota(
            provider=provider,
            model=model,
            estimated_input_tokens=100,
            max_output_tokens=700,
            daily_limit=test_limit,
        )
        self.assertIsNotNone(res1)
        self.assertEqual(res1.provider, provider)
        self.assertEqual(res1.model, model)
        self.assertGreater(res1.provisional_neurons, 0.0)

        # Check recorded usage in PostgreSQL
        status = db.get_quota_status(provider=provider, daily_limit=test_limit)
        self.assertIsNotNone(status)
        self.assertGreaterEqual(status["current_neurons"], current + res1.provisional_neurons)

        # Exceed limit
        with self.assertRaises(db.QuotaExceededException):
            db.reserve_ai_quota(
                provider=provider,
                model=model,
                estimated_input_tokens=100,
                max_output_tokens=700,
                daily_limit=status["current_neurons"],
            )

    # =========================================================================
    # 6. Conversation & Message Persistence on PostgreSQL
    # =========================================================================
    def test_06_conversation_and_message_persistence(self):
        """Verify conversation creation, message appending, and retrieval in PostgreSQL."""
        db.seed_agents()
        conv = db.create_conversation("pm", "Quarterly Roadmap Review")
        self.assertIsNotNone(conv)
        conv_id = conv["id"]

        msg1 = db.add_conversation_message(conv_id, "user", "What are our primary goals for Q4?")
        msg2 = db.add_conversation_message(conv_id, "assistant", "Our primary goal is the unified cloud container deployment.")

        retrieved_conv = db.get_conversation(conv_id)
        self.assertIsNotNone(retrieved_conv)
        messages = db.list_conversation_messages(conv_id)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "What are our primary goals for Q4?")
        self.assertEqual(messages[1]["content"], "Our primary goal is the unified cloud container deployment.")


if __name__ == "__main__":
    unittest.main()

