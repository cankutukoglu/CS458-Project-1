from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any
from urllib import error, request

from framework.llm.prompts import SYSTEM_PROMPT, build_user_prompt


class SelectorRepairClient(ABC):
    """Provider-neutral interface for selector repair."""

    provider_name = "unknown"

    @abstractmethod
    def repair_selector(self, payload: dict[str, Any]) -> str:
        raise NotImplementedError


class OpenAISelectorRepairClient(SelectorRepairClient):
    provider_name = "openai"
    endpoint = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def repair_selector(self, payload: dict[str, Any]) -> str:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(payload)},
            ],
        }
        response = _post_json(
            self.endpoint,
            body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        return response["choices"][0]["message"]["content"]


class AnthropicSelectorRepairClient(SelectorRepairClient):
    provider_name = "anthropic"
    endpoint = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")

    def repair_selector(self, payload: dict[str, Any]) -> str:
        body = {
            "model": self.model,
            "max_tokens": 128,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": build_user_prompt(payload)},
            ],
        }
        response = _post_json(
            self.endpoint,
            body,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        content = response["content"][0]["text"]
        return content


class GeminiSelectorRepairClient(SelectorRepairClient):
    provider_name = "gemini"
    endpoint_template = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def repair_selector(self, payload: dict[str, Any]) -> str:
        body = {
            "system_instruction": {
                "parts": [
                    {"text": SYSTEM_PROMPT},
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": build_user_prompt(payload)},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
            },
        }
        response = _post_json(
            self.endpoint_template.format(model=self.model),
            body,
            headers={
                "x-goog-api-key": self.api_key,
                "x-goog-api-client": "cs458-self-healing-framework/0.1.0",
                "Content-Type": "application/json",
            },
        )
        candidates = response.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        content = "".join(text_parts).strip()
        if not content:
            raise RuntimeError("Gemini returned an empty response")
        return content


def create_selector_repair_client() -> SelectorRepairClient:
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return OpenAISelectorRepairClient(api_key)
    if provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        return AnthropicSelectorRepairClient(api_key)
    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        return GeminiSelectorRepairClient(api_key)
    raise RuntimeError(f"Unsupported LLM provider: {provider}")


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    encoded = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=encoded, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed with status {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM request could not be completed: {exc.reason}") from exc
    return json.loads(raw)
