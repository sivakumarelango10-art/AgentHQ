"""Multiprocessing login worker for AgentHQ concurrency testing.

Spawned as independent operating system processes to test database-level atomic login rate limiting.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure backend root is on sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import db, security


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentHQ Login Concurrency Worker")
    parser.add_argument("--db-path", type=str, default="", help="Path to SQLite database file")
    parser.add_argument("--db-url", type=str, default="", help="SQLAlchemy database URL")
    parser.add_argument("--ip", type=str, default="198.51.100.99", help="Client IP address")
    parser.add_argument("--username", type=str, default="founder", help="Username")
    parser.add_argument("--password", type=str, default="WrongPassword!", help="Password to test")
    parser.add_argument("--owner-hash", type=str, default="", help="Configured owner password hash")
    args = parser.parse_args()

    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url
        os.environ.pop("AGENTHQ_DB_PATH", None)
    elif args.db_path:
        os.environ["AGENTHQ_DB_PATH"] = args.db_path
        os.environ.pop("DATABASE_URL", None)

    if args.owner_hash:
        os.environ["AGENTHQ_OWNER_PASSWORD_HASH"] = args.owner_hash

    db.reset_engine()

    is_limited, is_authenticated, retry_after = db.atomic_login_attempt(
        ip_address=args.ip,
        username=args.username,
        credential_verifier=lambda: security.verify_founder_credentials(args.username, args.password),
    )

    if is_limited:
        sys.stdout.write(f"LIMITED:{retry_after}\n")
        sys.stdout.flush()
        return 429
    elif is_authenticated:
        sys.stdout.write("AUTHENTICATED\n")
        sys.stdout.flush()
        return 200
    else:
        sys.stdout.write("REJECTED\n")
        sys.stdout.flush()
        return 401


if __name__ == "__main__":
    sys.exit(main())

