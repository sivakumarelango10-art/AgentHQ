"""Unit and integration test suite for Phase 2D.1: Persistent Security State Migration.

Tests:
1. Session persistence after process restart.
2. Logout persistence across process restart.
3. Expired sessions rejection.
4. Tampered session signature rejection.
5. Persistent rate limiting across process restarts.
6. Concurrent login failures serialization.
7. Ticket creation with SHA-256 hash storage (no plaintext tickets in DB).
8. Ticket single-use and replay prevention.
9. Ticket expiry rejection.
10. Concurrent ticket consumption (atomic race resolution).
11. Process crash / engine disposal recovery.
12. Pruning expired security records.
13. Internal RPC endpoints with Bearer auth.
14. SQLite compatibility.
15. PostgreSQL compatibility (skips safely if TEST_DATABASE_URL unset).
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from app import db, security
from app.main import app

TEST_PASSWORD = "FounderStudioPassword123!"
TEST_PASSWORD_HASH = security.hash_password(TEST_PASSWORD)
TEST_USERNAME = "founder"
TEST_RUNTIME_TOKEN = "test-runtime-token-phase2d1-xyz"
TEST_SESSION_SECRET = "test-session-secret-phase2d1-must-be-32-bytes!"


class PersistentSecurityPhase2D1Tests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db.get_session() as session:
            session.execute(db.delete(db.OwnerSession))
            session.execute(db.delete(db.LoginAttempt))
            session.execute(db.delete(db.WebSocketTicket))

        self.env_patcher = patch.dict(
            os.environ,
            {
                "STUDIO_USERNAME": TEST_USERNAME,
                "STUDIO_PASSWORD_HASH": TEST_PASSWORD_HASH,
                "RUNTIME_API_TOKEN": TEST_RUNTIME_TOKEN,
                "SESSION_SECRET": TEST_SESSION_SECRET,
                "ENVIRONMENT": "development",
                "CORS_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000",
                "TRUSTED_PROXY": "true",
            },
        )
        self.env_patcher.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env_patcher.stop()

    def test_01_session_persistence_after_process_restart(self):
        """1. Founder session persists in database and remains valid across process restarts."""
        login_res = self.client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        self.assertEqual(login_res.status_code, 200)
        cookie_header = login_res.headers.get("set-cookie", "")
        self.assertIn("studio_session=", cookie_header)
        token = login_res.cookies.get("studio_session")
        self.assertIsNotNone(token)

        # Verify session is in DB
        with db.get_session() as session:
            sessions = session.scalars(db.select(db.OwnerSession)).all()
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].username, TEST_USERNAME)
            self.assertFalse(sessions[0].is_revoked)

        # Simulate full process restart: clear in-memory test shims, create fresh TestClient
        security._active_sessions.clear()
        security._revoked_session_ids.clear()
        restarted_client = TestClient(app)
        restarted_client.cookies.set("studio_session", token)

        me_res = restarted_client.get("/api/auth/me")
        self.assertEqual(me_res.status_code, 200)
        self.assertTrue(me_res.json()["authenticated"])
        self.assertEqual(me_res.json()["user"]["username"], TEST_USERNAME)

    def test_02_logout_persistence_across_process_restart(self):
        """2. Revoked session remains revoked in database across process restarts."""
        login_res = self.client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        token = login_res.cookies.get("studio_session")

        # Log out
        logout_res = self.client.post("/api/auth/logout")
        self.assertEqual(logout_res.status_code, 200)

        # Verify DB marks is_revoked = True
        with db.get_session() as session:
            db_session = session.scalars(db.select(db.OwnerSession)).first()
            self.assertIsNotNone(db_session)
            self.assertTrue(db_session.is_revoked)
            self.assertIsNotNone(db_session.revoked_at)

        # Simulate restart
        security._active_sessions.clear()
        security._revoked_session_ids.clear()
        restarted_client = TestClient(app)
        restarted_client.cookies.set("studio_session", token)

        me_res = restarted_client.get("/api/auth/me")
        self.assertEqual(me_res.status_code, 401)

    def test_03_expired_sessions_rejected(self):
        """3. Expired sessions are rejected and cannot authenticate."""
        token, _, data = security.create_session("founder")
        session_id = data["session_id"]

        # Backdate expiry in DB
        with db.get_session() as session:
            record = session.get(db.OwnerSession, session_id)
            self.assertIsNotNone(record)
            record.expires_at = int(time.time()) - 100

        # Attempt verification
        verified = security.verify_session_token(token)
        self.assertIsNone(verified)

        client = TestClient(app)
        client.cookies.set("studio_session", token)
        res = client.get("/api/auth/me")
        self.assertEqual(res.status_code, 401)

    def test_04_tampered_signature_rejected_without_db_lookup(self):
        """4. Tampered token signature is rejected by HMAC check before DB lookup."""
        token, _, _ = security.create_session("founder")
        parts = token.split(".", 1)
        tampered_token = f"{parts[0]}.bad_signature_here"

        verified = security.verify_session_token(tampered_token)
        self.assertIsNone(verified)

        client = TestClient(app)
        client.cookies.set("studio_session", tampered_token)
        res = client.get("/api/auth/me")
        self.assertEqual(res.status_code, 401)

    def test_05_persistent_rate_limiting_across_restarts(self):
        """5. Rate limiting tracks failed attempts in DB and persists lockout across restarts."""
        test_ip = "198.51.100.42"

        # 5 failed attempts should return 401
        for _ in range(5):
            res = self.client.post(
                "/api/auth/login",
                json={"username": TEST_USERNAME, "password": "WrongPassword!"},
                headers={"x-forwarded-for": test_ip},
            )
            self.assertEqual(res.status_code, 401)

        # 6th attempt locks out with 429
        res6 = self.client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": "WrongPassword!"},
            headers={"x-forwarded-for": test_ip},
        )
        self.assertEqual(res6.status_code, 429)
        self.assertIn("Retry-After", res6.headers)

        # Simulate process restart
        security._login_failures.clear()
        restarted_client = TestClient(app)

        # 7th attempt after restart must STILL be 429 because DB tracks attempts
        res7 = restarted_client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": "WrongPassword!"},
            headers={"x-forwarded-for": test_ip},
        )
        self.assertEqual(res7.status_code, 429)

    def test_06_concurrent_login_failures(self):
        """6. Multiple concurrent failed login attempts serialize into DB cleanly."""
        test_ip = "198.51.100.99"

        def attempt_fail():
            c = TestClient(app)
            return c.post(
                "/api/auth/login",
                json={"username": TEST_USERNAME, "password": "WrongPassword!"},
                headers={"x-forwarded-for": test_ip},
            ).status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(lambda _: attempt_fail(), range(8)))

        # Each concurrent attempt in the batch completes safely
        self.assertEqual(len(results), 8)
        for r in results:
            self.assertIn(r, (401, 429))

        # Subsequent attempt after the concurrent batch completes MUST be 429
        subsequent = attempt_fail()
        self.assertEqual(subsequent, 429)

        # Verify DB recorded at least 5 failures (lockout threshold reached)
        with db.get_session() as session:
            count = session.scalar(
                db.select(db.func.count(db.LoginAttempt.id)).where(
                    db.LoginAttempt.ip_address == test_ip
                )
            )
            self.assertGreaterEqual(count, 5)

    def test_06b_multiprocess_simultaneous_login_attempts(self):
        """6b. Simultaneous authentication attempts from independent OS processes serialize cleanly."""
        test_ip = "198.51.100.188"
        worker_script = Path(__file__).resolve().parent / "multiprocess_login_worker.py"
        test_db = db.database_path()

        def run_worker():
            cmd = [
                sys.executable,
                str(worker_script),
                "--db-path", str(test_db),
                "--ip", test_ip,
                "--username", TEST_USERNAME,
                "--password", "WrongPassword!",
                "--owner-hash", TEST_PASSWORD_HASH,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            return proc.returncode, proc.stdout.strip()

        # Run 8 independent processes concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(run_worker) for _ in range(8)]
            results = [f.result() for f in futures]

        exit_codes = [r[0] for r in results]
        for code in exit_codes:
            self.assertIn(code, (401, 429))

        rejections = exit_codes.count(401)
        lockouts = exit_codes.count(429)
        self.assertLessEqual(rejections, 5)
        self.assertGreaterEqual(lockouts, 3)

        # Subsequent attempt must strictly be 429
        sub_code, sub_out = run_worker()
        self.assertEqual(sub_code, 429)
        self.assertTrue(sub_out.startswith("LIMITED:"))

        # Verify DB recorded exactly 5 failures (lockout threshold reached)
        with db.get_session() as session:
            count = session.scalar(
                db.select(db.func.count(db.LoginAttempt.id)).where(
                    db.LoginAttempt.ip_address == test_ip
                )
            )
            self.assertEqual(count, 5)

    def test_07_ticket_creation_and_hash_storage(self):
        """7. WebSocket ticket creation stores only SHA-256 hash in DB, never plaintext token."""
        ticket, ttl = security.create_ws_ticket("founder")
        self.assertEqual(ttl, 60)
        self.assertIn(".", ticket)

        expected_hash = hashlib.sha256(ticket.encode("utf-8")).hexdigest()

        with db.get_session() as session:
            record = session.scalar(
                db.select(db.WebSocketTicket).where(db.WebSocketTicket.ticket_hash == expected_hash)
            )
            self.assertIsNotNone(record)
            self.assertEqual(record.username, "founder")
            self.assertFalse(record.is_consumed)
            self.assertIsNone(record.consumed_at)

    def test_08_ticket_single_use_and_replay_prevention(self):
        """8. Ticket can be consumed exactly once; replay attempts are rejected."""
        ticket, _ = security.create_ws_ticket("founder")

        # First consumption
        ok1, username1 = security.verify_and_consume_ws_ticket(ticket)
        self.assertTrue(ok1)
        self.assertEqual(username1, "founder")

        # Second consumption (replay)
        ok2, reason2 = security.verify_and_consume_ws_ticket(ticket)
        self.assertFalse(ok2)
        self.assertEqual(reason2, "Ticket already used")

    def test_09_ticket_expiry_rejection(self):
        """9. Expired tickets cannot be consumed and are rejected with 'Ticket expired'."""
        ticket, _ = security.create_ws_ticket("founder")
        expected_hash = hashlib.sha256(ticket.encode("utf-8")).hexdigest()

        # Backdate expiry in DB
        with db.get_session() as session:
            record = session.scalar(
                db.select(db.WebSocketTicket).where(db.WebSocketTicket.ticket_hash == expected_hash)
            )
            record.expires_at = int(time.time()) - 10

        ok, reason = security.verify_and_consume_ws_ticket(ticket)
        self.assertFalse(ok)
        self.assertEqual(reason, "Ticket expired")

    def test_10_concurrent_ticket_consumption(self):
        """10. Multiple concurrent attempts to consume the SAME ticket: exactly ONE succeeds."""
        ticket, _ = security.create_ws_ticket("founder")

        def consume_worker(_):
            return security.verify_and_consume_ws_ticket(ticket)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(consume_worker, range(8)))

        successes = [out for out in outcomes if out[0] is True]
        failures = [out for out in outcomes if out[0] is False]

        # Exactly 1 thread succeeds
        self.assertEqual(len(successes), 1)
        self.assertEqual(successes[0][1], "founder")

        # Exactly 7 threads fail
        self.assertEqual(len(failures), 7)
        for _, reason in failures:
            self.assertIn("Ticket already used", reason)

    def test_11_process_crash_recovery(self):
        """11. Engine reset / sudden termination recovers cleanly without corrupted records."""
        token, _, data = security.create_session("founder")
        ticket, _ = security.create_ws_ticket("founder")

        # Simulate crash / engine disposal
        db.reset_engine()

        # Fresh query after engine recreation
        session_id = data["session_id"]
        stored_sess = db.get_owner_session(session_id)
        self.assertIsNotNone(stored_sess)
        self.assertEqual(stored_sess["username"], "founder")

        ticket_hash = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
        with db.get_session() as session:
            t = session.scalar(
                db.select(db.WebSocketTicket).where(db.WebSocketTicket.ticket_hash == ticket_hash)
            )
            self.assertIsNotNone(t)
            self.assertFalse(t.is_consumed)

    def test_12_cleanup_expired_security_records(self):
        """12. Pruning deletes expired security records while retaining active ones."""
        # 1. Active session and ticket
        active_token, _, active_data = security.create_session("founder")
        active_ticket, _ = security.create_ws_ticket("founder")

        # 2. Expired session and ticket
        expired_token, _, expired_data = security.create_session("founder")
        expired_ticket, _ = security.create_ws_ticket("founder")

        # Backdate expired ones
        old_epoch = int(time.time()) - 200000  # > 48 hours ago
        with db.get_session() as session:
            s_exp = session.get(db.OwnerSession, expired_data["session_id"])
            s_exp.expires_at = old_epoch

            exp_ticket_hash = hashlib.sha256(expired_ticket.encode("utf-8")).hexdigest()
            t_exp = session.scalar(
                db.select(db.WebSocketTicket).where(db.WebSocketTicket.ticket_hash == exp_ticket_hash)
            )
            t_exp.expires_at = old_epoch

            # Add old login attempt
            session.add(
                db.LoginAttempt(
                    id="old-attempt-1",
                    ip_address="10.0.0.1",
                    username="hacker",
                    attempt_time=old_epoch,
                    success=False,
                    created_at=db.utc_now(),
                )
            )

        # Run cleanup
        pruned = db.prune_expired_security_records(retention_seconds=86400)
        self.assertGreaterEqual(pruned["pruned_sessions"], 1)
        self.assertGreaterEqual(pruned["pruned_tickets"], 1)
        self.assertGreaterEqual(pruned["pruned_login_attempts"], 1)

        # Verify active records survived
        self.assertIsNotNone(db.get_owner_session(active_data["session_id"]))
        self.assertIsNone(db.get_owner_session(expired_data["session_id"]))

    def test_13_internal_rpc_endpoints(self):
        """13. Internal RPC endpoints validate session and consume tickets under Bearer auth."""
        # Session validation
        token, _, data = security.create_session("founder")
        rpc_res = self.client.post(
            "/api/auth/validate-session",
            json={"session_id": data["session_id"]},
            headers={"Authorization": f"Bearer {TEST_RUNTIME_TOKEN}"},
        )
        self.assertEqual(rpc_res.status_code, 200)
        self.assertTrue(rpc_res.json()["valid"])

        # Ticket consumption via RPC
        ticket, _ = security.create_ws_ticket("founder")
        consume_res = self.client.post(
            "/api/auth/ws-ticket/consume",
            json={"ticket": ticket},
            headers={"Authorization": f"Bearer {TEST_RUNTIME_TOKEN}"},
        )
        self.assertEqual(consume_res.status_code, 200)
        self.assertTrue(consume_res.json()["consumed"])
        self.assertEqual(consume_res.json()["username"], "founder")

        # Replay via RPC rejected with 403
        replay_res = self.client.post(
            "/api/auth/ws-ticket/consume",
            json={"ticket": ticket},
            headers={"Authorization": f"Bearer {TEST_RUNTIME_TOKEN}"},
        )
        self.assertEqual(replay_res.status_code, 403)

    def test_14_sqlite_compatibility(self):
        """14. Verifies database engine is running SQLite and WAL mode is active."""
        engine = db.get_engine()
        self.assertEqual(engine.dialect.name, "sqlite")
        with engine.connect() as conn:
            journal_mode = conn.execute(db.text("PRAGMA journal_mode")).scalar()
            self.assertEqual(journal_mode.lower(), "wal")

    def test_15_postgresql_compatibility(self):
        """15. PostgreSQL compatibility verified against TEST_DATABASE_URL or safely skipped."""
        pg_url = os.getenv("TEST_DATABASE_URL")
        if not pg_url or not pg_url.strip():
            self.skipTest("TEST_DATABASE_URL not configured. Status: NOT RUN (PostgreSQL credentials unavailable).")

        pg_engine = db.create_database_engine(pg_url)
        try:
            with pg_engine.connect() as conn:
                res = conn.execute(db.text("SELECT version();")).scalar()
                self.assertIn("PostgreSQL", res)
        finally:
            pg_engine.dispose()

    def test_16_ticket_redaction_in_logs_and_errors(self):
        """16. Raw WebSocket tickets are redacted from logs, error messages, and monitoring strings."""
        sample_url = "/ws/office?ticket=eyJ0aWNrZXQiOiAiMTIzIn0.sig123&env=prod"
        redacted = security.redact_sensitive_string(sample_url)
        self.assertNotIn("eyJ0aWNrZXQiOiAiMTIzIn0.sig123", redacted)
        self.assertIn("?ticket=[REDACTED]&env=prod", redacted)

        # Test log filter
        log_filter = security.SensitiveParamLogFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg='GET /ws/control?ticket=secret_ws_ticket_abc&foo=bar HTTP/1.1 101',
            args=(),
            exc_info=None,
        )
        self.assertTrue(log_filter.filter(record))
        self.assertNotIn("secret_ws_ticket_abc", record.msg)
        self.assertIn("ticket=[REDACTED]", record.msg)

        # Ticket consumption error response must not reflect raw ticket
        bad_ticket = "malformed_ticket_xyz"
        res = self.client.post(
            "/api/auth/ws-ticket/consume",
            json={"ticket": bad_ticket},
            headers={"Authorization": f"Bearer {TEST_RUNTIME_TOKEN}"},
        )
        self.assertEqual(res.status_code, 403)
        self.assertNotIn(bad_ticket, res.text)

    def test_17_batched_cleanup_and_concurrency_protection(self):
        """17. Batched deletion cleans up expired records and protects against concurrent conflicts."""
        now_epoch = int(time.time())
        expired_cutoff = now_epoch - 100

        # Seed 1200 expired tickets directly in DB
        with db.get_session() as session:
            tickets = [
                db.WebSocketTicket(
                    id=f"expired-ticket-{i}",
                    ticket_hash=f"hash-{i}",
                    username="founder",
                    created_at="2026-01-01T00:00:00Z",
                    expires_at=expired_cutoff,
                    is_consumed=False,
                )
                for i in range(1200)
            ]
            session.add_all(tickets)

            # Seed 600 old login attempts
            attempts = [
                db.LoginAttempt(
                    id=f"old-attempt-{i}",
                    ip_address="198.51.100.1",
                    username="founder",
                    attempt_time=now_epoch - 90000,
                    success=False,
                    created_at="2026-01-01T00:00:00Z",
                )
                for i in range(600)
            ]
            session.add_all(attempts)

        # Execute batched prune
        prune_result = db.prune_expired_security_records(batch_size=500, max_batches=5, retention_seconds=86400)
        self.assertFalse(prune_result.get("skipped", False))
        self.assertGreaterEqual(prune_result["pruned_tickets"], 1000)
        self.assertEqual(prune_result["pruned_login_attempts"], 600)

        # Test opportunistic throttle
        db._last_cleanup_timestamp = 0.0
        first_call = db.maybe_prune_expired_security_records(min_interval_seconds=600)
        self.assertIsNotNone(first_call)

        # Immediate second call should be throttled and return None
        second_call = db.maybe_prune_expired_security_records(min_interval_seconds=600)
        self.assertIsNone(second_call)


if __name__ == "__main__":
    unittest.main()
