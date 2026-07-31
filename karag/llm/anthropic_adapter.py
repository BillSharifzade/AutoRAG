"""Production target: Claude Opus 4.8 via the official Anthropic SDK.

This adapter is a *Generator only* — Claude has no first-party embeddings
endpoint, so pair it with an ``Embedder`` (Ollama locally, or Voyage/OpenAI in
production). The ``anthropic`` package is imported lazily so offline tests never
require it.

Notable, current-API choices (verified against the Anthropic API reference):
  * model id ``claude-opus-4-8``
  * adaptive thinking (``thinking={"type": "adaptive"}``) — the recommended mode
  * no ``temperature`` / ``budget_tokens`` (rejected on Opus 4.8)
  * tool_use blocks are mapped to :class:`ToolCall`; a ``refusal`` stop reason
    is surfaced so the orchestrator can fail closed rather than leak.
"""

from __future__ import annotations

from ..errors import GenerationError
from .base import ChatMessage, LLMResponse, MsgRole, ToolCall, ToolSpec


def _client(api_key: str | None):
    try:
        import anthropic  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise GenerationError(
            "anthropic adapter requires the SDK: pip install anthropic"
        ) from exc
    return anthropic.AsyncAnthropic(api_key=api_key) if api_key else anthropic.AsyncAnthropic()


class AnthropicGenerator:
    def __init__(
        self,
        model: str = "claude-opus-4-8",
        api_key: str | None = None,
        max_tokens: int = 4096,
        effort: str = "high",
    ) -> None:
        self.model = model
        self._api_key = api_key
        self.max_tokens = max_tokens
        self.effort = effort

    async def generate(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        client = _client(self._api_key)
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            "messages": self._to_anthropic_messages(messages),
        }
        if tools:
            kwargs["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ]
        resp = await client.messages.create(**kwargs)

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
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason or "end_turn",
            usage={
                "input_tokens": getattr(resp.usage, "input_tokens", 0),
                "output_tokens": getattr(resp.usage, "output_tokens", 0),
            },
        )

    @staticmethod
    def _to_anthropic_messages(messages: list[ChatMessage]) -> list[dict]:
        """Map our neutral messages onto the Anthropic content-block shape.

        Tool results become ``tool_result`` blocks in a user turn, keyed by the
        originating ``tool_use_id``.
        """
        out: list[dict] = []
        for m in messages:
            if m.role == MsgRole.TOOL:
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id or "",
                                "content": m.content,
                            }
                        ],
                    }
                )
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
