"""Production target: Claude via the official Anthropic SDK.

This adapter is a *Generator only* — Claude has no first-party embeddings
endpoint, so pair it with an ``Embedder`` (Ollama locally, or Voyage/OpenAI in
production). The ``anthropic`` package is imported lazily so offline tests never
require it.

Notable, current-API choices (verified against the Anthropic API reference):
  * adaptive thinking (``thinking={"type": "adaptive"}``) — the recommended mode
  * no ``temperature`` / ``budget_tokens`` (rejected on current models)
  * the system prompt and the tool list carry ``cache_control`` breakpoints:
    they are identical from one request to the next for a given user, and a
    cached prefix is billed at a tenth of the price
  * when the caller wants the answer as it is written (``on_delta``), the
    request streams and text deltas are forwarded; the final message is still
    assembled by the SDK, so tool calls and usage are read exactly as in the
    non-streaming case
  * tool_use blocks are mapped to :class:`ToolCall`; a ``refusal`` stop reason
    is surfaced so the orchestrator can fail closed rather than leak.
"""

from __future__ import annotations

from ..errors import GenerationError
from .base import ChatMessage, DeltaCallback, LLMResponse, MsgRole, ToolCall, ToolSpec


def _client(api_key: str | None):
    try:
        import anthropic  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise GenerationError(
            "anthropic adapter requires the SDK: pip install anthropic"
        ) from exc
    return anthropic.AsyncAnthropic(api_key=api_key) if api_key else anthropic.AsyncAnthropic()


_CACHE = {"type": "ephemeral"}


class AnthropicGenerator:
    def __init__(
        self,
        model: str = "claude-opus-4-8",
        api_key: str | None = None,
        max_tokens: int = 8192,
        effort: str = "high",
    ) -> None:
        self.model = model
        self._api_key = api_key
        self.max_tokens = max_tokens
        self.effort = effort

    def _request(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSpec] | None
    ) -> dict:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # One breakpoint after the system prompt: the handbook and role
            # guide inside it never change between a user's requests.
            "system": [{"type": "text", "text": system, "cache_control": _CACHE}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            "messages": self._to_anthropic_messages(messages),
        }
        if tools:
            specs = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]
            # Tools render before the system prompt in the cached prefix; a
            # breakpoint on the last one caches the whole list.
            specs[-1] = {**specs[-1], "cache_control": _CACHE}
            kwargs["tools"] = specs
        return kwargs

    async def generate(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> LLMResponse:
        client = _client(self._api_key)
        kwargs = self._request(system, messages, tools)
        try:
            if on_delta is None:
                resp = await client.messages.create(**kwargs)
            else:
                async with client.messages.stream(**kwargs) as stream:
                    async for text in stream.text_stream:
                        if text:
                            await on_delta(text)
                    resp = await stream.get_final_message()
        except Exception as exc:  # the SDK's typed errors all derive from Exception
            name = type(exc).__name__
            if name in ("AuthenticationError", "PermissionDeniedError",
                        "RateLimitError", "APIConnectionError", "APITimeoutError",
                        "APIStatusError", "BadRequestError", "NotFoundError",
                        "InternalServerError"):
                raise GenerationError(f"anthropic: {name}: {exc}") from exc
            raise
        return self._parse(resp)

    @staticmethod
    def _parse(resp) -> LLMResponse:
        if resp.stop_reason == "refusal":
            return LLMResponse(text="", stop_reason="refusal")

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )
        usage = {
            "input_tokens": getattr(resp.usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(resp.usage, "output_tokens", 0) or 0,
        }
        for key in ("cache_read_input_tokens", "cache_creation_input_tokens"):
            value = getattr(resp.usage, key, None)
            if value:
                usage[key] = value
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason or "end_turn",
            usage=usage,
        )

    @staticmethod
    def _to_anthropic_messages(messages: list[ChatMessage]) -> list[dict]:
        """Map our neutral messages onto the Anthropic content-block shape.

        Tool results become ``tool_result`` blocks in a user turn, keyed by the
        originating ``tool_use_id``. Consecutive tool results are merged into
        one user turn — the API wants every result of a parallel tool call in
        a single message.
        """
        out: list[dict] = []
        for m in messages:
            if m.role == MsgRole.TOOL:
                block = {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": m.content,
                }
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                        and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif m.role == MsgRole.ASSISTANT and m.tool_calls:
                blocks: list[dict] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
            else:
                role = "assistant" if m.role == MsgRole.ASSISTANT else "user"
                if m.images:
                    blocks = [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": img.media_type,
                                "data": img.data_b64,
                            },
                        }
                        for img in m.images
                    ]
                    blocks.append({"type": "text", "text": m.content})
                    out.append({"role": role, "content": blocks})
                else:
                    out.append({"role": role, "content": m.content})
        return out
