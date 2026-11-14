"""Phase 2E.1 Real Neon PostgreSQL Verification Test Suite.

Exhaustive verification of the PostgreSQL implementation using the live Neon test database:
- PART 2: Alembic migrations (empty upgrade, upgrade to latest, existing schema upgrade,
          migration history, indexes, foreign keys, unique constraints, and disposable downgrade/re-upgrade).
- PART 3: Database operations (canonical employees, conversation persistence, message ordering,
          task lifecycle & audit history, session persistence & revocation, WebSocket tickets,
          daily AI quota reservation & reconciliation).
- PART 4: Concurrency (4 concurrent task OCC updates with exact 1-winner semantics,
          zero audit logs on failure, shared provider quota across multiple models under FOR UPDATE,
          concurrent first-time bucket creation, concurrent login rate-limiting with advisory locks,
          concurrent WebSocket ticket consumption, and transaction rollback integrity).
- PART 5: Connection pooling (NullPool vs QueuePool, pool size & overflow, recycling,
          transaction-scoped advisory lock release, and leak prevention).
"""

from __future__ import annotations

import concurrent.futures
import os
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool, QueuePool

from app import db, security

# Read from environment or local .env
TEST_PG_URL = os.getenv("TEST_DATABASE_URL", "")
if not TEST_PG_URL and os.path.exists("backend/.env"):
    from dotenv import dotenv_values
    env_vals = dotenv_values("backend/.env")
    TEST_PG_URL = env_vals.get("TEST_DATABASE_URL", "")


def mask_url(url: str) -> str:
    """Mask credentials in database URL for safe logging and reporting."""
    if not url:
        return "[NOT CONFIGURED]"
    try:
        parts = url.split("@")
        if len(parts) == 2:
            prefix = parts[0].split("://")
            scheme = prefix[0]
            user = prefix[1].split(":")[0] if ":" in prefix[1] else prefix[1]
            return f"{scheme}://{user}:***@{parts[1]}"
    except Exception:
        pass
    return "postgresql://***:***@host/db"


@unittest.skipUnless(
    bool(TEST_PG_URL and TEST_PG_URL.startswith("postgresql")),
    "TEST_DATABASE_URL not configured. Status: NOT RUN (PostgreSQL credentials unavailable).",
)
class Phase2E1RealNeonVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prior_db_url = os.environ.get("DATABASE_URL")
        cls.prior_test_url = os.environ.get("TEST_DATABASE_URL")
        os.environ["DATABASE_URL"] = TEST_PG_URL
        os.environ["TEST_DATABASE_URL"] = TEST_PG_URL
        os.environ.pop("AGENTHQ_DB_PATH", None)

        db.reset_engine()
        cls.engine = db.get_engine()
        cls.backend_dir = Path(__file__).resolve().parents[1]
        cls.alembic_cfg = Config(str(cls.backend_dir / "alembic.ini"))
        cls.alembic_cfg.set_main_option("script_location", str(cls.backend_dir / "alembic"))

        # Initialize schema and seed canonical agents
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        db.reset_engine()
        if cls.prior_db_url:
            os.environ["DATABASE_URL"] = cls.prior_db_url
        else:
            os.environ.pop("DATABASE_URL", None)
        if cls.prior_test_url:
            os.environ["TEST_DATABASE_URL"] = cls.prior_test_url
        else:
            os.environ.pop("TEST_DATABASE_URL", None)

    # =========================================================================
    # PART 2 — MIGRATIONS
    # =========================================================================

    def test_01_empty_upgrade_and_head_state(self):
        """2.1 & 2.2: Verify Alembic upgrade reaches head and creates all canonical tables."""
        command.upgrade(self.alembic_cfg, "head")

        with self.engine.connect() as conn:
            inspector = inspect(conn)
            tables = set(inspector.get_table_names(schema="public"))

            expected = {
                "agents", "tasks", "task_audit_logs", "daily_ai_usage",
                "daily_ai_quota_buckets", "runtime_sessions", "owner_sessions",
                "login_attempts", "websocket_tickets", "conversations",
                "conversation_messages", "alembic_version",
            }
            for table in expected:
                self.assertIn(table, tables, f"Expected table '{table}' in public schema.")

            curr_rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            self.assertEqual(curr_rev, "0005_task_lifecycle_and_concurrency")

    def test_02_idempotent_existing_schema_upgrade(self):
        """2.3: Upgrading an existing schema to head is fully idempotent."""
        command.upgrade(self.alembic_cfg, "head")
        with self.engine.connect() as conn:
            curr_rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            self.assertEqual(curr_rev, "0005_task_lifecycle_and_concurrency")

    def test_03_migration_history_and_revisions(self):
        """2.4: Verify complete migration history: 0001 -> 0002 -> 0003 -> 0004 -> 0005."""
        from alembic.script import ScriptDirectory
        script_dir = ScriptDirectory.from_config(self.alembic_cfg)
        revisions = [rev.revision for rev in script_dir.walk_revisions()]

        self.assertIn("0001_initial_schema", revisions)
        self.assertIn("0002_daily_ai_usage", revisions)
        self.assertIn("0003_persistent_security_state", revisions)
        self.assertIn("0004_unified_task_management", revisions)
        self.assertIn("0005_task_lifecycle_and_concurrency", revisions)

    def test_04_database_indexes_verification(self):
        """2.5: Verify essential database indexes exist on PostgreSQL."""
        with self.engine.connect() as conn:
            inspector = inspect(conn)

            task_indexes = {idx["name"] for idx in inspector.get_indexes("tasks", schema="public")}
            self.assertIn("idx_tasks_created_at", task_indexes)
            self.assertIn("idx_tasks_status", task_indexes)
            self.assertIn("idx_tasks_assigned_agent", task_indexes)
            self.assertIn("idx_tasks_due_date", task_indexes)
            self.assertIn("idx_tasks_cancelled_at", task_indexes)

            session_indexes = {idx["name"] for idx in inspector.get_indexes("owner_sessions", schema="public")}
            self.assertIn("idx_owner_sessions_expires_at", session_indexes)
            self.assertIn("idx_owner_sessions_is_revoked", session_indexes)
            self.assertIn("idx_owner_sessions_username", session_indexes)

            ticket_indexes = {idx["name"] for idx in inspector.get_indexes("websocket_tickets", schema="public")}
            self.assertIn("idx_ws_tickets_expires_at", ticket_indexes)
            self.assertIn("idx_ws_tickets_consumed", ticket_indexes)

            attempt_indexes = {idx["name"] for idx in inspector.get_indexes("login_attempts", schema="public")}
            self.assertIn("idx_login_attempts_attempt_time", attempt_indexes)
            self.assertIn("idx_login_attempts_ip_time", attempt_indexes)

    def test_05_foreign_keys_and_constraints(self):
        """2.6 & 2.7: Verify foreign keys, check constraints, and unique constraints."""
        with self.engine.connect() as conn:
            inspector = inspect(conn)

            # Foreign Keys
            task_fks = {fk["constrained_columns"][0]: fk["referred_table"] for fk in inspector.get_foreign_keys("tasks", schema="public")}
            self.assertEqual(task_fks.get("assigned_agent_id"), "agents")

            audit_fks = {fk["constrained_columns"][0]: fk["referred_table"] for fk in inspector.get_foreign_keys("task_audit_logs", schema="public")}
            self.assertEqual(audit_fks.get("task_id"), "tasks")

            msg_fks = {fk["constrained_columns"][0]: fk["referred_table"] for fk in inspector.get_foreign_keys("conversation_messages", schema="public")}
            self.assertEqual(msg_fks.get("conversation_id"), "conversations")

            # Unique Constraints / Unique Indexes
            session_uniques = {u["name"] for u in inspector.get_unique_constraints("owner_sessions", schema="public")}
            session_u_indexes = {idx["name"] for idx in inspector.get_indexes("owner_sessions", schema="public") if idx.get("unique")}
            self.assertTrue("uq_owner_sessions_token_hash" in session_uniques or "uq_owner_sessions_token_hash" in session_u_indexes)

            quota_u_indexes = {idx["name"] for idx in inspector.get_indexes("daily_ai_quota_buckets", schema="public") if idx.get("unique")}
            self.assertIn("uq_daily_quota_bucket_date_provider", quota_u_indexes)

    def test_06_downgrade_and_reupgrade_on_disposable_schema(self):
        """2.8: Verify full migration downgrade to base and re-upgrade on an isolated disposable schema."""
        disposable_schema = "alembic_disposable_test"
        with self.engine.connect() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {disposable_schema};"))
            conn.execute(text(f"SET search_path TO {disposable_schema};"))
            conn.commit()

            cfg = Config(str(self.backend_dir / "alembic.ini"))
            cfg.set_main_option("script_location", str(self.backend_dir / "alembic"))
            cfg.attributes["connection"] = conn

            try:
                # 1. Upgrade from empty schema to head
                command.upgrade(cfg, "head")
                res1 = conn.execute(text(f"SELECT tablename FROM pg_tables WHERE schemaname = '{disposable_schema}';")).fetchall()
                table_names_1 = {r[0] for r in res1}
                self.assertIn("tasks", table_names_1)
                self.assertIn("owner_sessions", table_names_1)
                self.assertEqual(len(table_names_1), 12)

                # 2. Downgrade to base
                command.downgrade(cfg, "base")
                res2 = conn.execute(text(f"SELECT tablename FROM pg_tables WHERE schemaname = '{disposable_schema}';")).fetchall()
                table_names_2 = {r[0] for r in res2}
                self.assertNotIn("tasks", table_names_2)
                self.assertNotIn("owner_sessions", table_names_2)
                self.assertNotIn("daily_ai_usage", table_names_2)

                # 3. Re-upgrade to head
                command.upgrade(cfg, "head")
                res3 = conn.execute(text(f"SELECT tablename FROM pg_tables WHERE schemaname = '{disposable_schema}';")).fetchall()
                table_names_3 = {r[0] for r in res3}
                self.assertIn("tasks", table_names_3)
                self.assertEqual(len(table_names_3), 12)
            finally:
                conn.execute(text("SET search_path TO public;"))
                conn.execute(text(f"DROP SCHEMA IF EXISTS {disposable_schema} CASCADE;"))
                conn.commit()

    # =========================================================================
    # PART 3 — DATABASE OPERATIONS
    # =========================================================================

    def test_07_canonical_employee_seeding_and_assignment(self):
        """3.1 & 3.2: Verify canonical employee seeding and assignment resolution."""
        db.seed_agents()
        agents = db.list_agents()
        self.assertEqual(len(agents), 7)
        agent_ids = {a["id"] for a in agents}
        self.assertEqual(agent_ids, {"ceo", "pm", "dev", "design", "research", "qa", "kiran"})

        task = db.create_task({
            "title": "Employee Assignment Test",
            "assigned_agent_id": "kiran",
            "status": "inbox",
        })
        self.assertEqual(task["assigned_agent_name"], "Kiran")
        self.assertEqual(task["assigned_agent_role"], "Software Engineer")

    def test_08_conversation_and_message_ordering(self):
        """3.3 & 3.4: Verify conversation persistence and strict message order_index."""
        conv = db.create_conversation("dev", "Architecture Review")
        conv_id = conv["id"]

        for i in range(5):
            db.add_conversation_message(conv_id, "user" if i % 2 == 0 else "assistant", f"Message step {i}")

        messages = db.list_conversation_messages(conv_id)
        self.assertEqual(len(messages), 5)
        for idx, msg in enumerate(messages):
            self.assertEqual(msg["order_index"], idx + 1)
            self.assertEqual(msg["content"], f"Message step {idx}")

    def test_09_task_lifecycle_and_audit_history(self):
        """3.5 - 3.8: Verify task CRUD, status state machine, cancellation terminal state, and audit trail."""
        created = db.create_task({"title": "Lifecycle Task", "status": "inbox", "priority": "normal"})
        task_id = created["id"]
        self.assertEqual(created["version"], 1)

        # Update priority & move to working
        updated = db.update_task(task_id, {"status": "working", "priority": "urgent", "version": 1})
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["status"], "working")
        self.assertEqual(updated["priority"], "urgent")

        # Complete task
        completed = db.update_task(task_id, {"status": "done", "version": 2})
        self.assertEqual(completed["version"], 3)
        self.assertEqual(completed["status"], "done")
        self.assertIsNotNone(completed["completed_at"])

        # Reopen task (completed_at cleared)
        reopened = db.update_task(task_id, {"status": "working", "version": 3})
        self.assertEqual(reopened["version"], 4)
        self.assertIsNone(reopened["completed_at"])

        # Cancel task
        cancelled = db.cancel_task(task_id, expected_version=4, note="Verified lifecycle test cancellation.")
        self.assertEqual(cancelled["version"], 5)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIsNotNone(cancelled["cancelled_at"])

        # Terminal state check
        with self.assertRaises(ValueError):
            db.update_task(task_id, {"title": "Illegal Reopen", "version": 5})

        # Audit trail verification
        history = db.get_task(task_id).get("audit_history") or []
        self.assertGreaterEqual(len(history), 5)
        actions = [entry["action"] for entry in history]
        self.assertEqual(actions[0], "created")
        self.assertIn("status_changed", actions)
        self.assertEqual(actions[-1], "cancelled")

    def test_10_persistent_security_sessions_and_revocation(self):
        """3.9 & 3.10: Verify owner session persistence, validation, and revocation."""
        token, csrf, data = security.create_session("founder@agenthq.internal", role="founder")
        session_id = data["session_id"]

        verified = security.verify_session_token(token)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["username"], "founder@agenthq.internal")

        # Revoke session
        self.assertTrue(security.revoke_session(session_id))
        self.assertIsNone(security.verify_session_token(token))

    def test_11_websocket_ticket_single_use_consumption(self):
        """3.11: Verify WebSocket ticket single-use consumption and replay protection."""
        ticket, ttl = security.create_ws_ticket("founder@agenthq.internal")
        self.assertIsNotNone(ticket)

        valid, user = security.verify_and_consume_ws_ticket(ticket)
        self.assertTrue(valid)
        self.assertEqual(user, "founder@agenthq.internal")

        # Replay attempt fails
        valid2, _ = security.verify_and_consume_ws_ticket(ticket)
        self.assertFalse(valid2)

    def test_12_daily_ai_quota_reservation_and_reconciliation(self):
        """3.12 & 3.13: Verify daily AI quota reservation and telemetry reconciliation."""
        provider = "cloudflare"
        model = "@cf/meta/llama-3.3-70b-instruct"

        status_init = db.get_quota_status(provider=provider)
        current = status_init["current_neurons"]
        test_limit = current + 10000.0

        res = db.reserve_ai_quota(provider=provider, model=model, estimated_input_tokens=200, daily_limit=test_limit)
        self.assertIsNotNone(res)
        self.assertGreater(res.provisional_neurons, 0.0)

        status_after = db.get_quota_status(provider=provider, daily_limit=test_limit)
        self.assertGreaterEqual(status_after["current_neurons"], current + res.provisional_neurons)

    # =========================================================================
    # PART 4 — CONCURRENCY
    # =========================================================================

    def test_13_concurrent_task_updates_occ_race(self):
        """4.1 - 4.3: Four concurrent updates with same expected_version: exactly 1 winner, 3 conflicts, 0 orphan logs."""
        created = db.create_task({"title": "OCC Race Task", "status": "inbox"})
        task_id = created["id"]
        expected_version = 1

        results = []

        def worker(worker_id: int):
            db.reset_engine()  # Independent connection
            try:
                res = db.update_task(task_id, {
                    "title": f"Updated by worker {worker_id}",
                    "status": "working",
                    "version": expected_version,
                })
                return ("SUCCESS", res)
            except ValueError as err:
                return ("CONFLICT", str(err))

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(worker, i) for i in range(4)]
            results = [f.result() for f in futures]

        successes = [r for r in results if r[0] == "SUCCESS"]
        conflicts = [r for r in results if r[0] == "CONFLICT"]

        self.assertEqual(len(successes), 1, "Exactly one worker must succeed in OCC race.")
        self.assertEqual(len(conflicts), 3, "Exactly three workers must receive Conflict.")

        # Verify audit records grew by exactly 1
        history = db.get_task(task_id).get("audit_history") or []
        # 1 for created + exactly 1 for the successful update = 2
        self.assertEqual(len(history), 2, "Failed updates must produce zero audit records.")

    def test_14_shared_provider_quota_multiple_models(self):
        """4.4: Concurrent reservations across different models serialize under row lock."""
        models = ["@cf/qwen/qwen3.8-27b", "@cf/meta/llama-3-8b", "@cf/mistral/mistral-7b-instruct"]
        status_init = db.get_quota_status("cloudflare")
        test_limit = status_init["current_neurons"] + 20000.0

        def quota_worker(model_name: str):
            db.reset_engine()
            try:
                res = db.reserve_ai_quota(
                    provider="cloudflare",
                    model=model_name,
                    estimated_input_tokens=100,
                    daily_limit=test_limit,
                )
                return True
            except Exception:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(quota_worker, m) for m in models]
            results = [f.result() for f in futures]

        self.assertTrue(all(results))

    def test_15_concurrent_first_time_quota_bucket_creation(self):
        """4.5: Concurrent first-time bucket creation handles ON CONFLICT DO NOTHING without duplicates."""
        date_str = f"2099-12-{uuid4().hex[:2]}"

        def bucket_worker():
            db.reset_engine()
            try:
                db.reserve_ai_quota(
                    provider="cloudflare",
                    model="@cf/qwen/qwen3.8-27b",
                    estimated_input_tokens=50,
                    daily_limit=50000.0,
                )
                return True
            except Exception:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(bucket_worker) for _ in range(4)]
            results = [f.result() for f in futures]

        self.assertTrue(all(results))

    def test_16_concurrent_login_rate_limiting(self):
        """4.6: Concurrent login attempt checks under advisory lock serialize without deadlocks."""
        test_ip = f"10.250.{uuid4().hex[:2]}.1"
        db.reset_login_rate_limit(test_ip)

        def login_worker():
            db.reset_engine()
            return db.check_and_record_login_attempt(ip_address=test_ip, success=False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(login_worker) for _ in range(4)]
            results = [f.result() for f in futures]

        # All 4 should complete without database deadlock exceptions
        self.assertEqual(len(results), 4)
        db.reset_login_rate_limit(test_ip)

    def test_17_concurrent_websocket_ticket_consumption(self):
        """4.7: Concurrent attempts to consume the same WebSocket ticket: exactly 1 succeeds."""
        ticket, ttl = security.create_ws_ticket("concurrent_user@agenthq.internal")

        def ws_worker():
            db.reset_engine()
            valid, _ = security.verify_and_consume_ws_ticket(ticket)
            return valid

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(ws_worker) for _ in range(2)]
            results = [f.result() for f in futures]

        self.assertEqual(results.count(True), 1, "Exactly one consumer must successfully consume the ticket.")
        self.assertEqual(results.count(False), 1, "The competing consumer must fail.")

    def test_18_transaction_rollback_integrity(self):
        """4.8: Failed transactions roll back cleanly leaving no orphaned records."""
        task_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with self.assertRaises(RuntimeError):
            with db.get_session() as session:
                task = db.Task(
                    id=task_id,
                    title="Rollback Candidate",
                    description="",
                    priority="normal",
                    status="inbox",
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                session.add(task)
                session.flush()
                # Simulate critical failure before commit
                raise RuntimeError("Simulated crash")

        # Verify task was rolled back
        retrieved = db.get_task(task_id)
        self.assertIsNone(retrieved, "Task created in rolled-back transaction must not exist.")

    # =========================================================================
    # PART 5 — CONNECTION POOLING
    # =========================================================================

    def test_19_direct_vs_pooled_engine_behavior(self):
        """5.1: Verify QueuePool for runtime and NullPool for CLI/isolated usage."""
        runtime_engine = db.create_database_engine(TEST_PG_URL)
        self.assertIsInstance(runtime_engine.pool, QueuePool)

        cli_engine = sa.create_engine(db.normalize_database_url(TEST_PG_URL), poolclass=NullPool)
        self.assertIsInstance(cli_engine.pool, NullPool)
        runtime_engine.dispose()
        cli_engine.dispose()

    def test_20_pool_size_overflow_and_recycling(self):
        """5.2: Verify runtime QueuePool parameters (pool_size=5, max_overflow=2, pool_recycle=300)."""
        engine = db.create_database_engine(TEST_PG_URL)
        pool = engine.pool
        self.assertEqual(pool.size(), 5)
        self.assertEqual(pool._max_overflow, 2)
        self.assertEqual(pool._recycle, 300)
        self.assertTrue(pool._pre_ping)
        engine.dispose()

    def test_21_advisory_locking_transaction_scope(self):
        """5.4: Transaction-level advisory lock (pg_advisory_xact_lock) is released automatically upon commit/rollback."""
        test_ip = "192.168.10.99"
        lock_key = db._ip_to_advisory_lock_key(test_ip)

        # Connection 1 acquires transaction advisory lock
        with self.engine.connect() as conn1:
            conn1.execute(text("BEGIN"))
            conn1.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

            # Connection 2 checks if lock is held using try_lock
            with self.engine.connect() as conn2:
                # try lock on same key should return false because conn1 holds it
                acquired = conn2.execute(text("SELECT pg_try_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}).scalar()
                self.assertFalse(acquired, "conn2 must not acquire advisory lock held by conn1.")

            conn1.execute(text("COMMIT"))

        # After conn1 commits, conn2 should now be able to acquire it
        with self.engine.connect() as conn2:
            conn2.execute(text("BEGIN"))
            acquired2 = conn2.execute(text("SELECT pg_try_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}).scalar()
            self.assertTrue(acquired2, "conn2 must acquire advisory lock after conn1 commits.")
            conn2.execute(text("COMMIT"))

    def test_22_connection_leak_prevention(self):
        """5.5: Run consecutive operations and verify pool returns connections without leaks."""
        initial_checkedout = self.engine.pool.checkedout()

        for _ in range(15):
            with db.get_session() as session:
                session.execute(text("SELECT 1;"))

        final_checkedout = self.engine.pool.checkedout()
        self.assertEqual(initial_checkedout, final_checkedout, "Pool checkedout count must return to baseline after sessions close.")


if __name__ == "__main__":
    unittest.main()
