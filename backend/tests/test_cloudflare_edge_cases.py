"""Unit tests for Phase 2B.1 Cloudflare AI quota and usage edge cases.

Verifies:
1. usage = None
2. usage = {}
3. usage = []
4. usage = ""
5. prompt_tokens = 0 (preserved, not replaced by estimate)
6. completion_tokens = 0 (preserved, not replaced by estimate)
7. negative usage (rejected, fallback to estimate)
8. float usage (normalized safely)
9. nonnumeric usage (e.g. string "abc", list, bool)
10. missing completion_tokens (conservative fallback)
11. missing prompt_tokens (conservative fallback)
12. invalid provider response (missing choices, non-dict choices)
13. repeated reservation (independent reservations recorded accurately)
14. repeated reconciliation (additive/delta reconciliation)
15. quota exhaustion (rejection before network dispatch)
16. UTC date rollover (yesterday's quota does not block today)
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import db, providers


class CloudflareAIEdgeCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_file = Path(self.temp_dir.name) / "edge_case_test.db"
        self.db_path = str(self.db_file)
        os.environ["AGENTHQ_DB_PATH"] = self.db_path
        os.environ.pop("DATABASE_URL", None)
        db.reset_engine()
        db.init_db()

        self.provider = providers.CloudflareWorkersAIProvider(
            account_id="test_acc",
            api_token="test_tok",
            model="@cf/qwen/qwen3.8-27b",
        )
        self.messages = [{"role": "user", "content": "Ping"}]

    def tearDown(self):
        db.reset_engine()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def _mock_cf_response(self, usage: any, content: str = "Pong") -> providers.httpx.Response:
        data = {
            "choices": [{"message": {"role": "assistant", "content": content}}],
        }
        if usage is not None:
            data["usage"] = usage
        return providers.httpx.Response(
            status_code=200,
            json=data,
            request=providers.httpx.Request("POST", "https://api.cloudflare.com"),
        )

    async def test_01_usage_is_none(self):
        """1. usage is None: falls back to conservative token estimate."""
        resp = self._mock_cf_response(usage=None)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp
            result = await self.provider.chat_completion(self.messages)
            self.assertEqual(result.content, "Pong")
            self.assertGreater(result.prompt_tokens, 0)
            self.assertGreater(result.completion_tokens, 0)

    async def test_02_usage_is_empty_dict(self):
        """2. usage is {}: falls back to conservative token estimate."""
        resp = self._mock_cf_response(usage={})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp
            result = await self.provider.chat_completion(self.messages)
            self.assertGreater(result.prompt_tokens, 0)
            self.assertGreater(result.completion_tokens, 0)

    async def test_03_usage_is_list(self):
        """3. usage is []: non-dict handled gracefully without AttributeError."""
        resp = self._mock_cf_response(usage=[])
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp
            result = await self.provider.chat_completion(self.messages)
            self.assertGreater(result.prompt_tokens, 0)
            self.assertGreater(result.completion_tokens, 0)

    async def test_04_usage_is_string(self):
        """4. usage is "": non-dict handled gracefully without AttributeError."""
        resp = self._mock_cf_response(usage="")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp
            result = await self.provider.chat_completion(self.messages)
            self.assertGreater(result.prompt_tokens, 0)
            self.assertGreater(result.completion_tokens, 0)

    async def test_05_prompt_tokens_is_zero(self):
        """5. prompt_tokens = 0: legitimate 0 is preserved, not overridden by fallback."""
        resp = self._mock_cf_response(usage={"prompt_tokens": 0, "completion_tokens": 25})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp
            result = await self.provider.chat_completion(self.messages)
            self.assertEqual(result.prompt_tokens, 0)
            self.assertEqual(result.completion_tokens, 25)

    async def test_06_completion_tokens_is_zero(self):
        """6. completion_tokens = 0: legitimate 0 is preserved, not overridden by fallback."""
        resp = self._mock_cf_response(usage={"prompt_tokens": 50, "completion_tokens": 0})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp
            result = await self.provider.chat_completion(self.messages)
            self.assertEqual(result.prompt_tokens, 50)
            self.assertEqual(result.completion_tokens, 0)

    async def test_07_negative_usage(self):
        """7. negative token counts are rejected and replaced by conservative fallback."""
        resp = self._mock_cf_response(usage={"prompt_tokens": -10, "completion_tokens": -50})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp
            result = await self.provider.chat_completion(self.messages)
            self.assertGreater(result.prompt_tokens, 0)
            self.assertGreater(result.completion_tokens, 0)

    async def test_08_float_usage(self):
        """8. float usage values (e.g. 42.8) are normalized to integers."""
        resp = self._mock_cf_response(usage={"prompt_tokens": 42.9, "completion_tokens": 17.1})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp
            result = await self.provider.chat_completion(self.messages)
            self.assertEqual(result.prompt_tokens, 42)
            self.assertEqual(result.completion_tokens, 17)

    async def test_09_nonnumeric_usage(self):
        """9. nonnumeric usage values (strings, booleans, objects) fallback safely."""
        resp = self._mock_cf_response(usage={
            "prompt_tokens": "malformed_string",
            "completion_tokens": False,
            "total_tokens": [123],
        })
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp
            result = await self.provider.chat_completion(self.messages)
            self.assertGreater(result.prompt_tokens, 0)
            self.assertGreater(result.completion_tokens, 0)

    async def test_10_missing_completion_tokens(self):
        """10. missing completion_tokens: prompt_tokens parsed, completion falls back."""
        resp = self._mock_cf_response(usage={"prompt_tokens": 88})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp
            result = await self.provider.chat_completion(self.messages)
            self.assertEqual(result.prompt_tokens, 88)
            self.assertGreater(result.completion_tokens, 0)

    async def test_11_missing_prompt_tokens(self):
        """11. missing prompt_tokens: prompt falls back, completion_tokens parsed."""
        resp = self._mock_cf_response(usage={"completion_tokens": 99})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp
            result = await self.provider.chat_completion(self.messages)
            self.assertGreater(result.prompt_tokens, 0)
            self.assertEqual(result.completion_tokens, 99)

    async def test_12_invalid_provider_response(self):
        """12. invalid provider response raises AIProviderMalformedResponseError."""
        bad_resp = providers.httpx.Response(
            status_code=200,
            json={"error": "no choices"},
            request=providers.httpx.Request("POST", "https://api.cloudflare.com"),
        )
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = bad_resp
            with self.assertRaises(providers.AIProviderMalformedResponseError):
                await self.provider.chat_completion(self.messages)

    def test_13_repeated_reservation(self):
        """13. repeated reservation: sequential reservations accumulate accurately."""
        res1 = db.reserve_ai_quota("cloudflare", "@cf/qwen/qwen3.8-27b", 100, 100)
        res2 = db.reserve_ai_quota("cloudflare", "@cf/qwen/qwen3.8-27b", 200, 200)

        usage = db.get_daily_neuron_usage("cloudflare")
        expected = round(res1.provisional_neurons + res2.provisional_neurons, 6)
        self.assertAlmostEqual(usage, expected, places=4)

        status = db.get_quota_status("cloudflare")
        self.assertFalse(status["is_exhausted"])

    def test_14_repeated_reconciliation(self):
        """14. repeated reconciliation: reconciling multiple reservations updates accurately."""
        res1 = db.reserve_ai_quota("cloudflare", "@cf/qwen/qwen3.8-27b", 1000, 700)
        res2 = db.reserve_ai_quota("cloudflare", "@cf/qwen/qwen3.8-27b", 1000, 700)

        # Reconcile res1 with actual lower tokens
        db.reconcile_ai_quota(res1, 100, 50)
        # Reconcile res2 with actual lower tokens
        db.reconcile_ai_quota(res2, 200, 100)

        expected_1 = db.calculate_estimated_neurons(100, 50)
        expected_2 = db.calculate_estimated_neurons(200, 100)
        total_actual = round(expected_1 + expected_2, 6)

        usage = db.get_daily_neuron_usage("cloudflare")
        self.assertAlmostEqual(usage, total_actual, places=4)

    def test_15_quota_exhaustion_strict_rejection(self):
        """15. quota exhaustion: once limit is breached, all further reservations are rejected."""
        # Use controlled daily limit of 500.0 neurons
        test_limit = 500.0
        # 1,000 input, 1,000 output = ~331.8 neurons (fits under 500.0)
        res1 = db.reserve_ai_quota("cloudflare", "@cf/qwen/qwen3.8-27b", 1000, 1000, daily_limit=test_limit)
        self.assertIsNotNone(res1)

        status = db.get_quota_status("cloudflare", daily_limit=test_limit)
        self.assertGreater(status["current_neurons"], 300.0)
        self.assertLess(status["current_neurons"], test_limit)

        # Attempting another 1,000 in / 1,000 out would push total to ~663.6 > 500.0, strictly rejected!
        with self.assertRaises(db.QuotaExceededException) as ctx:
            db.reserve_ai_quota("cloudflare", "@cf/qwen/qwen3.8-27b", 1000, 1000, daily_limit=test_limit)

        self.assertIn("Daily AI quota reached", str(ctx.exception))
        self.assertEqual(ctx.exception.limit, test_limit)

    def test_16_utc_date_rollover(self):
        """16. UTC date rollover: usage recorded on a past UTC date does not block today's requests."""
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        now_ts = db.utc_now()

        # Seed yesterday's usage as exhausted (10,000 neurons)
        with db.get_session() as session:
            record = db.DailyAIUsage(
                id=f"usage-{yesterday}-test",
                usage_date=yesterday,
                provider="cloudflare",
                model="@cf/qwen/qwen3.8-27b",
                request_count=50,
                estimated_input_tokens=100000,
                estimated_output_tokens=50000,
                estimated_neurons=10000.0,
                created_at=now_ts,
                updated_at=now_ts,
            )
            session.add(record)

        # Yesterday's usage should be 10,000
        yesterday_usage = db.get_daily_neuron_usage("cloudflare", usage_date=yesterday)
        self.assertEqual(yesterday_usage, 10000.0)

        # Today's quota status should be fresh and 0
        status_today = db.get_quota_status("cloudflare")
        self.assertEqual(status_today["current_neurons"], 0.0)
        self.assertFalse(status_today["is_exhausted"])

        # Reserving for today must succeed despite yesterday being over quota
        res = db.reserve_ai_quota("cloudflare", "@cf/qwen/qwen3.8-27b", 500, 500)
        self.assertIsNotNone(res)
        self.assertGreater(db.get_daily_neuron_usage("cloudflare"), 0.0)


if __name__ == "__main__":
    unittest.main()
