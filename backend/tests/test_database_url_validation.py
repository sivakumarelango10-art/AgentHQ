import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.db import validate_database_url, normalize_database_url, get_database_url


class TestDatabaseUrlValidation(unittest.TestCase):
    """Test suite for DATABASE_URL parsing, validation, and production constraints."""

    def test_01_valid_standard_postgresql_url(self):
        """Standard postgresql:// URL is parsed and normalized to postgresql+psycopg driver."""
        url = "postgresql://founder:secretpass@db.example.com:5432/agenthq"
        parsed = validate_database_url(url, environment="production")
        self.assertEqual(parsed.get_backend_name(), "postgresql")
        self.assertEqual(parsed.drivername, "postgresql+psycopg")
        self.assertEqual(parsed.host, "db.example.com")
        self.assertEqual(parsed.port, 5432)
        self.assertEqual(parsed.database, "agenthq")

    def test_02_valid_postgresql_psycopg_driver_url(self):
        """PostgreSQL URL already specifying postgresql+psycopg driver is preserved."""
        url = "postgresql+psycopg://founder:secretpass@db.example.com:5432/agenthq"
        parsed = validate_database_url(url, environment="production")
        self.assertEqual(parsed.get_backend_name(), "postgresql")
        self.assertEqual(parsed.drivername, "postgresql+psycopg")
        self.assertEqual(parsed.host, "db.example.com")

    def test_03_valid_neon_connection_string_with_query_params(self):
        """Valid Neon PostgreSQL URL with SSL and endpoint options is accepted."""
        url = (
            "postgresql://neondb_owner:npg_secrettoken@ep-cool-fog-123456.ap-southeast-1.aws.neon.tech/neondb"
            "?sslmode=require&endpoint=ep-cool-fog-123456"
        )
        parsed = validate_database_url(url, environment="production")
        self.assertEqual(parsed.get_backend_name(), "postgresql")
        self.assertEqual(parsed.host, "ep-cool-fog-123456.ap-southeast-1.aws.neon.tech")
        self.assertEqual(parsed.query.get("sslmode"), "require")

    def test_04_invalid_url_raises_error(self):
        """Completely unparseable string raises a clear descriptive ValueError."""
        with self.assertRaises(ValueError) as ctx:
            validate_database_url("not a url at all", environment="production")
        err = str(ctx.exception)
        self.assertIn("DATABASE_URL is malformed", err)
        # Ensure credentials/secrets are not mentioned
        self.assertNotIn("secret", err.lower())

    def test_05_empty_and_none_url_rejected_in_production(self):
        """Empty or None database URL raises descriptive ValueError in production."""
        with self.assertRaises(ValueError) as ctx:
            validate_database_url("", environment="production")
        self.assertIn("DATABASE_URL is not set or empty", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            validate_database_url(None, environment="production")
        self.assertIn("DATABASE_URL is not set or empty", str(ctx.exception))

    def test_06_sqlite_forbidden_in_production(self):
        """SQLite URL is rejected when environment is production."""
        with self.assertRaises(ValueError) as ctx:
            validate_database_url("sqlite:///data.db", environment="production")
        err = str(ctx.exception)
        self.assertIn("Production requires a PostgreSQL database", err)
        self.assertIn("sqlite", err)

    def test_07_sqlite_allowed_in_development(self):
        """SQLite URL is allowed in development environment."""
        parsed = validate_database_url("sqlite:///data.db", environment="development")
        self.assertEqual(parsed.get_backend_name(), "sqlite")

    def test_08_malformed_scheme_rejected_in_production(self):
        """Non-PostgreSQL dialect scheme is rejected in production."""
        with self.assertRaises(ValueError) as ctx:
            validate_database_url("mysql://user:pass@host/db", environment="production")
        err = str(ctx.exception)
        self.assertIn("Production requires a PostgreSQL database", err)
        self.assertIn("mysql", err)

    def test_09_whitespace_and_quotes_rejected_with_actionable_error(self):
        """URLs with leading/trailing whitespace or surrounding quotes are explicitly rejected."""
        quoted_cases = [
            '"postgresql://user:pass@host/db"',
            "'postgresql://user:pass@host/db'",
            ' "postgresql://user:pass@host/db" ',
            " postgresql://user:pass@host/db",
            "postgresql://user:pass@host/db ",
            "\tpostgresql://user:pass@host/db\n",
        ]
        for case in quoted_cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError) as ctx:
                    validate_database_url(case, environment="production")
                err = str(ctx.exception)
                self.assertIn("surrounding whitespace or quotes", err)
                # Verify credentials/passwords are NOT echoed back
                self.assertNotIn("pass", err)
                self.assertNotIn("user", err)

    def test_10_missing_host_rejected_in_production(self):
        """PostgreSQL URL without host is rejected in production."""
        with self.assertRaises(ValueError) as ctx:
            validate_database_url("postgresql://", environment="production")
        err = str(ctx.exception)
        self.assertIn("valid host", err)

    def test_11_entrypoint_supervisor_detects_failure_before_migrations(self):
        """Supervisor validate_production_environment catches malformed URL and exits before alembic."""
        from docker.entrypoint import UnifiedSupervisor

        supervisor = UnifiedSupervisor()
        old_env = os.environ.get("DATABASE_URL")
        try:
            # Set quoted URL in environment
            os.environ["DATABASE_URL"] = '"postgresql://user:pass@host/agenthq"'
            os.environ["ENVIRONMENT"] = "production"

            buf = io.StringIO()
            with redirect_stdout(buf):
                with self.assertRaises(SystemExit) as cm:
                    supervisor.validate_production_environment()
            self.assertEqual(cm.exception.code, 1)
            output = buf.getvalue()
            self.assertIn("FATAL: Database configuration error", output)
            self.assertIn("surrounding whitespace or quotes", output)
            # Ensure credentials are not printed
            self.assertNotIn("pass", output)
            self.assertNotIn("user", output)
        finally:
            if old_env is not None:
                os.environ["DATABASE_URL"] = old_env
            else:
                os.environ.pop("DATABASE_URL", None)


if __name__ == "__main__":
    unittest.main()
