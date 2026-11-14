import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from starlette.testclient import TestClient

from app import db, main
from app.db import calculate_estimated_neurons
from app.providers import (
    AICompletionResult,
    AIProviderAuthError,
    AIProviderModelError,
    AIProviderRateLimitError,
    AIProviderTimeoutError,
    CloudflareWorkersAIProvider,
    OllamaProvider,
    get_ai_provider,
)


class MockHTTPResponse:
    def __init__(self, status_code: int, json_data: dict, headers: dict | None = None):
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://api.cloudflare.com/test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("HTTP Error", request=request, response=response)


class CloudflareWorkersAITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "cf-test.db"
        self.env_patch = patch.dict(
            os.environ,
            {
                "AGENTHQ_DB_PATH": str(self.db_path),
                "AI_PROVIDER": "cloudflare",
                "CLOUDFLARE_ACCOUNT_ID": "mock-account-12345",
                "CLOUDFLARE_API_TOKEN": "mock-token-xyz987",
                "CLOUDFLARE_MODEL": "@cf/qwen/qwen3.8-27b",
                "CLOUDFLARE_DAILY_NEURON_LIMIT": "8500",
            },
        )
        self.env_patch.start()
        db.reset_engine()
        db.init_db()

    def tearDown(self):
        db.reset_engine()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    async def test_01_local_ollama_provider_remains_functional(self):
        """1. Local Ollama provider remains functional when selected."""
        provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="qwen3:4b")
        self.assertEqual(provider.name, "ollama")
        self.assertEqual(provider.model, "qwen3:4b")

        mock_payload = {
            "message": {"content": "Ollama response"},
            "prompt_eval_count": 15,
            "eval_count": 8,
        }
        mock_resp = MockHTTPResponse(200, mock_payload)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            result = await provider.chat_completion([{"role": "user", "content": "Hello"}])
            self.assertEqual(result.content, "Ollama response")
            self.assertEqual(result.prompt_tokens, 15)
            self.assertEqual(result.completion_tokens, 8)

    async def test_02_cloudflare_provider_configuration(self):
        """2. Cloudflare provider configuration and endpoint URL."""
        provider = CloudflareWorkersAIProvider()
        self.assertEqual(provider.name, "cloudflare")
        self.assertEqual(provider.model, "@cf/qwen/qwen3.8-27b")
        self.assertIn("mock-account-12345", provider.endpoint_url)
        self.assertIn("/ai/v1/chat/completions", provider.endpoint_url)

        # Missing credentials raises AIProviderAuthError
        unconfigured = CloudflareWorkersAIProvider(account_id="", api_token="")
        with self.assertRaises(AIProviderAuthError):
            await unconfigured.chat_completion([{"role": "user", "content": "Hi"}])

    async def test_03_successful_inference(self):
        """3. Successful inference with OpenAI-compatible payload & usage parsing."""
        provider = CloudflareWorkersAIProvider()
        mock_resp = MockHTTPResponse(
            200,
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "Cloudflare Workers AI ready."}}
                ],
                "usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100},
            },
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            result = await provider.chat_completion([{"role": "user", "content": "Test prompt"}])
            self.assertEqual(result.content, "Cloudflare Workers AI ready.")
            self.assertEqual(result.prompt_tokens, 80)
            self.assertEqual(result.completion_tokens, 20)
            self.assertEqual(result.total_tokens, 100)

    async def test_04_invalid_credentials(self):
        """4. Invalid credentials triggers AIProviderAuthError and translates to HTTP 502."""
        provider = CloudflareWorkersAIProvider()
        mock_resp = MockHTTPResponse(401, {"success": False, "errors": [{"message": "Unauthorized"}]})

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            with self.assertRaises(AIProviderAuthError):
                await provider.chat_completion([{"role": "user", "content": "Hi"}])

        client = TestClient(main.app)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            res = client.post("/api/agents/ceo/chat", json={"message": "Hello Atlas"})
            self.assertEqual(res.status_code, 502)
            self.assertIn("authentication failed", res.json()["detail"].lower())

    async def test_05_invalid_model(self):
        """5. Invalid model identifier raises AIProviderModelError."""
        provider = CloudflareWorkersAIProvider()
        mock_resp = MockHTTPResponse(404, {"success": False, "errors": [{"message": "Model not found"}]})

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            with self.assertRaises(AIProviderModelError):
                await provider.chat_completion([{"role": "user", "content": "Hi"}])

    async def test_06_provider_timeout_keeps_quota_reservation(self):
        """6. Provider timeout raises AIProviderTimeoutError and preserves consumed quota."""
        client = TestClient(main.app)

        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Read timed out")):
            res = client.post("/api/agents/ceo/chat", json={"message": "Long prompt"})
            self.assertEqual(res.status_code, 504)

        # Quota must NOT be released on timeout (uncertain state)
        usage = db.get_daily_neuron_usage(provider="cloudflare")
        self.assertGreater(usage, 0.0)

    def test_07_quota_exhaustion_returns_http_429(self):
        """7. Reaching the daily quota raises QuotaExceededException and returns HTTP 429."""
        # Manually exhaust today's quota
        today = db.utc_today_str()
        now_ts = db.utc_now()
        with db.get_session() as session:
            record = db.DailyAIUsage(
                id=f"exhausted-{today}",
                usage_date=today,
                provider="cloudflare",
                model="@cf/qwen/qwen3.8-27b",
                request_count=50,
                estimated_input_tokens=10000,
                estimated_output_tokens=25000,
                estimated_neurons=8500.5,
                created_at=now_ts,
                updated_at=now_ts,
            )
            session.add(record)

        client = TestClient(main.app)
        res = client.post("/api/agents/ceo/chat", json={"message": "Are we over quota?"})
        self.assertEqual(res.status_code, 429)
        self.assertIn("daily free allocation reached", res.json()["detail"].lower())
        self.assertIn("Retry-After", res.headers)

    def test_08_8500_neuron_safety_threshold(self):
        """8. The 8,500-neuron safety threshold rejects requests that would breach ceiling."""
        status = db.get_quota_status(provider="cloudflare")
        self.assertEqual(status["daily_limit_neurons"], 8500.0)

        # Set usage to 8,450 neurons
        today = db.utc_today_str()
        with db.get_session() as session:
            record = db.DailyAIUsage(
                id=f"near-limit-{today}",
                usage_date=today,
                provider="cloudflare",
                model="@cf/qwen/qwen3.8-27b",
                request_count=40,
                estimated_input_tokens=8000,
                estimated_output_tokens=20000,
                estimated_neurons=8450.0,
                created_at=db.utc_now(),
                updated_at=db.utc_now(),
            )
            session.add(record)

        # A request for 700 max output tokens requires ~203 neurons (8450 + 203 > 8500) -> must reject
        with self.assertRaises(db.QuotaExceededException):
            db.reserve_ai_quota(
                provider="cloudflare",
                model="@cf/qwen/qwen3.8-27b",
                estimated_input_tokens=200,
                max_output_tokens=700,
                daily_limit=8500.0,
            )

    def test_09_utc_quota_reset(self):
        """9. Yesterday's usage does not block today's requests (UTC daily reset)."""
        yesterday_str = "2026-11-13"
        with db.get_session() as session:
            record = db.DailyAIUsage(
                id=f"yesterday-usage",
                usage_date=yesterday_str,
                provider="cloudflare",
                model="@cf/qwen/qwen3.8-27b",
                request_count=100,
                estimated_input_tokens=20000,
                estimated_output_tokens=50000,
                estimated_neurons=10000.0,
                created_at=db.utc_now(),
                updated_at=db.utc_now(),
            )
            session.add(record)

        # Today's usage is isolated and still 0.0
        today_usage = db.get_daily_neuron_usage(provider="cloudflare", usage_date=db.utc_today_str())
        self.assertEqual(today_usage, 0.0)
        status = db.get_quota_status(provider="cloudflare")
        self.assertFalse(status["is_exhausted"])
        self.assertEqual(status["remaining_neurons"], 8500.0)

    def test_10_concurrent_quota_reservations(self):
        """10. Concurrent quota reservations are atomically recorded without race conditions."""
        num_threads = 5
        reservations_per_thread = 4

        def worker():
            for _ in range(reservations_per_thread):
                db.reserve_ai_quota(
                    provider="cloudflare",
                    model="@cf/qwen/qwen3.8-27b",
                    estimated_input_tokens=100,
                    max_output_tokens=200,
                    daily_limit=50000.0,
                )

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker) for _ in range(num_threads)]
            for f in futures:
                f.result()

        total_requests = num_threads * reservations_per_thread
        with db.get_session() as session:
            record = session.scalar(
                db.select(db.DailyAIUsage).where(
                    db.DailyAIUsage.usage_date == db.utc_today_str(),
                    db.DailyAIUsage.provider == "cloudflare",
                )
            )
            self.assertIsNotNone(record)
            self.assertEqual(record.request_count, total_requests)

    def test_11_input_output_neuron_calculation(self):
        """11. Input and output neuron calculation matches published rates."""
        # 1,000 input tokens at 40909/M = 40.909
        # 500 output tokens at 290909/M = 145.4545
        # Total = 186.3635 neurons
        neurons = calculate_estimated_neurons(input_tokens=1000, output_tokens=500)
        self.assertAlmostEqual(neurons, 186.3635, places=4)

        # Zero tokens
        self.assertEqual(calculate_estimated_neurons(0, 0), 0.0)

    async def test_12_response_sanitization(self):
        """12. Response sanitization removes thinking blocks from Cloudflare output."""
        raw_output = "<think>Analyzing user prompt and reviewing company state...</think>Hello Founder, I am ready to assist."
        mock_resp = MockHTTPResponse(
            200,
            {
                "choices": [{"message": {"role": "assistant", "content": raw_output}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 30},
            },
        )

        client = TestClient(main.app)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            res = client.post("/api/agents/ceo/chat", json={"message": "Status report"})
            self.assertEqual(res.status_code, 200)
            content = res.json()["assistant_message"]["content"]
            self.assertEqual(content, "Hello Founder, I am ready to assist.")
            self.assertNotIn("<think>", content)

    async def test_13_bounded_retry_behavior(self):
        """13. Sanitization rejects internal monologue and executes exactly one bounded retry."""
        draft_response = MockHTTPResponse(
            200,
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "Okay, the user wants me to review code. First, I need to check."}}
                ],
                "usage": {"prompt_tokens": 40, "completion_tokens": 20},
            },
        )
        clean_response = MockHTTPResponse(
            200,
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "I have reviewed the code specifications."}}
                ],
                "usage": {"prompt_tokens": 60, "completion_tokens": 25},
            },
        )

        client = TestClient(main.app)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [draft_response, clean_response]
            res = client.post("/api/agents/dev/chat", json={"message": "Review code"})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["assistant_message"]["content"], "I have reviewed the code specifications.")
            self.assertEqual(mock_post.call_count, 2)

    async def test_14_conversation_context_preservation(self):
        """14. Conversation context across multiple turns is passed to Cloudflare."""
        client = TestClient(main.app)
        mock_resp1 = MockHTTPResponse(
            200,
            {
                "choices": [{"message": {"role": "assistant", "content": "Step 1 initiated."}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10},
            },
        )
        mock_resp2 = MockHTTPResponse(
            200,
            {
                "choices": [{"message": {"role": "assistant", "content": "Step 2 completed."}}],
                "usage": {"prompt_tokens": 80, "completion_tokens": 10},
            },
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [mock_resp1, mock_resp2]
            r1 = client.post("/api/agents/pm/chat", json={"message": "Begin plan"})
            conv_id = r1.json()["conversation_id"]

            r2 = client.post("/api/agents/pm/chat", json={"message": "Continue plan", "conversation_id": conv_id})
            self.assertEqual(r2.status_code, 200)

            # Check that call 2 received conversation history
            call2_messages = mock_post.call_args_list[1].kwargs["json"]["messages"]
            user_texts = [m["content"] for m in call2_messages if m["role"] == "user"]
            self.assertIn("Begin plan", user_texts)
            self.assertIn("Continue plan", user_texts)

    async def test_15_no_automatic_paid_fallback(self):
        """15. Cloudflare failure stops cleanly without calling paid third-party fallback."""
        client = TestClient(main.app)
        mock_resp = MockHTTPResponse(500, {"success": False, "errors": [{"message": "Internal Server Error"}]})

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            res = client.post("/api/agents/ceo/chat", json={"message": "Status"})
            self.assertEqual(res.status_code, 502)
            # Assert only Cloudflare was called
            self.assertEqual(mock_post.call_count, 1)

    async def test_16_existing_regression_suite(self):
        """16. Hermes3D custom runtime completions endpoint functions with Cloudflare."""
        client = TestClient(main.app)
        mock_resp = MockHTTPResponse(
            200,
            {
                "choices": [{"message": {"role": "assistant", "content": "Hello from 3D canvas!"}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 15},
            },
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            payload = {
                "lane": "atlas",
                "messages": [{"role": "user", "content": "Welcome"}],
                "session_id": "agent:atlas:main",
            }
            res = client.post("/v1/chat/completions", json=payload)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["object"], "chat.completion")
            self.assertEqual(data["choices"][0]["message"]["content"], "Hello from 3D canvas!")


if __name__ == "__main__":
    unittest.main()
