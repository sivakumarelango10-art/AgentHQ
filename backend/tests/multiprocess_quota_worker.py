"""Multiprocessing quota worker for AgentHQ concurrency testing.

Spawned as independent operating system processes to test database-level concurrency.
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

from app import db


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentHQ Quota Concurrency Worker")
    parser.add_argument("--db-path", type=str, default="", help="Path to SQLite database file")
    parser.add_argument("--db-url", type=str, default="", help="SQLAlchemy database URL")
    parser.add_argument("--model", type=str, default="@cf/qwen/qwen3.8-27b", help="AI Model identifier")
    parser.add_argument("--reservations", type=int, default=1, help="Number of reservations to execute")
    parser.add_argument("--input-tokens", type=int, default=100, help="Input tokens per reservation")
    parser.add_argument("--output-tokens", type=int, default=200, help="Output tokens per reservation")
    parser.add_argument("--limit", type=float, default=db.CLOUDFLARE_DEFAULT_DAILY_LIMIT, help="Daily neuron limit")
    parser.add_argument("--crash-after", action="store_true", help="Immediately exit via os._exit after first reservation")
    args = parser.parse_args()

    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url
        os.environ.pop("AGENTHQ_DB_PATH", None)
    elif args.db_path:
        os.environ["AGENTHQ_DB_PATH"] = args.db_path
        os.environ.pop("DATABASE_URL", None)

    db.reset_engine()

    success_count = 0
    quota_exceeded_count = 0
    error_count = 0

    for i in range(args.reservations):
        try:
            db.reserve_ai_quota(
                provider="cloudflare",
                model=args.model,
                estimated_input_tokens=args.input_tokens,
                max_output_tokens=args.output_tokens,
                daily_limit=args.limit,
            )
            success_count += 1
            if args.crash_after:
                # Force process crash post-reservation without python cleanup/reconciliation
                os._exit(42)
        except db.QuotaExceededException:
            quota_exceeded_count += 1
        except Exception as e:
            error_count += 1
            print(f"Worker unexpected error: {e}", file=sys.stderr)

    print(f"SUCCESS:{success_count},EXCEEDED:{quota_exceeded_count},ERROR:{error_count}")
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

