"""LLM provider abstractions for kabupilot agents."""

from __future__ import annotations

import json
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


class OpenAIWithGrokToolProvider(SupportsLLMGenerate):
    """OpenAI Responses client that can call xAI Grok as an external tool."""

    _TOOL_NAME = "grok_search"
    _RESPONSES_ALLOWED_OPTIONS = {"max_output_tokens", "metadata", "stop"}

    def __init__(
        self,
        *,
        model: str = "gpt-4.1",
        api_key: str | None = None,
        organisation: str | None = None,
        grok_model: str = "grok-4",
        grok_api_key: str | None = None,
        grok_base: str | None = None,
        grok_chat_path: str = "/v1/chat/completions",
        default_grok_system_prompt: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            raise LLMProviderError(
                "The 'openai' package is required to use OpenAIWithGrokToolProvider."
            ) from exc

        try:
            import requests
        except ImportError as exc:  # pragma: no cover - import guard
            raise LLMProviderError(
                "The 'requests' package is required to use OpenAIWithGrokToolProvider."
            ) from exc

        openai_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not openai_key:
            raise LLMProviderError(
                "OPENAI_API_KEY environment variable is not set and no api_key was provided."
            )

        xai_key = grok_api_key or os.environ.get("XAI_API_KEY")
        if not xai_key:
            raise LLMProviderError(
                "XAI_API_KEY environment variable is not set and no grok_api_key was provided."
            )

        self._client = OpenAI(api_key=openai_key, organization=organisation)
        self._model = model

        self._grok_model = grok_model
        self._grok_base = (grok_base or os.environ.get("XAI_BASE") or "https://api.x.ai").rstrip(
            "/"
        )
        self._grok_chat_path = grok_chat_path
        self._grok_timeout = 60
        self._default_grok_system_prompt = (
            default_grok_system_prompt
            or "You are Grok from xAI providing concise, factual market intelligence."
        )

        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {xai_key}", "Content-Type": "application/json"}
        )

    def _call_grok(
        self,
        *,
        query: str,
        system_prompt: str,
        temperature: float | None,
        max_tokens: int | None,
    ) -> str:
        payload: dict[str, object] = {
            "model": self._grok_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)

        response = self._session.post(
            f"{self._grok_base}{self._grok_chat_path}", json=payload, timeout=self._grok_timeout
        )
        if response.status_code >= 400:
            raise LLMProviderError(
                f"xAI Grok API error {response.status_code}: {response.text.strip()}"
            )
        try:
            data = response.json()
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise LLMProviderError("Failed to decode response from xAI Grok API") from exc

        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - defensive
            raise LLMProviderError("Malformed response from xAI Grok API") from exc

    def _parse_tool_arguments(self, arguments: object) -> Mapping[str, object]:
        if arguments is None:
            return {}
        if isinstance(arguments, Mapping):
            return arguments
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise LLMProviderError("Failed to parse Grok tool arguments") from exc
            if not isinstance(parsed, Mapping):
                raise LLMProviderError("Grok tool arguments must decode to an object")
            return parsed
        raise LLMProviderError("Unsupported Grok tool arguments type")

    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        **options: object,
    ) -> str:
        input_messages = [
            {"role": message.role, "content": message.content} for message in messages
        ]

        grok_system_prompt = str(
            options.pop("grok_system_prompt", self._default_grok_system_prompt)
        )
        grok_temperature = options.pop("grok_temperature", None)
        grok_max_tokens = options.pop("grok_max_tokens", None)
        if grok_temperature is not None:
            try:
                grok_temperature = float(grok_temperature)
            except (TypeError, ValueError) as exc:
                raise LLMProviderError("grok_temperature must be numeric") from exc
        if grok_max_tokens is not None:
            try:
                grok_max_tokens = int(grok_max_tokens)
            except (TypeError, ValueError) as exc:
                raise LLMProviderError("grok_max_tokens must be an integer") from exc

        params: dict[str, object] = {
            "model": self._model,
            "input": input_messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": self._TOOL_NAME,
                        "description": "Send a query to xAI Grok and return its textual answer.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "User question to forward to Grok.",
                                }
                            },
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
        }
        if temperature is not None:
            params["temperature"] = float(temperature)

        for key in list(options):
            if key in self._RESPONSES_ALLOWED_OPTIONS:
                params[key] = options.pop(key)

        if options:
            unsupported = ", ".join(sorted(options))
            raise LLMProviderError(
                f"Unsupported options for OpenAIWithGrokToolProvider: {unsupported}"
            )

        try:
            initial = self._client.responses.create(**params)
        except Exception as exc:  # pragma: no cover - defensive
            raise LLMProviderError(f"OpenAI Responses API call failed: {exc}") from exc

        tool_calls = []
        for item in getattr(initial, "output", []) or []:
            if getattr(item, "type", None) == "tool_call" and getattr(item, "name", None) == self._TOOL_NAME:
                tool_calls.append(item)

        if tool_calls:
            tool_outputs = []
            for call in tool_calls:
                arguments = self._parse_tool_arguments(getattr(call, "arguments", None))
                query = str(arguments.get("query", ""))
                if not query:
                    raise LLMProviderError("Grok tool was invoked without a query")
                call_id = getattr(call, "id", None)
                if not call_id:
                    raise LLMProviderError("Grok tool call missing identifier")
                grok_response = self._call_grok(
                    query=query,
                    system_prompt=grok_system_prompt,
                    temperature=grok_temperature,
                    max_tokens=grok_max_tokens,
                )
                tool_outputs.append({"tool_call_id": call_id, "output": grok_response})

            try:
                final = self._client.responses.submit_tool_outputs(
                    initial.id, {"tool_outputs": tool_outputs}
                )
            except Exception as exc:  # pragma: no cover - defensive
                raise LLMProviderError(
                    f"OpenAI Responses API submit_tool_outputs failed: {exc}"
                ) from exc
            output_text = getattr(final, "output_text", None)
        else:
            output_text = getattr(initial, "output_text", None)

        if not output_text:
            raise LLMProviderError("OpenAI Responses API returned no output text")
        return str(output_text)


__all__ = [
    "ChatMessage",
    "ChatRole",
    "LLMProviderError",
    "SupportsLLMGenerate",
    "OpenAIChatProvider",
    "XAIChatProvider",
    "OpenAIWithGrokToolProvider",
]
