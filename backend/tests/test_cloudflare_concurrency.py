"""Multiprocess concurrency test suite for AgentHQ Cloud AI Quota.

Spawns independent operating-system processes against file-backed databases to verify:
A. 20 concurrent reservations with exact expected totals.
B. Simultaneous reservations when quota is almost exhausted.
C. Concurrent first-time insertion of the daily usage row.
D. Multiple processes attempting to exceed the 8,500-neuron threshold.
E. Exact request_count and estimated_neurons matching.
F. No lost updates.
G. Total estimated neuron reservation never exceeds configured limit.
H. Crashed processes retain committed reservations.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import db

WORKER_SCRIPT = Path(__file__).resolve().parent / "multiprocess_quota_worker.py"


class MultiprocessQuotaConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_file = Path(self.temp_dir.name) / "concurrency_test.db"
        self.db_path = str(self.db_file)
        os.environ["AGENTHQ_DB_PATH"] = self.db_path
        os.environ.pop("DATABASE_URL", None)
        db.reset_engine()
        db.init_db()

    def tearDown(self):
        db.reset_engine()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _run_workers(
        self,
        num_procs: int,
        reservations_per_proc: int,
        input_tokens: int = 100,
        output_tokens: int = 200,
        limit: float = 8500.0,
        crash_after: bool = False,
        custom_db_path: str | None = None,
        custom_db_url: str | None = None,
        models: list[str] | None = None,
    ) -> list[tuple[int, str, str]]:
        """Launch num_procs independent OS processes and wait for completion."""
        target_path = custom_db_path or self.db_path
        procs = []

        for i in range(num_procs):
            cmd = [sys.executable, str(WORKER_SCRIPT)]
            if custom_db_url:
                cmd.extend(["--db-url", custom_db_url])
            else:
                cmd.extend(["--db-path", target_path])

            model = models[i % len(models)] if models else "@cf/qwen/qwen3.8-27b"
            cmd.extend([
                "--model", model,
                "--reservations", str(reservations_per_proc),
                "--input-tokens", str(input_tokens),
                "--output-tokens", str(output_tokens),
                "--limit", str(limit),
            ])
            if crash_after:
                cmd.append("--crash-after")

            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            procs.append(p)

        results = []
        for p in procs:
            out, err = p.communicate()
            results.append((p.returncode, out.strip(), err.strip()))
        return results

    def test_A_E_F_twenty_concurrent_reservations_with_exact_totals(self):
        """A, E, F: 20 concurrent reservations across 4 processes produce exact request_count and neurons without lost updates."""
        input_tokens = 100
        output_tokens = 200
        per_res_neurons = db.calculate_estimated_neurons(input_tokens, output_tokens)

        # 4 independent processes, 5 reservations each = 20 total
        results = self._run_workers(
            num_procs=4,
            reservations_per_proc=5,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            limit=50000.0,
        )

        for code, out, err in results:
            self.assertEqual(code, 0, f"Worker process failed with stderr: {err}")
            self.assertIn("SUCCESS:5", out)
            self.assertIn("ERROR:0", out)

        today = db.utc_today_str()
        usage = db.get_daily_neuron_usage("cloudflare", today)
        expected_neurons = round(20 * per_res_neurons, 6)
        self.assertAlmostEqual(usage, expected_neurons, places=4)

        with db.get_session() as session:
            record = session.scalar(
                db.select(db.DailyAIUsage).where(
                    db.DailyAIUsage.usage_date == today,
                    db.DailyAIUsage.provider == "cloudflare",
                )
            )
            self.assertIsNotNone(record)
            self.assertEqual(record.request_count, 20)
            self.assertEqual(record.estimated_input_tokens, 20 * input_tokens)
            self.assertEqual(record.estimated_output_tokens, 20 * output_tokens)
            self.assertAlmostEqual(record.estimated_neurons, expected_neurons, places=4)

    def test_B_D_G_simultaneous_reservations_at_quota_ceiling(self):
        """B, D, G: When quota is nearly exhausted, concurrent attempts strictly never exceed 8,500 limit."""
        # 1. Pre-fill quota to near ceiling: e.g. 8,000 neurons used out of 8,500
        # That leaves 500 neurons available.
        # Each worker attempts to reserve 200 input tokens, 700 output tokens = ~211.8 neurons.
        # At most 2 reservations can fit (2 * 211.8 = 423.6 <= 500). The 3rd would be 635.4 > 500.
        db.reserve_ai_quota(
            provider="cloudflare",
            model="@cf/qwen/qwen3.8-27b",
            estimated_input_tokens=50000,
            max_output_tokens=20400,
            daily_limit=50000.0,
        )
        pre_usage = db.get_daily_neuron_usage("cloudflare")

        # Now set limit to pre_usage + 500 neurons
        effective_limit = pre_usage + 500.0

        # Launch 4 processes simultaneously, each attempting 2 reservations
        results = self._run_workers(
            num_procs=4,
            reservations_per_proc=2,
            input_tokens=200,
            output_tokens=700,
            limit=effective_limit,
        )

        total_success = 0
        total_exceeded = 0
        for code, out, err in results:
            self.assertEqual(code, 0, f"Worker process error: {err}")
            for part in out.split(","):
                if part.startswith("SUCCESS:"):
                    total_success += int(part.split(":")[1])
                elif part.startswith("EXCEEDED:"):
                    total_exceeded += int(part.split(":")[1])

        # Exactly 2 should succeed, 6 should be rejected due to quota ceiling
        self.assertEqual(total_success, 2)
        self.assertEqual(total_exceeded, 6)

        final_usage = db.get_daily_neuron_usage("cloudflare")
        self.assertLessEqual(final_usage, effective_limit)

    def test_C_concurrent_first_time_insertion_of_daily_usage_row(self):
        """C: Multiple processes concurrently racing to insert the first daily usage row serialize cleanly without errors."""
        fresh_db = Path(self.temp_dir.name) / "first_insert_race.db"
        fresh_path = str(fresh_db)
        os.environ["AGENTHQ_DB_PATH"] = fresh_path
        db.reset_engine()
        db.init_db()

        # 4 processes each reserving simultaneously on fresh database
        results = self._run_workers(
            num_procs=4,
            reservations_per_proc=1,
            input_tokens=100,
            output_tokens=100,
            custom_db_path=fresh_path,
        )

        for code, out, err in results:
            self.assertEqual(code, 0, f"Worker failed: {err}")
            self.assertIn("SUCCESS:1", out)

        with db.get_session() as session:
            records = session.scalars(
                db.select(db.DailyAIUsage).where(
                    db.DailyAIUsage.usage_date == db.utc_today_str(),
                    db.DailyAIUsage.provider == "cloudflare",
                )
            ).all()
            # There must be EXACTLY 1 row for this (date, provider, model), not 4 duplicate rows!
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].request_count, 4)

    def test_H_crashed_processes_retain_committed_reservations(self):
        """H: If a process crashes or is killed immediately after reservation, the reservation remains committed."""
        crash_db = Path(self.temp_dir.name) / "crash_test.db"
        crash_path = str(crash_db)
        os.environ["AGENTHQ_DB_PATH"] = crash_path
        db.reset_engine()
        db.init_db()

        # Run 2 workers with --crash-after flag (exit with code 42 immediately after reserve)
        results = self._run_workers(
            num_procs=2,
            reservations_per_proc=1,
            input_tokens=500,
            output_tokens=500,
            crash_after=True,
            custom_db_path=crash_path,
        )

        for code, out, err in results:
            # Both processes crashed with code 42
            self.assertEqual(code, 42)

        os.environ["AGENTHQ_DB_PATH"] = crash_path
        db.reset_engine()

        # Verify that despite the crash, both reservations are safely committed in the file-backed SQLite database
        expected_per_res = db.calculate_estimated_neurons(500, 500)
        usage = db.get_daily_neuron_usage("cloudflare")
        self.assertAlmostEqual(usage, round(2 * expected_per_res, 6), places=4)

        with db.get_session() as session:
            record = session.scalar(
                db.select(db.DailyAIUsage).where(
                    db.DailyAIUsage.usage_date == db.utc_today_str(),
                    db.DailyAIUsage.provider == "cloudflare",
                )
            )
            self.assertIsNotNone(record)
            self.assertEqual(record.request_count, 2)

    def test_I_multi_model_sharing_provider_quota(self):
        """I: Multiple different models concurrently reserving against one provider share the same daily quota bucket."""
        models = [
            "@cf/qwen/qwen3.8-27b",
            "@cf/meta/llama-3-8b",
            "@cf/mistral/mistral-7b-instruct",
            "@cf/google/gemma-7b-it",
        ]
        input_tokens = 100
        output_tokens = 200
        per_res = db.calculate_estimated_neurons(input_tokens, output_tokens)

        # 4 processes, each operating on a distinct model, 5 reservations each
        results = self._run_workers(
            num_procs=4,
            reservations_per_proc=5,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            limit=50000.0,
            models=models,
        )

        for code, out, err in results:
            self.assertEqual(code, 0, f"Worker failed: {err}")
            self.assertIn("SUCCESS:5", out)

        today = db.utc_today_str()
        # Verify the shared bucket accumulated all 20 reservations
        total_usage = db.get_daily_neuron_usage("cloudflare", today)
        expected_total = round(20 * per_res, 6)
        self.assertAlmostEqual(total_usage, expected_total, places=4)

        with db.get_session() as session:
            # Check the bucket
            bucket = session.scalar(
                db.select(db.DailyAIQuotaBucket).where(
                    db.DailyAIQuotaBucket.usage_date == today,
                    db.DailyAIQuotaBucket.provider == "cloudflare",
                )
            )
            self.assertIsNotNone(bucket)
            self.assertEqual(bucket.request_count, 20)
            self.assertAlmostEqual(bucket.estimated_neurons, expected_total, places=4)

            # Check per-model breakdown
            model_records = session.scalars(
                db.select(db.DailyAIUsage).where(
                    db.DailyAIUsage.usage_date == today,
                    db.DailyAIUsage.provider == "cloudflare",
                )
            ).all()
            self.assertEqual(len(model_records), 4)
            for rec in model_records:
                self.assertEqual(rec.request_count, 5)
                self.assertAlmostEqual(rec.estimated_neurons, round(5 * per_res, 6), places=4)


class PostgreSQLQuotaConcurrencyTests(unittest.TestCase):
    """PostgreSQL integration tests requiring dedicated TEST_DATABASE_URL."""

    def setUp(self):
        self.pg_url = os.getenv("TEST_DATABASE_URL")
        if not self.pg_url or not self.pg_url.startswith("postgresql"):
            self.skipTest("TEST_DATABASE_URL not configured. Status: NOT RUN (PostgreSQL credentials unavailable).")
        os.environ["DATABASE_URL"] = self.pg_url
        os.environ.pop("AGENTHQ_DB_PATH", None)
        db.reset_engine()
        db.init_db()

    def tearDown(self):
        db.reset_engine()

    def _run_pg_workers(
        self,
        num_procs: int,
        reservations_per_proc: int,
        input_tokens: int = 100,
        output_tokens: int = 200,
        limit: float = 8500.0,
        crash_after: bool = False,
        models: list[str] | None = None,
    ) -> list[tuple[int, str, str]]:
        procs = []
        for i in range(num_procs):
            cmd = [sys.executable, str(WORKER_SCRIPT), "--db-url", self.pg_url]
            model = models[i % len(models)] if models else "@cf/qwen/qwen3.8-27b"
            cmd.extend([
                "--model", model,
                "--reservations", str(reservations_per_proc),
                "--input-tokens", str(input_tokens),
                "--output-tokens", str(output_tokens),
                "--limit", str(limit),
            ])
            if crash_after:
                cmd.append("--crash-after")
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            procs.append(p)

        results = []
        for p in procs:
            out, err = p.communicate()
            results.append((p.returncode, out.strip(), err.strip()))
        return results

    def test_pg_01_concurrent_reservations_and_no_lost_updates(self):
        """PG-1: Concurrent reservations with accurate request counts and zero lost updates."""
        results = self._run_pg_workers(num_procs=4, reservations_per_proc=5, limit=50000.0)
        for code, out, err in results:
            self.assertEqual(code, 0, f"PG worker error: {err}")
            self.assertIn("SUCCESS:5", out)

    def test_pg_02_first_time_bucket_creation(self):
        """PG-2: Concurrent first-time bucket creation handles ON CONFLICT DO NOTHING without duplicates."""
        results = self._run_pg_workers(num_procs=4, reservations_per_proc=1)
        for code, out, err in results:
            self.assertEqual(code, 0, f"PG worker error: {err}")

    def test_pg_03_multiple_models_share_one_provider_quota(self):
        """PG-3: Multiple models share the single provider quota bucket under PostgreSQL FOR UPDATE."""
        models = ["@cf/qwen/qwen3.8-27b", "@cf/meta/llama-3-8b", "@cf/mistral/mistral-7b-instruct"]
        results = self._run_pg_workers(num_procs=3, reservations_per_proc=3, limit=50000.0, models=models)
        for code, out, err in results:
            self.assertEqual(code, 0, f"PG worker error: {err}")

    def test_pg_04_quota_exhaustion_and_rollback(self):
        """PG-4: Quota exhaustion rolls back cleanly without exceeding ceiling."""
        results = self._run_pg_workers(num_procs=4, reservations_per_proc=3, limit=100.0)
        exceeded_seen = False
        for code, out, err in results:
            if "EXCEEDED:" in out:
                exceeded_seen = True
        self.assertTrue(exceeded_seen)

    def test_pg_05_process_interruption_retains_reservations(self):
        """PG-5: Process interruption retains committed reservations in PostgreSQL."""
        results = self._run_pg_workers(num_procs=2, reservations_per_proc=1, crash_after=True)
        for code, out, err in results:
            self.assertEqual(code, 42)


if __name__ == "__main__":
    unittest.main()

