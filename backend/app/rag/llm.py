"""DeepSeek chat completions (OpenAI-compatible) over httpx. Errors never include headers or keys."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence

import httpx

from .settings import ConfigError, RagSettings

_RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


@dataclass
class LLMReply:
    content: str
    model: str | None = None
    usage: dict[str, Any] | None = None


class LLM(Protocol):
    model: str

    def complete(self, messages: Sequence[dict[str, str]]) -> LLMReply: ...


class DeepSeekClient:
    def __init__(self, settings: RagSettings, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_attempts: int = 4) -> None:
        if not settings.deepseek_api_key:
            raise ConfigError("DEEPSEEK_API_KEY is not set")
        self.model = settings.llm_model
        self._url = f"{settings.deepseek_base_url}/chat/completions"
        self._key, self._max_tokens = settings.deepseek_api_key, settings.llm_max_tokens
        self._client, self._sleep, self._attempts = client or httpx.Client(timeout=120), sleep, max_attempts
        self.calls = 0

    def complete(self, messages: Sequence[dict[str, str]]) -> LLMReply:
        body = {"model": self.model, "messages": list(messages), "temperature": 0, "max_tokens": self._max_tokens,
                "response_format": {"type": "json_object"}}
        for attempt in range(1, self._attempts + 1):
            self.calls += 1
            try:
                response = self._client.post(self._url, json=body, headers={"Authorization": f"Bearer {self._key}"})
            except httpx.HTTPError as exc:
                if attempt == self._attempts:
                    raise LLMError(f"deepseek: request failed ({type(exc).__name__})") from None
                self._sleep(min(2 ** attempt, 30))
                continue
            if response.status_code in _RETRY_STATUS and attempt < self._attempts:
                self._sleep(min(2 ** attempt, 30))
                continue
            if response.status_code >= 400:
                try:
                    message = (response.json().get("error") or {}).get("message", "")
                except ValueError:
                    message = response.text
                raise LLMError(f"deepseek: HTTP {response.status_code}: {str(message)[:200]}")
            data = response.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                raise LLMError("deepseek: unexpected response shape") from None
            return LLMReply(content or "", data.get("model"), data.get("usage"))
        raise LLMError("deepseek: gave up")  # pragma: no cover
