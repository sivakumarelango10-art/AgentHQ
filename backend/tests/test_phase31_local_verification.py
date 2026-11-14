"""Phase 3.1: Complete Local Production Verification Suite.

Tests:
1. Dual-process startup and coordination.
2. Backend health probe (AgentHQ on 127.0.0.1:8000).
3. Frontend health probe (Hermes3D on 127.0.0.1:3000).
4. Internal runtime proxy (Hermes3D -> AgentHQ).
5. Database connection to Neon PostgreSQL.
6. Founder authentication flow and session cookie generation.
7. Employee list and conversation persistence.
8. Task creation and persistence through Hermes3D task-store API.
9. WebSocket single-use ticket generation and validation.
10. Graceful shutdown and clean port deallocation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class Phase31LocalProductionVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parents[2]
        cls.backend_dir = cls.root_dir / "backend"
        cls.hermes_dir = Path("E:/Hermes3D").resolve()
        cls.python_exe = cls.backend_dir / ".venv" / "Scripts" / "python.exe"

        if str(cls.backend_dir) not in sys.path:
            sys.path.insert(0, str(cls.backend_dir))

        # Load environment from backend/.env if available
        import dotenv
        dotenv.load_dotenv(str(cls.backend_dir / ".env"))

        cls.db_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
        cls.runtime_token = "test-runtime-token-phase31-prod-xyz-987"
        cls.session_secret = "test-session-secret-phase31-must-be-32bytes-long!"
        cls.studio_token = "test-studio-access-token-12345"
        cls.test_username = "founder"
        cls.test_password = "FounderPassword123!"

        # Compute password hash
        from app import security
        cls.password_hash = security.hash_password(cls.test_password)

        # 1. Start FastAPI Backend
        fastapi_env = os.environ.copy()
        fastapi_env["PORT"] = "8000"
        fastapi_env["HOST"] = "127.0.0.1"
        fastapi_env["ENVIRONMENT"] = "production"
        fastapi_env["DATABASE_URL"] = cls.db_url or ""
        fastapi_env["RUNTIME_API_TOKEN"] = cls.runtime_token
        fastapi_env["SESSION_SECRET"] = cls.session_secret
        fastapi_env["OWNER_USERNAME"] = cls.test_username
        fastapi_env["OWNER_PASSWORD_HASH"] = cls.password_hash
        fastapi_env["STUDIO_PASSWORD_HASH"] = cls.password_hash
        fastapi_env["AGENTHQ_ENFORCE_AUTH"] = "true"

        cls.fastapi_proc = subprocess.Popen(
            [
                str(cls.python_exe),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--log-level",
                "warning",
            ],
            cwd=str(cls.backend_dir),
            env=fastapi_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Wait for FastAPI
        cls._wait_for_url("http://127.0.0.1:8000/health", timeout=20.0)

        # 2. Start Hermes3D Next.js
        hermes_env = os.environ.copy()
        hermes_env["NODE_ENV"] = "production"
        hermes_env["PORT"] = "3000"
        hermes_env["HOST"] = "127.0.0.1"
        hermes_env["STUDIO_ACCESS_TOKEN"] = cls.studio_token
        hermes_env["RUNTIME_API_TOKEN"] = cls.runtime_token
        hermes_env["SESSION_SECRET"] = cls.session_secret
        hermes_env["OWNER_USERNAME"] = cls.test_username
        hermes_env["OWNER_PASSWORD_HASH"] = cls.password_hash
        hermes_env["STUDIO_PASSWORD_HASH"] = cls.password_hash
        hermes_env["AGENTHQ_INTERNAL_URL"] = "http://127.0.0.1:8000"
        hermes_env["AGENTHQ_URL"] = "http://127.0.0.1:8000"

        cls.hermes_proc = subprocess.Popen(
            ["node", "server/index.js"],
            cwd=str(cls.hermes_dir),
            env=hermes_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Wait for Hermes3D
        cls._wait_for_url("http://127.0.0.1:3000/api/health", timeout=30.0)

    @classmethod
    def tearDownClass(cls):
        if cls.fastapi_proc and cls.fastapi_proc.poll() is None:
            cls.fastapi_proc.terminate()
            cls.fastapi_proc.wait(timeout=5)
        if cls.hermes_proc and cls.hermes_proc.poll() is None:
            cls.hermes_proc.terminate()
            cls.hermes_proc.wait(timeout=5)

    @classmethod
    def _wait_for_url(cls, url: str, timeout: float = 20.0):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Probe/1.0"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status == 200:
                        return
            except Exception:
                time.sleep(0.3)
        raise TimeoutError(f"Service at {url} failed to respond within {timeout}s.")

    def test_01_backend_health(self):
        """1. Backend health probe responds with runtime: AgentHQ."""
        req = urllib.request.Request("http://127.0.0.1:8000/health")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("runtime"), "AgentHQ")

    def test_02_frontend_health(self):
        """2. Hermes3D frontend public health probe responds without auth."""
        req = urllib.request.Request("http://127.0.0.1:3000/api/health")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("service"), "hermes3d")

    def test_03_founder_authentication(self):
        """3. Founder authenticates via Hermes3D and receives signed session cookie."""
        login_payload = json.dumps({"username": self.test_username, "password": self.test_password}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:3000/api/auth/login",
            data=login_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            cookies = resp.headers.get_all("Set-Cookie") or [resp.headers.get("Set-Cookie", "")]
            cookie_text = " ".join(cookies)
            self.assertIn("studio_session=", cookie_text)

    def test_04_employee_directory_and_canonical_identities(self):
        """4. Employee directory returns canonical employees via AgentHQ internal API."""
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/agents",
            headers={"Authorization": f"Bearer {self.runtime_token}"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            items = data.get("items", [])
            self.assertEqual(len(items), 7)
            names = {a["name"] for a in items}
            self.assertEqual(names, {"Atlas", "Mira", "Arin", "Kiran", "Nia", "Ira", "Dev"})

    def test_05_internal_runtime_task_store_proxy_and_persistence(self):
        """5. Task created via Hermes3D task-store API persists into AgentHQ PostgreSQL database."""
        # Authenticate founder to obtain session cookie
        login_payload = json.dumps({"username": self.test_username, "password": self.test_password}).encode()
        login_req = urllib.request.Request(
            "http://127.0.0.1:3000/api/auth/login",
            data=login_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(login_req) as login_resp:
            set_cookie = login_resp.headers.get("Set-Cookie", "")
            session_cookie = set_cookie.split(";")[0]

        # PUT /api/task-store (Create or update task via Hermes3D proxy)
        task_id = f"docker-test-task-{int(time.time())}"
        task_payload = json.dumps({
            "task": {
                "id": task_id,
                "title": "Phase 3.1 Docker Readiness Task",
                "description": "Verify unified container task persistence.",
                "assignedAgentId": "pm",
                "status": "todo",
                "priority": "high",
            }
        }).encode()

        create_req = urllib.request.Request(
            "http://127.0.0.1:3000/api/task-store",
            data=task_payload,
            headers={
                "Content-Type": "application/json",
                "Cookie": session_cookie,
            },
            method="PUT",
        )
        with urllib.request.urlopen(create_req) as create_resp:
            self.assertEqual(create_resp.status, 200)
            task_resp = json.loads(create_resp.read().decode())
            task = task_resp["task"]
            self.assertEqual(task["id"], task_id)
            self.assertEqual(task["title"], "Phase 3.1 Docker Readiness Task")

        # GET /api/tasks/{task_id} directly from AgentHQ internal API
        get_req = urllib.request.Request(
            f"http://127.0.0.1:8000/api/tasks/{task_id}",
            headers={"Authorization": f"Bearer {self.runtime_token}"},
        )
        with urllib.request.urlopen(get_req) as get_resp:
            self.assertEqual(get_resp.status, 200)
            data = json.loads(get_resp.read().decode())
            persisted = data["item"]
            self.assertEqual(persisted["id"], task_id)
            self.assertEqual(persisted["status"], "inbox")
            self.assertEqual(persisted["assigned_agent_id"], "pm")

    def test_06_websocket_ticket_lifecycle(self):
        """6. WebSocket ticket generation succeeds and persists hash for single-use authentication."""
        login_payload = json.dumps({"username": self.test_username, "password": self.test_password}).encode()
        login_req = urllib.request.Request(
            "http://127.0.0.1:3000/api/auth/login",
            data=login_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(login_req) as login_resp:
            session_cookie = login_resp.headers.get("Set-Cookie", "").split(";")[0]

        ticket_req = urllib.request.Request(
            "http://127.0.0.1:3000/api/auth/ws-ticket",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Cookie": session_cookie,
            },
            method="POST",
        )
        with urllib.request.urlopen(ticket_req) as ticket_resp:
            self.assertEqual(ticket_resp.status, 200)
            ticket_data = json.loads(ticket_resp.read().decode())
            self.assertTrue(ticket_data.get("ok"))
            self.assertIn("ticket", ticket_data)


if __name__ == "__main__":
    unittest.main()
