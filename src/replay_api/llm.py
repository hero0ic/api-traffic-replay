"""LLM providers for diagnosis.

Live calls use the OpenAI-compatible Chat Completions HTTP API via httpx.
Tests inject FakeProvider. The API stays off unless LLM_ENABLED is set.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from replay_api.config import Settings, get_settings


class LLMError(Exception):
    """The provider call failed or returned an unusable response."""


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, messages: list[dict[str, str]]) -> str: ...


class FakeProvider:
    """Deterministic provider for tests. No network."""

    name = "fake"
    model = "fake-model"

    def __init__(self, content: str = "Likely breaking change: status code changed.") -> None:
        self.content = content
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.content


class HttpChatProvider:
    """OpenAI-compatible chat completions client."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, messages: list[dict[str, str]]) -> str:
        url = f"{self.base_url}/chat/completions"
        try:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2,
                },
                timeout=self.timeout,
                trust_env=False,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"LLM HTTP {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response missing choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM returned an empty diagnosis")
        return content.strip()


def llm_is_configured(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return bool(cfg.llm_enabled and cfg.llm_api_key)


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    cfg = settings or get_settings()
    if not llm_is_configured(cfg):
        raise LLMError("AI diagnosis is disabled on this server")
    assert cfg.llm_api_key is not None
    return HttpChatProvider(
        api_key=cfg.llm_api_key,
        base_url=cfg.llm_base_url,
        model=cfg.llm_model,
    )


# Optional override used by tests instead of monkeypatching every call site.
_provider_override: LLMProvider | None = None


def set_provider_override(provider: LLMProvider | None) -> None:
    global _provider_override
    _provider_override = provider


def resolve_provider(settings: Settings | None = None) -> LLMProvider:
    if _provider_override is not None:
        return _provider_override
    return get_llm_provider(settings)
