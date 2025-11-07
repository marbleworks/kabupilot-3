"""LLM provider abstractions for kabupilot agents."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping, MutableMapping, Protocol, Sequence


DEFAULT_OPENAI_CHAT_MODEL = "gpt-5"
DEFAULT_XAI_GROK_MODEL = "grok-4-fast-reasoning"


def _env_flag(name: str, default: bool = False) -> bool:
    """Return ``True`` when an environment variable is truthy."""

    value = os.environ.get(name)
    if value is None:
        return default

    normalised = value.strip().lower()
    return normalised in {"1", "true", "yes", "on"}

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
        **options: object,
    ) -> str:
        ...


def _serialise_messages(messages: Iterable[ChatMessage]) -> list[Mapping[str, str]]:
    serialised: list[MutableMapping[str, str]] = []
    for message in messages:
        serialised.append({"role": message.role, "content": message.content})
    return serialised


class OpenAIChatProvider(SupportsLLMGenerate):
    """Wrapper around the official OpenAI Responses API client."""

    _RESPONSES_ALLOWED_OPTIONS = {"max_output_tokens", "metadata", "stop", "text"}

    def __init__(
        self,
        *,
        model: str = DEFAULT_OPENAI_CHAT_MODEL,
        api_key: str | None = None,
        organisation: str | None = None,
        enable_web_search: bool | None = None,
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

        if enable_web_search is None:
            enable_web_search = _env_flag("KABUPILOT_OPENAI_WEB_SEARCH", default=True)
        self._tools: tuple[Mapping[str, object], ...] | None = (
            ({"type": "web_search"},)
            if enable_web_search
            else None
        )

    def _extract_output_text(self, response: object) -> str | None:
        output_text = getattr(response, "output_text", None)
        if output_text:
            return str(output_text)

        output_items = getattr(response, "output", None)
        if not output_items:
            return None

        def _as_mapping(value: object) -> Mapping[str, object] | None:
            if isinstance(value, Mapping):
                return value
            model_dump = getattr(value, "model_dump", None)
            if callable(model_dump):
                try:
                    dumped = model_dump()
                except Exception:  # pragma: no cover - defensive
                    return None
                if isinstance(dumped, Mapping):
                    return dumped
            return None

        text_parts: list[str] = []
        for item in output_items:
            item_map = _as_mapping(item)
            if not item_map:
                item_type = getattr(item, "type", None)
                if item_type != "message":
                    continue
                contents = getattr(item, "content", None) or []
            else:
                if item_map.get("type") != "message":
                    continue
                contents = item_map.get("content") or []

            for block in contents:
                block_map = _as_mapping(block)
                block_type = None
                if block_map:
                    block_type = block_map.get("type")
                    if block_type == "output_text":
                        text = block_map.get("text")
                        if text:
                            text_parts.append(str(text))
                        continue
                    if block_type == "text":
                        text = block_map.get("text")
                        if isinstance(text, Mapping):
                            value = text.get("value")
                            if value:
                                text_parts.append(str(value))
                        elif text:
                            text_parts.append(str(text))
                        continue

                block_type = block_type or getattr(block, "type", None)
                if block_type == "output_text":
                    text_value = getattr(block, "text", None)
                    if text_value:
                        text_parts.append(str(text_value))
                    continue
                if block_type == "text":
                    text_obj = getattr(block, "text", None)
                    value = getattr(text_obj, "value", None)
                    if value:
                        text_parts.append(str(value))
        return "".join(text_parts) if text_parts else None

    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        **options: object,
    ) -> str:
        params: dict[str, object] = {
            "model": self._model,
            "input": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }

        if self._tools:
            params["tools"] = list(self._tools)

        for key in list(options):
            if key in self._RESPONSES_ALLOWED_OPTIONS:
                params[key] = options.pop(key)

        if options:
            unsupported = ", ".join(sorted(options))
            raise LLMProviderError(
                f"Unsupported options for OpenAIChatProvider: {unsupported}"
            )

        try:
            response = self._client.responses.create(**params)
        except Exception as exc:  # pragma: no cover - defensive
            raise LLMProviderError(f"OpenAI Responses API call failed: {exc}") from exc

        output_text = self._extract_output_text(response)
        if not output_text:
            raise LLMProviderError("OpenAI Responses API returned no output text")
        return output_text


def _extract_xai_text(content: object) -> str | None:
    """Normalise xAI's chat message content into a plain string."""

    if isinstance(content, str):
        return content

    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, Mapping):
                continue
            block_type = block.get("type")
            text_value = block.get("text")
            if isinstance(text_value, Mapping):
                nested = text_value.get("value")
                if isinstance(nested, str):
                    parts.append(nested)
                    continue
            if isinstance(text_value, str):
                parts.append(text_value)
                continue
            if block_type in {"text", "output_text"}:
                if isinstance(text_value, str):
                    parts.append(text_value)
                    continue
            data = block.get("content") if block_type == "output_text" else None
            if isinstance(data, str):
                parts.append(data)
        if parts:
            return "".join(parts)

    return None


class XAIChatProvider(SupportsLLMGenerate):
    """Simple HTTP client for the xAI (Grok) API."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_XAI_GROK_MODEL,
        api_key: str | None = None,
        base_url: str | None = None,
        enable_x_search: bool | None = None,
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

        if enable_x_search is None:
            enable_x_search = _env_flag("KABUPILOT_XAI_X_SEARCH", default=True)

        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        )
        self._model = model
        self._base_url = base_url or os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1")
        self._tools: tuple[Mapping[str, object], ...] | None = (
            (
                {
                    "xSearch": {
                        "enableImageUnderstanding": False,
                        "enableVideoUnderstanding": False,
                    }
                },
            )
            if enable_x_search
            else None
        )

    def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        **options: object,
    ) -> str:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": _serialise_messages(messages),
        }
        if self._tools:
            payload["tools"] = list(self._tools)
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
        content = _extract_xai_text(message.get("content"))
        if not content:
            raise LLMProviderError("xAI API returned an empty message content")
        return content


class OpenAIWithGrokToolProvider(SupportsLLMGenerate):
    """OpenAI Responses client that can call xAI Grok as an external tool."""

    _TOOL_NAME = "grok_search"
    _RESPONSES_ALLOWED_OPTIONS = {"max_output_tokens", "metadata", "stop", "text"}

    def __init__(
        self,
        *,
        model: str = DEFAULT_OPENAI_CHAT_MODEL,
        api_key: str | None = None,
        organisation: str | None = None,
        grok_model: str = DEFAULT_XAI_GROK_MODEL,
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
        max_tokens: int | None,
    ) -> str:
        payload: dict[str, object] = {
            "model": self._grok_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
        }
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
            content = _extract_xai_text(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - defensive
            raise LLMProviderError("Malformed response from xAI Grok API") from exc
        if not content:
            raise LLMProviderError("xAI Grok API returned an empty message content")
        return content

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
        **options: object,
    ) -> str:
        input_messages = [
            {"role": message.role, "content": message.content} for message in messages
        ]

        grok_system_prompt = str(
            options.pop("grok_system_prompt", self._default_grok_system_prompt)
        )
        grok_max_tokens = options.pop("grok_max_tokens", None)
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

