from __future__ import annotations

import base64
import json
import os
import time
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

import app.db as db
import app.security as security
from app.main import app

TEST_PASSWORD = "FounderSecurePassword123!"
TEST_PASSWORD_HASH = security.hash_password(TEST_PASSWORD)
TEST_USERNAME = "founder"
TEST_RUNTIME_TOKEN = "test-runtime-token-phase2c-xyz123"
TEST_SESSION_SECRET = "test-session-secret-phase2c-must-be-32-bytes-long!"


class SecurityPhase2CTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        # Reset security in-memory stores between tests
        with security._session_lock:
            security._active_sessions.clear()
            security._revoked_session_ids.clear()
        with security._ticket_lock:
            security._active_ws_tickets.clear()
            security._consumed_ws_tickets.clear()
        with security._rate_limit_lock:
            security._login_failures.clear()

        self.env_patcher = patch.dict(
            os.environ,
            {
                "STUDIO_USERNAME": TEST_USERNAME,
                "STUDIO_PASSWORD_HASH": TEST_PASSWORD_HASH,
                "RUNTIME_API_TOKEN": TEST_RUNTIME_TOKEN,
                "SESSION_SECRET": TEST_SESSION_SECRET,
                "ENVIRONMENT": "development",
                "CORS_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000",
            },
        )
        self.env_patcher.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env_patcher.stop()

    def test_01_successful_founder_login(self):
        """1. Successful founder login with valid credentials sets secure cookie and returns CSRF."""
        res = self.client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("user", {}).get("username"), TEST_USERNAME)
        self.assertIn("csrf_token", data)
        self.assertTrue(len(data["csrf_token"]) > 16)

        # Verify studio_session cookie was set
        cookies = res.cookies
        self.assertIn(security.COOKIE_NAME, cookies)
        cookie_val = cookies[security.COOKIE_NAME]
        self.assertIn(".", cookie_val)

    def test_02_rejected_login_invalid_credentials(self):
        """2. Rejected login with invalid credentials returns 401."""
        res = self.client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": "WrongPassword999!"},
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid founder credentials", res.json().get("detail", ""))

        # Wrong username
        res2 = self.client.post(
            "/api/auth/login",
            json={"username": "impostor", "password": TEST_PASSWORD},
        )
        self.assertEqual(res2.status_code, 401)

    def test_03_login_rate_limiting_lockout(self):
        """3. Login rate limiting locks out after N failed attempts with 429 Retry-After."""
        client_ip = "127.0.0.1"

        # Trigger 5 failed attempts
        for i in range(5):
            res = self.client.post(
                "/api/auth/login",
                json={"username": TEST_USERNAME, "password": "bad_password"},
            )
            self.assertEqual(res.status_code, 401)

        # 6th attempt should be locked out with 429
        locked_res = self.client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        self.assertEqual(locked_res.status_code, 429)
        self.assertIn("Retry-After", locked_res.headers)
        self.assertIn("Too many failed login attempts", locked_res.json().get("detail", ""))

    def test_04_session_cookie_flags_in_production(self):
        """4. Session cookie has HttpOnly, SameSite=Lax, and Secure=True in production."""
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            prod_client = TestClient(app)
            res = prod_client.post(
                "/api/auth/login",
                json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            )
            self.assertEqual(res.status_code, 200)
            set_cookie_header = res.headers.get("set-cookie", "")
            self.assertIn(f"{security.COOKIE_NAME}=", set_cookie_header)
            self.assertIn("httponly", set_cookie_header.lower())
            self.assertIn("samesite=lax", set_cookie_header.lower())
            self.assertIn("secure", set_cookie_header.lower())

    def test_05_rejected_request_with_expired_session(self):
        """5. Expired session token is rejected with 401."""
        now = int(time.time())
        expired_data = {
            "session_id": "expired-session-123",
            "username": TEST_USERNAME,
            "role": "founder",
            "created_at": now - 100000,
            "expires_at": now - 100,  # Expired in past
            "csrf_token": "token123",
        }
        payload_json = json.dumps(expired_data, separators=(",", ":"))
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")
        sig = security._sign_payload(payload_b64, TEST_SESSION_SECRET)
        expired_token = f"{payload_b64}.{sig}"

        client = TestClient(app)
        client.cookies.set(security.COOKIE_NAME, expired_token)

        res = client.get("/api/auth/me")
        self.assertEqual(res.status_code, 401)

    def test_06_rejected_request_with_tampered_signature(self):
        """6. Tampered session signature is rejected with 401."""
        token, _, _ = security.create_session(TEST_USERNAME)
        payload_b64, sig = token.split(".", 1)

        # Alter the signature
        tampered_sig = sig[:-4] + "AAAA"
        tampered_token = f"{payload_b64}.{tampered_sig}"

        client = TestClient(app)
        client.cookies.set(security.COOKIE_NAME, tampered_token)

        res = client.get("/api/auth/me")
        self.assertEqual(res.status_code, 401)

    def test_07_successful_logout_invalidates_session(self):
        """7. Logout invalidates session server-side and clears cookie."""
        client = TestClient(app)
        login_res = client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        self.assertEqual(login_res.status_code, 200)

        # Verify session is currently active
        me_res = client.get("/api/auth/me")
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.json()["user"]["username"], TEST_USERNAME)

        # Logout
        logout_res = client.post("/api/auth/logout")
        self.assertEqual(logout_res.status_code, 200)

        # Verify session is now invalidated
        after_logout_res = client.get("/api/auth/me")
        self.assertEqual(after_logout_res.status_code, 401)

    def test_08_runtime_endpoints_require_runtime_api_token(self):
        """8. When auth is enforced, runtime endpoints reject unauthenticated requests with 401."""
        client = TestClient(app)

        # /api/agents
        res = client.get("/api/agents")
        self.assertEqual(res.status_code, 401)

        # /api/tasks
        res = client.get("/api/tasks")
        self.assertEqual(res.status_code, 401)

        # /state
        res = client.get("/state")
        self.assertEqual(res.status_code, 401)

        # /v1/chat/completions
        res = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(res.status_code, 401)

    def test_09_runtime_endpoints_accept_valid_bearer_token(self):
        """9. Runtime endpoints succeed with Authorization: Bearer <RUNTIME_API_TOKEN>."""
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {TEST_RUNTIME_TOKEN}"}

        res = client.get("/api/agents", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("items", data)

        res_state = client.get("/state", headers=headers)
        self.assertEqual(res_state.status_code, 200)

    def test_10_runtime_endpoints_reject_invalid_bearer_token(self):
        """10. Runtime endpoints reject wrong bearer token with 401."""
        client = TestClient(app)
        headers = {"Authorization": "Bearer wrong-token-xyz"}

        res = client.get("/api/agents", headers=headers)
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid runtime API token", res.json().get("detail", ""))

    def test_11_health_check_endpoints_remain_public(self):
        """11. Health checks and root remain publicly accessible without auth."""
        client = TestClient(app)

        # /health
        res1 = client.get("/health")
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json().get("ok"), True)

        # /api/health
        res2 = client.get("/api/health")
        self.assertEqual(res2.status_code, 200)
        self.assertIn("database", res2.json())

        # /
        res3 = client.get("/")
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(res3.json().get("status"), "ok")

    def test_12_cors_policy_headers(self):
        """12. CORS policy handles origin allowlist properly and attaches security headers."""
        client = TestClient(app)

        # Approved origin preflight
        res = client.options(
            "/api/agents",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("access-control-allow-origin"), "http://localhost:3000")
        self.assertEqual(res.headers.get("access-control-allow-credentials"), "true")

        # Standard GET response includes security headers and CORS headers
        get_res = client.get("/health", headers={"Origin": "http://localhost:3000"})
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.headers.get("access-control-allow-origin"), "http://localhost:3000")
        self.assertIn("Content-Security-Policy", get_res.headers)
        self.assertEqual(get_res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(get_res.headers.get("X-Frame-Options"), "DENY")

    def test_13_csrf_protection_on_mutating_requests(self):
        """13. CSRF token mismatch on cookie-authenticated mutating requests is rejected with 403."""
        client = TestClient(app)
        login_res = client.post(
            "/api/auth/login",
            json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        )
        self.assertEqual(login_res.status_code, 200)

        # Mutating request with invalid CSRF token
        bad_csrf_res = client.post(
            "/api/tasks",
            json={"title": "Unauthorized Task", "priority": "normal"},
            headers={"X-CSRF-Token": "invalid-csrf-token"},
        )
        self.assertEqual(bad_csrf_res.status_code, 403)
        self.assertIn("CSRF token validation failed", bad_csrf_res.json().get("detail", ""))

    def test_14_websocket_ticket_generation_and_consumption(self):
        """14. WebSocket ticket generation and single-use validation."""
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {TEST_RUNTIME_TOKEN}"}

        # Request ticket
        ticket_res = client.post("/api/auth/ws-ticket", headers=headers)
        self.assertEqual(ticket_res.status_code, 200)
        ticket_data = ticket_res.json()
        self.assertTrue(ticket_data.get("ok"))
        ticket = ticket_data["ticket"]
        self.assertEqual(ticket_data["expires_in"], 60)

        # First consumption should succeed
        valid, username = security.verify_and_consume_ws_ticket(ticket)
        self.assertTrue(valid)
        self.assertEqual(username, "founder")

        # Second consumption (replay) should fail
        valid_again, reason = security.verify_and_consume_ws_ticket(ticket)
        self.assertFalse(valid_again)
        self.assertIn("already used", reason)

    def test_15_websocket_rejects_expired_and_tampered_tickets(self):
        """15. WebSocket ticket verification rejects expired and tampered tickets."""
        # Tampered ticket
        token, _ = security.create_ws_ticket("founder")
        payload_b64, sig = token.split(".", 1)
        tampered_ticket = f"{payload_b64}.tampered_{sig}"
        valid, reason = security.verify_and_consume_ws_ticket(tampered_ticket)
        self.assertFalse(valid)
        self.assertEqual(reason, "Invalid signature")

        # Expired ticket
        now = int(time.time())
        expired_data = {
            "ticket_id": "expired-ws-ticket",
            "username": "founder",
            "expires_at": now - 10,
        }
        payload_json = json.dumps(expired_data, separators=(",", ":"))
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")
        sig = security._sign_payload(payload_b64, TEST_SESSION_SECRET)
        expired_ticket = f"{payload_b64}.{sig}"
        valid_exp, reason_exp = security.verify_and_consume_ws_ticket(expired_ticket)
        self.assertFalse(valid_exp)
        self.assertEqual(reason_exp, "Ticket expired")


if __name__ == "__main__":
    unittest.main()
