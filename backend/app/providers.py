from __future__ import annotations

import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

OLLAMA_DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_DEFAULT_THINK = os.getenv("OLLAMA_THINK", "false").strip().casefold() == "true"


def build_ollama_chat_payload(
    messages: list[dict[str, str]],
    model: str = OLLAMA_DEFAULT_MODEL,
    think: bool = OLLAMA_DEFAULT_THINK,
    temperature: float = 0.6,
    max_tokens: int = 700,
) -> dict[str, Any]:
    """Build a bounded local chat request with an explicit Qwen3 thinking mode."""
    request_payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": "10m",
        "options": {
            "temperature": temperature,
            "num_ctx": 4096,
            "num_predict": max_tokens,
        },
    }
    if model.casefold().startswith("qwen3"):
        request_payload["think"] = think
    return request_payload


class AIProviderError(Exception):
    """Base exception for all AI provider operations."""
    pass


class AIProviderAuthError(AIProviderError):
    """Raised when authentication with the provider fails."""
    pass


class AIProviderModelError(AIProviderError):
    """Raised when the requested model is not found or invalid."""
    pass


class AIProviderRateLimitError(AIProviderError):
    """Raised when provider rate limits are exceeded."""
    pass


class AIProviderServiceError(AIProviderError):
    """Raised when the remote AI service returns a 5xx or server error."""
    pass


class AIProviderUnavailableError(AIProviderError):
    """Raised when the AI provider endpoint cannot be reached."""
    pass


class AIProviderTimeoutError(AIProviderError):
    """Raised when an AI provider request times out."""
    pass


class AIProviderMalformedResponseError(AIProviderError):
    """Raised when the AI provider returns an unparseable response."""
    pass


@dataclass
class AICompletionResult:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    raw_response: dict[str, Any] | None = None


def estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    """Provide a conservative heuristic token estimate before dispatch."""
    chars = sum(len(str(m.get("content", ""))) for m in messages)
    return max(1, (chars // 4) + (len(messages) * 4))


def parse_provider_token_count(
    raw_usage: Any,
    token_key: str,
    fallback_estimate: int,
) -> int:
    """Safely extract token counts from provider usage metadata.

    Distinguishes:
    - Missing or non-dict usage -> fallback_estimate
    - Missing key or None value -> fallback_estimate
    - Legitimate 0 value -> 0 (preserved)
    - Positive numeric (int or float) -> truncated/normalized int
    - Negative numeric, NaN, Inf, or non-numeric/malformed -> fallback_estimate
    """
    safe_fallback = max(0, int(fallback_estimate or 0))
    if not isinstance(raw_usage, dict):
        return safe_fallback

    if token_key not in raw_usage:
        return safe_fallback

    val = raw_usage[token_key]
    if val is None:
        return safe_fallback

    # In Python, bool is a subclass of int, so reject booleans explicitly
    if isinstance(val, bool):
        return safe_fallback

    if isinstance(val, (int, float)):
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return safe_fallback
        int_val = int(val)
        if int_val < 0:
            return safe_fallback
        return int_val

    if isinstance(val, str):
        val_str = val.strip()
        try:
            num = float(val_str)
            if math.isnan(num) or math.isinf(num):
                return safe_fallback
            int_val = int(num)
            if int_val < 0:
                return safe_fallback
            return int_val
        except (ValueError, TypeError):
            return safe_fallback

    return safe_fallback


class BaseAIProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.6,
        max_tokens: int = 700,
        think: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> AICompletionResult:
        """Execute a non-streaming chat completion."""
        pass

    @abstractmethod
    async def health_check(self) -> tuple[bool, str | None]:
        """Verify availability and configured model readiness."""
        pass


class OllamaProvider(BaseAIProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        think: bool | None = None,
    ):
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen3:4b")
        if think is not None:
            self.think = think
        else:
            self.think = os.getenv("OLLAMA_THINK", "false").strip().casefold() == "true"

    async def health_check(self) -> tuple[bool, str | None]:
        """Verify local Ollama daemon connectivity."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(2.5)) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                payload = response.json()
            available = [item.get("name", "") for item in payload.get("models", [])]
            selected = next(
                (name for name in available if name == self.model or name.startswith(f"{self.model}:")),
                None,
            )
            return True, selected or self.model
        except Exception:
            return False, None

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.6,
        max_tokens: int = 700,
        think: bool | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> AICompletionResult:
        use_think = self.think if think is None else think
        payload = build_ollama_chat_payload(
            messages=messages,
            model=self.model,
            think=use_think,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        async def _do_post(c: httpx.AsyncClient) -> dict[str, Any]:
            resp = await c.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()

        try:
            if client is not None:
                result = await _do_post(client)
            else:
                async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0)) as c:
                    result = await _do_post(c)
        except httpx.TimeoutException as error:
            raise AIProviderTimeoutError("The local AI model timed out.") from error
        except httpx.ConnectError as error:
            raise AIProviderUnavailableError("Ollama daemon is not reachable.") from error
        except httpx.HTTPStatusError as error:
            raise AIProviderServiceError(f"Ollama returned HTTP {error.response.status_code}.") from error
        except Exception as error:
            raise AIProviderMalformedResponseError(f"Ollama response failed: {error}") from error

        if not isinstance(result, dict) or not isinstance(result.get("message"), dict):
            raise AIProviderMalformedResponseError("Ollama returned an unexpected response structure.")

        content = str(result["message"].get("content") or "")
        fallback_input = estimate_messages_tokens(messages)
        fallback_output = max(1, len(content) // 4) if content else 0

        prompt_tokens = parse_provider_token_count(
            {"t": result.get("prompt_eval_count")}, "t", fallback_input
        )
        completion_tokens = parse_provider_token_count(
            {"t": result.get("eval_count")}, "t", fallback_output
        )

        return AICompletionResult(
            content=content,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            raw_response=result,
        )


class CloudflareWorkersAIProvider(BaseAIProvider):
    name = "cloudflare"

    def __init__(
        self,
        account_id: str | None = None,
        api_token: str | None = None,
        model: str | None = None,
        base_endpoint: str | None = None,
    ):
        self.account_id = account_id.strip() if account_id is not None else (os.getenv("CLOUDFLARE_ACCOUNT_ID") or "").strip()
        self.api_token = api_token.strip() if api_token is not None else (os.getenv("CLOUDFLARE_API_TOKEN") or "").strip()
        self.model = model.strip() if model is not None else (os.getenv("CLOUDFLARE_MODEL") or "@cf/qwen/qwen3.8-27b").strip()
        self.custom_endpoint = base_endpoint

    @property
    def endpoint_url(self) -> str:
        if self.custom_endpoint:
            return self.custom_endpoint
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/v1/chat/completions"

    async def health_check(self) -> tuple[bool, str | None]:
        """Verify Cloudflare credentials and model access."""
        if not self.account_id or not self.api_token:
            return False, "Missing Cloudflare credentials"
        try:
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            }
            search_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/models/search?search={self.model}"
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(search_url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        return True, self.model
            return True, self.model
        except Exception:
            return bool(self.account_id and self.api_token), self.model

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.6,
        max_tokens: int = 700,
        think: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> AICompletionResult:
        if not self.account_id or not self.api_token:
            raise AIProviderAuthError("Cloudflare Workers AI credentials missing: CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are required.")

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        async def _do_post(c: httpx.AsyncClient) -> httpx.Response:
            return await c.post(self.endpoint_url, headers=headers, json=payload)

        try:
            if client is not None:
                response = await _do_post(client)
            else:
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as c:
                    response = await _do_post(c)
        except httpx.TimeoutException as error:
            raise AIProviderTimeoutError("Cloudflare Workers AI request timed out.") from error
        except httpx.ConnectError as error:
            raise AIProviderUnavailableError("Cloudflare Workers AI endpoint is unreachable.") from error
        except Exception as error:
            raise AIProviderServiceError(f"Cloudflare Workers AI connection failure: {error}") from error

        if response.status_code in (401, 403):
            raise AIProviderAuthError("Cloudflare Workers AI credentials are invalid or unauthorized.")
        if response.status_code == 404:
            raise AIProviderModelError(f"Cloudflare Workers AI model '{self.model}' was not found.")
        if response.status_code == 429:
            raise AIProviderRateLimitError("Cloudflare Workers AI rate limit reached.")
        if response.status_code >= 500:
            raise AIProviderServiceError(f"Cloudflare Workers AI returned HTTP {response.status_code}.")
        if response.status_code != 200:
            raise AIProviderServiceError(f"Cloudflare Workers AI request failed with HTTP {response.status_code}.")

        try:
            result = response.json()
        except Exception as error:
            raise AIProviderMalformedResponseError(f"Could not parse Cloudflare JSON response: {error}") from error

        choices = result.get("choices")
        if not isinstance(choices, list) or len(choices) == 0:
            raise AIProviderMalformedResponseError("Cloudflare Workers AI returned no completion choices.")

        first_choice = choices[0]
        message_obj = first_choice.get("message") if isinstance(first_choice, dict) else None
        if not isinstance(message_obj, dict):
            raise AIProviderMalformedResponseError("Cloudflare Workers AI choice message is malformed.")

        content = str(message_obj.get("content") or "")

        raw_usage = result.get("usage")
        fallback_input = estimate_messages_tokens(messages)
        fallback_output = max(1, len(content) // 4) if content else 0

        prompt_tokens = parse_provider_token_count(raw_usage, "prompt_tokens", fallback_input)
        completion_tokens = parse_provider_token_count(raw_usage, "completion_tokens", fallback_output)

        fallback_total = prompt_tokens + completion_tokens
        total_tokens = parse_provider_token_count(raw_usage, "total_tokens", fallback_total)
        total_tokens = max(total_tokens, prompt_tokens + completion_tokens)

        return AICompletionResult(
            content=content,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            raw_response=result,
        )


def get_ai_provider(provider_type: str | None = None) -> BaseAIProvider:
    """Resolve the active AI provider singleton based on configuration."""
    provider = (provider_type or os.getenv("AI_PROVIDER", "ollama")).strip().casefold()
    if provider == "cloudflare":
        return CloudflareWorkersAIProvider()
    return OllamaProvider()
