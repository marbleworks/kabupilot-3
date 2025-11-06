"""LLM provider abstractions for kabupilot agents."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping, MutableMapping, Protocol, Sequence

ChatRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    """Represents a single chat message passed to the LLM provider."""

    role: ChatRole
    content: str


class LLMProviderError(RuntimeError):
    """Raised when a provider cannot fulfil a generation request."""


class SupportsLLMGenerate(Protocol):
    """Protocol implemented by LLM providers."""

    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        **options: object,
    ) -> str:
        ...


def _serialise_messages(messages: Iterable[ChatMessage]) -> list[Mapping[str, str]]:
    serialised: list[MutableMapping[str, str]] = []
    for message in messages:
        serialised.append({"role": message.role, "content": message.content})
    return serialised


class OpenAIChatProvider(SupportsLLMGenerate):
    """Wrapper around the official OpenAI client."""

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        organisation: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            raise LLMProviderError(
                "The 'openai' package is required to use OpenAIChatProvider."
            ) from exc

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise LLMProviderError(
                "OPENAI_API_KEY environment variable is not set and no api_key was provided."
            )

        self._client = OpenAI(api_key=key, organization=organisation)
        self._model = model

    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        **options: object,
    ) -> str:
        params: dict[str, object] = {
            "model": self._model,
            "messages": _serialise_messages(messages),
        }
        if temperature is not None:
            params["temperature"] = float(temperature)
        params.update(options)

        response = self._client.chat.completions.create(**params)
        try:
            choice = response.choices[0]
        except (AttributeError, IndexError) as exc:  # pragma: no cover - defensive
            raise LLMProviderError("No choices returned from OpenAI API") from exc
        message = getattr(choice, "message", None)
        if message is None:
            raise LLMProviderError("Malformed response from OpenAI API: missing message")
        content = getattr(message, "content", None)
        if not content:
            raise LLMProviderError(
                "OpenAI API returned an empty message. Check your request parameters."
            )
        return str(content)


class XAIChatProvider(SupportsLLMGenerate):
    """Simple HTTP client for the xAI (Grok) API."""

    def __init__(
        self,
        *,
        model: str = "grok-beta",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - import guard
            raise LLMProviderError(
                "The 'requests' package is required to use XAIChatProvider."
            ) from exc

        key = api_key or os.environ.get("XAI_API_KEY")
        if not key:
            raise LLMProviderError(
                "XAI_API_KEY environment variable is not set and no api_key was provided."
            )

        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        )
        self._model = model
        self._base_url = base_url or os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1")

    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        **options: object,
    ) -> str:
        import json

        payload: dict[str, object] = {
            "model": self._model,
            "messages": _serialise_messages(messages),
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if options:
            payload.update(options)

        response = self._session.post(
            f"{self._base_url.rstrip('/')}/chat/completions", json=payload, timeout=60
        )
        if response.status_code >= 400:
            raise LLMProviderError(
                f"xAI API error {response.status_code}: {response.text.strip()}"
            )
        try:
            data = response.json()
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise LLMProviderError("Failed to decode response from xAI API") from exc

        choices = data.get("choices")
        if not choices:
            raise LLMProviderError("xAI API returned no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        if not isinstance(message, dict):
            raise LLMProviderError("xAI API response missing message field")
        content = message.get("content")
        if not content:
            raise LLMProviderError("xAI API returned an empty message content")
        return str(content)


__all__ = [
    "ChatMessage",
    "ChatRole",
    "LLMProviderError",
    "OpenAIChatProvider",
    "XAIChatProvider",
]
