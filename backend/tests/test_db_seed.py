import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db


class DatabaseSeedTests(unittest.TestCase):
    def test_fresh_database_contains_the_canonical_seven_employees(self):
        with tempfile.TemporaryDirectory() as directory:
            database_file = Path(directory) / "agenthq-test.db"
            with patch.dict(os.environ, {"AGENTHQ_DB_PATH": str(database_file)}):
                db.init_db()
                first = db.list_agents()

                self.assertEqual(len(first), 7)
                self.assertEqual(
                    {agent["name"] for agent in first},
                    {"Atlas", "Mira", "Arin", "Kiran", "Nia", "Ira", "Dev"},
                )

                # Initialization must be idempotent and must not duplicate employees.
                db.init_db()
                second = db.list_agents()
                self.assertEqual(len(second), 7)
                self.assertEqual(
                    {agent["id"] for agent in second},
                    {agent["id"] for agent in first},
                )


if __name__ == "__main__":
    unittest.main()
