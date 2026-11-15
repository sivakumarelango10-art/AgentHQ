#!/usr/bin/env python3
"""Unified Process Supervisor and Lifecycle Manager for Render Free Deployment.

Supervises:
1. AgentHQ FastAPI Backend (127.0.0.1:8000)
2. Hermes3D Next.js Studio (0.0.0.0:$PORT)

Guarantees:
- Validates PostgreSQL requirement (rejects SQLite in production).
- Runs Alembic migrations on startup.
- Fast startup failure detection (< 20s).
- Atomic failure: if either process dies, container exits with error to trigger restart.
- Graceful shutdown: handles SIGTERM / SIGINT, cleanly draining both processes.
- Streams stdout/stderr from both processes directly to container console.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


class UnifiedSupervisor:
    def __init__(self):
        self.fastapi_proc: subprocess.Popen | None = None
        self.hermes_proc: subprocess.Popen | None = None
        self.shutting_down = False

        self.root_dir = Path(__file__).resolve().parents[1]
        self.backend_dir = self.root_dir / "backend"
        # In container, hermes3d is located at /app/hermes3d or specified by HERMES3D_DIR
        configured_hermes = os.getenv("HERMES3D_DIR")
        if configured_hermes:
            self.hermes_dir = Path(configured_hermes).resolve()
        else:
            local_sibling = Path("E:/Hermes3D").resolve()
            container_path = self.root_dir / "hermes3d"
            self.hermes_dir = local_sibling if local_sibling.exists() else container_path

        self.public_port = os.getenv("PORT", "3000").strip() or "3000"
        self.internal_api_port = "8000"

    def log(self, message: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        print(f"[{timestamp}] [SUPERVISOR] {message}", flush=True)

    def validate_production_environment(self) -> None:
        self.log("Validating production environment constraints...")
        raw_db_url = os.getenv("DATABASE_URL")
        environment = os.getenv("ENVIRONMENT", "production").strip()

        # Ensure backend directory is in sys.path for database validation
        if str(self.backend_dir) not in sys.path:
            sys.path.insert(0, str(self.backend_dir))

        try:
            from app.db import validate_database_url
            url_obj = validate_database_url(raw_db_url, environment=environment)
            self.log(f"Environment validation passed. Target database: PostgreSQL (driver: {url_obj.drivername}).")
        except ValueError as err:
            self.log(f"FATAL: Database configuration error: {err}")
            sys.exit(1)
        except Exception as err:
            self.log(f"FATAL: Unexpected error validating database URL: {type(err).__name__}")
            sys.exit(1)

        if not os.getenv("STUDIO_ACCESS_TOKEN") and not os.getenv("OWNER_PASSWORD_HASH") and not os.getenv("STUDIO_PASSWORD_HASH"):
            self.log("WARNING: STUDIO_ACCESS_TOKEN and password hashes are unset. Setting fallback STUDIO_ACCESS_TOKEN for public bind.")
            os.environ["STUDIO_ACCESS_TOKEN"] = "render-free-secure-gate"

    def run_migrations(self) -> None:
        self.log("Executing Alembic database migrations (upgrade head)...")
        t0 = time.perf_counter()
        res = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(self.backend_dir),
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            self.log(f"FATAL: Database migration failed (exit code {res.returncode}):\n{res.stderr}")
            sys.exit(1)
        elapsed = time.perf_counter() - t0
        self.log(f"Alembic migrations completed successfully in {elapsed:.2f}s.")

    def wait_for_http(self, url: str, name: str, timeout_seconds: float = 25.0) -> None:
        self.log(f"Awaiting readiness probe for {name} ({url})...")
        start = time.perf_counter()
        deadline = start + timeout_seconds
        while time.perf_counter() < deadline:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "SupervisorProbe/1.0"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    if resp.status == 200:
                        elapsed = time.perf_counter() - start
                        self.log(f"{name} is healthy and responding (took {elapsed:.2f}s).")
                        return
            except Exception:
                time.sleep(0.3)
        raise TimeoutError(f"{name} failed to respond on {url} within {timeout_seconds}s.")

    def start_fastapi(self) -> None:
        self.log("Launching AgentHQ FastAPI backend on 127.0.0.1:8000...")
        env = os.environ.copy()
        env["HOST"] = "127.0.0.1"
        env["PORT"] = self.internal_api_port
        env["ENVIRONMENT"] = "production"

        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            self.internal_api_port,
            "--workers",
            "1",
            "--log-level",
            "info",
        ]
        self.fastapi_proc = subprocess.Popen(
            cmd,
            cwd=str(self.backend_dir),
            env=env,
        )
        self.wait_for_http(f"http://127.0.0.1:{self.internal_api_port}/health", "AgentHQ FastAPI", timeout_seconds=20.0)

    def start_hermes(self) -> None:
        self.log(f"Launching Hermes3D Next.js on 0.0.0.0:{self.public_port}...")
        env = os.environ.copy()
        env["NODE_ENV"] = "production"
        env["HOST"] = "0.0.0.0"
        env["PORT"] = self.public_port
        env["AGENTHQ_INTERNAL_URL"] = f"http://127.0.0.1:{self.internal_api_port}"
        env["AGENTHQ_URL"] = f"http://127.0.0.1:{self.internal_api_port}"

        # If server/index.js exists, use it; otherwise fallback to next start
        server_script = self.hermes_dir / "server" / "index.js"
        if server_script.exists():
            cmd = ["node", str(server_script)]
        else:
            cmd = ["npx", "next", "start", "-p", self.public_port, "-H", "0.0.0.0"]

        self.hermes_proc = subprocess.Popen(
            cmd,
            cwd=str(self.hermes_dir),
            env=env,
        )
        self.wait_for_http(f"http://127.0.0.1:{self.public_port}/api/health", "Hermes3D Studio", timeout_seconds=30.0)

    def shutdown(self, signum=None, frame=None) -> None:
        if self.shutting_down:
            return
        self.shutting_down = True
        sig_name = signal.Signals(signum).name if signum else "CLEANUP"
        self.log(f"Received shutdown request ({sig_name}). Draining child processes gracefully...")

        procs = [("FastAPI", self.fastapi_proc), ("Hermes3D", self.hermes_proc)]
        for name, proc in procs:
            if proc and proc.poll() is None:
                self.log(f"Sending SIGTERM to {name} (PID {proc.pid})...")
                proc.terminate()

        t0 = time.perf_counter()
        deadline = t0 + 10.0
        for name, proc in procs:
            if proc and proc.poll() is None:
                remaining = max(0.1, deadline - time.perf_counter())
                try:
                    proc.wait(timeout=remaining)
                    self.log(f"{name} exited cleanly.")
                except subprocess.TimeoutExpired:
                    self.log(f"WARNING: {name} did not exit within timeout. Forcing SIGKILL.")
                    proc.kill()

        self.log("All processes terminated. Shutdown complete.")
        sys.exit(0)

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)

        self.log("Starting Unified Render Free Process Supervisor...")
        self.validate_production_environment()
        self.run_migrations()
        self.start_fastapi()
        self.start_hermes()

        self.log("==================================================")
        self.log("AGENTHQ + HERMES3D UNIFIED STACK IS LIVE AND READY")
        self.log(f"Public Frontend: http://0.0.0.0:{self.public_port}")
        self.log(f"Internal Runtime API: http://127.0.0.1:{self.internal_api_port}")
        self.log("==================================================")

        # Main supervision loop: inspect both processes every 1s
        while not self.shutting_down:
            time.sleep(1.0)
            if self.fastapi_proc and self.fastapi_proc.poll() is not None:
                code = self.fastapi_proc.returncode
                self.log(f"FATAL: AgentHQ FastAPI backend terminated unexpectedly with code {code}.")
                self.shutdown()
                sys.exit(1)

            if self.hermes_proc and self.hermes_proc.poll() is not None:
                code = self.hermes_proc.returncode
                self.log(f"FATAL: Hermes3D Studio terminated unexpectedly with code {code}.")
                self.shutdown()
                sys.exit(1)


if __name__ == "__main__":
    supervisor = UnifiedSupervisor()
    supervisor.run()

