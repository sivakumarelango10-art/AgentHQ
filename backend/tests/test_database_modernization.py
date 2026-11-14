import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from starlette.testclient import TestClient

from app import db
from app.main import app


class DatabaseModernizationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "modernization-test.db"
        self.env_patch = patch.dict(os.environ, {"AGENTHQ_DB_PATH": str(self.db_path)})
        self.env_patch.start()
        db.reset_engine()

    def tearDown(self):
        db.reset_engine()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_01_fresh_sqlite_initialization(self):
        """1. Fresh SQLite initialization creates tables properly."""
        db.init_db()
        self.assertTrue(self.db_path.exists())
        with db.get_session() as session:
            agents_count = session.query(db.Agent).count()
            self.assertGreater(agents_count, 0)

    def test_02_seven_canonical_employees_exist(self):
        """2. Verify the exact 7 canonical founding employees exist with expected attributes."""
        db.init_db()
        agents = db.list_agents()
        agent_map = {agent["id"]: agent for agent in agents}

        expected_ids = {"ceo", "pm", "dev", "design", "research", "qa", "kiran"}
        self.assertEqual(set(agent_map.keys()), expected_ids)

        expected_names = {
            "ceo": "Atlas",
            "pm": "Mira",
            "dev": "Arin",
            "design": "Nia",
            "research": "Ira",
            "qa": "Dev",
            "kiran": "Kiran",
        }
        for aid, name in expected_names.items():
            self.assertEqual(agent_map[aid]["name"], name)
            self.assertEqual(agent_map[aid]["status"], "idle")
            self.assertEqual(agent_map[aid]["current_task"], "Available — awaiting assignment")

    def test_03_idempotent_seeding_and_customization_preservation(self):
        """3. Seeding must be idempotent and must NOT overwrite existing customizations."""
        db.init_db()
        # Customize an employee
        db.set_agent_activity("ceo", "meeting", "Strategy session with Founder")
        customized = db.get_agent("ceo")
        self.assertEqual(customized["status"], "meeting")
        self.assertEqual(customized["current_task"], "Strategy session with Founder")

        # Run init_db / seed again
        db.init_db()
        reloaded = db.get_agent("ceo")
        self.assertEqual(reloaded["status"], "meeting")
        self.assertEqual(reloaded["current_task"], "Strategy session with Founder")
        self.assertEqual(len(db.list_agents()), 7)

    def test_04_employee_creation_and_retrieval(self):
        """4. Test employee creation with payload validation."""
        db.init_db()
        created = db.create_agent({
            "name": "Zane",
            "role": "Security Specialist",
            "department": "Engineering",
            "room": "Development Room",
            "color": "#ff5500",
        })
        self.assertTrue(created["id"].startswith("agent-"))
        self.assertEqual(created["name"], "Zane")

        fetched = db.get_agent(created["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["name"], "Zane")
        self.assertEqual(len(db.list_agents()), 8)

    def test_05_task_creation_validation_and_cancellation(self):
        """5. Task creation, agent validation, and cancellation."""
        db.init_db()
        # Creation with valid agent
        task = db.create_task({
            "title": "Cloud migration blueprint",
            "description": "Design PostgreSQL + Cloudflare inference layer",
            "priority": "urgent",
            "assigned_agent_id": "dev",
        })
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["assigned_agent_name"], "Arin")

        # Invalid agent raises ValueError
        with self.assertRaises(ValueError):
            db.create_task({
                "title": "Invalid task",
                "assigned_agent_id": "non-existent-agent-id",
            })

        # Cancel task
        cancelled = db.cancel_task(task["id"], expected_version=1)
        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled["status"], "cancelled")

        # Non-queued cannot be cancelled again
        retry_cancel = db.cancel_task(task["id"], expected_version=2)
        self.assertEqual(retry_cancel["status"], "cancelled")

    def test_06_conversation_persistence(self):
        """6. Conversation creation and retrieval."""
        db.init_db()
        conv = db.create_conversation("pm", "Quarterly Milestone Planning")
        self.assertEqual(conv["agent_id"], "pm")
        self.assertEqual(conv["title"], "Quarterly Milestone Planning")

        fetched = db.get_conversation(conv["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["agent_name"], "Mira")

        all_convs = db.list_conversations()
        self.assertEqual(len(all_convs), 1)
        self.assertEqual(all_convs[0]["id"], conv["id"])

    def test_07_message_history_ordering(self):
        """7. Message history ordering across turns."""
        db.init_db()
        conv = db.create_conversation("dev", "API Implementation")
        cid = conv["id"]

        m1 = db.add_conversation_message(cid, "user", "How should we order messages?")
        m2 = db.add_conversation_message(cid, "assistant", "Using an explicit order index.")
        m3 = db.add_conversation_message(cid, "user", "Does it work in Postgres?")
        m4 = db.add_conversation_message(cid, "assistant", "Yes, completely independent of rowid.")

        messages = db.list_conversation_messages(cid, limit=10)
        self.assertEqual(len(messages), 4)
        self.assertEqual([m["id"] for m in messages], [m1["id"], m2["id"], m3["id"], m4["id"]])
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user", "assistant"])

    def test_08_multiple_messages_created_in_same_second(self):
        """8. Ensure messages created with the exact same second maintain chronological order."""
        db.init_db()
        conv = db.create_conversation("qa", "Stress Testing Ordering")
        cid = conv["id"]

        same_second_timestamp = "2026-11-14T10:00:00+00:00"
        with patch("app.db.utc_now", return_value=same_second_timestamp):
            m1 = db.add_conversation_message(cid, "user", "Message 1 (same second)")
            m2 = db.add_conversation_message(cid, "assistant", "Message 2 (same second)")
            m3 = db.add_conversation_message(cid, "user", "Message 3 (same second)")
            m4 = db.add_conversation_message(cid, "assistant", "Message 4 (same second)")
            m5 = db.add_conversation_message(cid, "user", "Message 5 (same second)")

        messages = db.list_conversation_messages(cid, limit=10)
        self.assertEqual(len(messages), 5)
        # Verify timestamps are identical
        for m in messages:
            self.assertEqual(m["created_at"], same_second_timestamp)
        # Verify ordering is strictly preserved
        self.assertEqual([m["id"] for m in messages], [m1["id"], m2["id"], m3["id"], m4["id"], m5["id"]])
        self.assertEqual(
            [m["content"] for m in messages],
            [
                "Message 1 (same second)",
                "Message 2 (same second)",
                "Message 3 (same second)",
                "Message 4 (same second)",
                "Message 5 (same second)",
            ],
        )

    def test_09_foreign_key_constraints(self):
        """9. Foreign key cascading and SET NULL behavior."""
        db.init_db()
        # Create a custom agent
        agent = db.create_agent({
            "name": "TempAgent",
            "role": "Temp Role",
            "department": "Engineering",
            "room": "Development Room",
        })
        aid = agent["id"]

        # Assign task
        task = db.create_task({
            "title": "Temp Task",
            "assigned_agent_id": aid,
        })
        tid = task["id"]

        # Create conversation and message
        conv = db.create_conversation(aid, "Temp Discussion")
        cid = conv["id"]
        msg = db.add_conversation_message(cid, "user", "Hello temp")

        # Delete agent
        with db.get_session() as session:
            a = session.get(db.Agent, aid)
            session.delete(a)

        # Task assigned_agent_id should be SET NULL
        tasks = db.list_tasks()
        target_task = next(t for t in tasks if t["id"] == tid)
        self.assertIsNone(target_task["assigned_agent_id"])

        # Conversation should be CASCADE deleted
        self.assertIsNone(db.get_conversation(cid))
        # Conversation messages should be CASCADE deleted
        messages = db.list_conversation_messages(cid)
        self.assertEqual(len(messages), 0)

    def test_10_runtime_session_persistence_and_validation(self):
        """10. Hermes3D runtime session mapping persistence and employee mismatch error."""
        db.init_db()
        session_id = "agent:arin:main"
        conv_id_1 = db.get_or_create_runtime_conversation("dev", session_id, "Dev Chat")
        self.assertTrue(conv_id_1)

        # Calling again with same session returns same conversation
        conv_id_2 = db.get_or_create_runtime_conversation("dev", session_id)
        self.assertEqual(conv_id_1, conv_id_2)

        # Calling with mismatched agent raises ValueError
        with self.assertRaises(ValueError):
            db.get_or_create_runtime_conversation("pm", session_id)

    def test_11_alembic_migration_consistency(self):
        """11. Verify Alembic migrations apply cleanly and track version."""
        # Use an isolated fresh database file for alembic
        alembic_db = Path(self.temp_dir.name) / "alembic-check.db"
        with patch.dict(os.environ, {"AGENTHQ_DB_PATH": str(alembic_db)}):
            db.reset_engine()
            backend_dir = Path(__file__).resolve().parents[1]
            ini_path = backend_dir / "alembic.ini"
            alembic_cfg = Config(str(ini_path))

            # Run upgrade head
            command.upgrade(alembic_cfg, "head")

            # Check that head revision was applied
            eng = db.create_database_engine(f"sqlite:///{alembic_db.as_posix()}")
            with eng.connect() as conn:
                version = conn.execute(db.text("SELECT version_num FROM alembic_version")).scalar()
                self.assertIn(version, ("0002_daily_ai_usage", "0003_persistent_security_state", "0004_unified_task_management", "0005_task_lifecycle_and_concurrency"))
                agents = conn.execute(db.text("SELECT COUNT(*) FROM agents")).scalar()
                self.assertEqual(agents, 7)
            eng.dispose()

    def test_12_existing_api_response_compatibility(self):
        """12. Verify FastAPI endpoints return exact field structures expected by frontend."""
        db.init_db()
        client = TestClient(app)

        # GET /api/agents
        res = client.get("/api/agents")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertIn("mode", data)
        self.assertEqual(data["total"], 7)
        self.assertEqual(data["mode"], "sqlite")

        first_agent = data["items"][0]
        for field in ["id", "name", "role", "department", "status", "room", "color", "current_task", "created_at", "updated_at"]:
            self.assertIn(field, first_agent)

        # POST /api/tasks
        res = client.post("/api/tasks", json={
            "title": "Test Task via API",
            "priority": "normal",
            "assigned_agent_id": "ceo",
        })
        self.assertEqual(res.status_code, 201)
        task_data = res.json()["item"]
        self.assertEqual(task_data["title"], "Test Task via API")
        self.assertEqual(task_data["status"], "queued")
        self.assertEqual(task_data["assigned_agent_name"], "Atlas")

        # GET /api/tasks
        res = client.get("/api/tasks")
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(res.json()["total"], 1)

        # PATCH /api/tasks/{task_id}/cancel
        task_id = task_data["id"]
        res = client.patch(f"/api/tasks/{task_id}/cancel", json={"version": 1})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["item"]["status"], "cancelled")

        # GET /health
        res = client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["database"], "connected")


if __name__ == "__main__":
    unittest.main()

