"""OpenAI GPT generator (Chat Completions API) — a data-plane ``Generator``.

A drop-in alternative to the Anthropic adapter for teams standardizing on
OpenAI, or as a stopgap until a Claude key is available. Pair it with an
``Embedder`` (the OpenAI embedder, Ollama, or Voyage) via the factory.

Message mapping and response parsing are pure functions so the tool-use
round-trip — the part most likely to break — is unit-tested offline without a
key or network; only ``generate`` performs I/O (lazy ``httpx``).

Contract notes (OpenAI Chat Completions):
  * the system prompt is a ``system`` message, not a separate field;
  * assistant tool calls carry ``tool_calls`` whose ``function.arguments`` is a
    JSON *string*; tool results are ``role:"tool"`` messages keyed by
    ``tool_call_id``;
  * ``finish_reason == "tool_calls"`` maps to our ``tool_use`` stop reason and
    ``content_filter`` to ``refusal`` so the orchestrator fails closed.
"""

from __future__ import annotations

import json
import os

from ..errors import ConfigError, GenerationError
from .base import ChatMessage, LLMResponse, MsgRole, ToolCall, ToolSpec


def _httpx():
    try:
        import httpx  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise ConfigError("openai generator requires httpx: pip install httpx") from exc
    return httpx


class OpenAIGenerator:
    def __init__(
        self,
        model: str = "gpt-5.5",
        api_key: str | None = None,
        *,
        base_url: str = "https://api.openai.com/v1",
        max_completion_tokens: int = 4096,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.max_completion_tokens = max_completion_tokens
        # gpt-5.x reject temperature != 1; leave it None to omit (recommended).
        self.temperature = temperature
        # Reasoning models (e.g. gpt-5.6 Sol/Terra/Luna) require "none" to expose
        # function tools on chat/completions; gpt-5.5 and older keep reasoning
        # while tool-calling, so the default (omit) is correct for the default model.
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout

    def _body(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSpec] | None
    ) -> dict:
        body: dict = {
            "model": self.model,
            "messages": self._to_openai_messages(system, messages),
            # newer models reject the legacy `max_tokens`; this key is universal.
            "max_completion_tokens": self.max_completion_tokens,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
        return body

    async def generate(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise ConfigError("OPENAI_API_KEY is not set")
        httpx = _httpx()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=self._body(system, messages, tools),
            )
            if resp.status_code >= 400:
                raise GenerationError(
                    f"openai chat completions failed ({resp.status_code}): {resp.text}"
                )
            return self._parse(resp.json())

    @staticmethod
    def _to_openai_messages(system: str, messages: list[ChatMessage]) -> list[dict]:
        """Map neutral messages onto OpenAI's chat shape (system prompt first)."""
        out: list[dict] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            if m.role == MsgRole.TOOL:
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.tool_call_id or "",
                        "content": m.content,
                    }
                )
            elif m.role == MsgRole.ASSISTANT and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
            else:
                role = "assistant" if m.role == MsgRole.ASSISTANT else "user"
                if m.images:
                    parts: list[dict] = [{"type": "text", "text": m.content}]
                    parts.extend(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{img.media_type};base64,{img.data_b64}"
                            },
                        }
                        for img in m.images
                    )
                    out.append({"role": role, "content": parts})
                else:
                    out.append({"role": role, "content": m.content})
        return out

    @staticmethod
    def _parse(data: dict) -> LLMResponse:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        finish = choice.get("finish_reason")

        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(
                ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=arguments)
            )

        if finish == "content_filter":
            stop_reason = "refusal"
        elif finish == "tool_calls" or tool_calls:
            stop_reason = "tool_use"
        else:
            stop_reason = "end_turn"

        usage = data.get("usage") or {}
        return LLMResponse(
            text=message.get("content") or "",
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage={
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        )
