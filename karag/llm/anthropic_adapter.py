"""Production target: Claude via the official Anthropic SDK.

This adapter is a *Generator only* — Claude has no first-party embeddings
endpoint, so pair it with an ``Embedder`` (Ollama locally, or Voyage/OpenAI in
production). The ``anthropic`` package is imported lazily so offline tests never
require it.

Current-API choices, each one deliberate:

* **Adaptive thinking, effort as the dial.** Current models think on every
  request; ``output_config.effort`` decides how much (and so latency and cost).
  No ``temperature`` / ``budget_tokens`` — both are rejected.
* **Thinking blocks travel back unchanged.** Inside one turn's tool loop the
  assistant's content blocks (thinking, text, tool_use) are replayed verbatim,
  so the model keeps its reasoning between tool calls. Earlier chat turns are
  replayed as text only — dropping a *leading* run of thinking is allowed;
  editing the middle is not. ``block_binding: drop_block`` makes any mistake
  degrade (the block is dropped) instead of failing the request.
* **The prefix never changes inside a turn.** The system prompt and the tool
  list are identical on every call of a turn; the closing "answer now" call
  keeps the tools and sets ``tool_choice: none`` instead of removing them,
  because changing ``tools`` would invalidate every thinking block so far.
  That same stability is what makes prompt caching pay.
* **Server-side refusal fallback** (``fallbacks: "default"``): when a safety
  classifier declines a benign request, the API re-runs it on the model
  Anthropic recommends for that category inside the same call.
* **Always streamed.** Long answers and large tool inputs (a whole spreadsheet
  passed to ``create_xlsx``) never hit an HTTP timeout; text deltas are
  forwarded when the caller wants them, and the final message is assembled by
  the SDK either way. Tool inputs stream eagerly; the executor validates every
  input against its schema before anything runs.
"""

from __future__ import annotations

import asyncio
import logging

from ..errors import GenerationError
from .base import (
    STREAM_RESET,
    ChatMessage,
    DeltaCallback,
    LLMResponse,
    MsgRole,
    ToolCall,
    ToolSpec,
)

log = logging.getLogger("karag.llm.anthropic")

_CACHE = {"type": "ephemeral"}

BETA_FALLBACK = "server-side-fallback-2026-07-01"
BETA_THINKING_BINDING = "thinking-binding-controls-2026-08-01"

# Models whose request surface this adapter targets: adaptive thinking with an
# effort level, server-side refusal fallback and thinking-block binding. An
# older model configured by hand still works — it simply gets the plain shape.
_CURRENT_FAMILIES = (
    "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5", "claude-mythos-5",
)
_NO_EFFORT = ("claude-haiku-4-5", "claude-sonnet-4-5", "claude-3")


def _is_current(model: str) -> bool:
    return model.startswith(_CURRENT_FAMILIES)


def _sdk():
    try:
        import anthropic  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise GenerationError(
            "anthropic adapter requires the SDK: pip install anthropic"
        ) from exc
    return anthropic


class AnthropicGenerator:
    def __init__(
        self,
        model: str = "claude-sonnet-5-5",
        api_key: str | None = None,
        max_tokens: int = 32000,
        effort: str = "medium",
        workspace_id: str | None = None,
        refusal_fallback: str | None = "default",
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._workspace_id = workspace_id or None
        self.max_tokens = max_tokens
        self.effort = effort
        self.refusal_fallback = refusal_fallback or None
        # One client per event loop: an AsyncAnthropic holds a connection pool
        # bound to the loop that created it, and reusing it saves a TLS
        # handshake on every model call.
        self._clients: dict[int, object] = {}

    # ------------------------------------------------------------- client

    def _client(self):
        loop_id = id(asyncio.get_running_loop())
        client = self._clients.get(loop_id)
        if client is None:
            anthropic = _sdk()
            kwargs: dict = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._workspace_id:
                kwargs["default_headers"] = {"anthropic-workspace-id": self._workspace_id}
            client = anthropic.AsyncAnthropic(**kwargs)
            self._clients = {loop_id: client}  # drop clients of dead loops
        return client

    # ------------------------------------------------------------ request

    def _request(
        self,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None,
        *,
        tool_choice: str | None = None,
        eager_tools: bool = True,
    ) -> dict:
        current = _is_current(self.model)
        thinking: dict = {"type": "adaptive"}
        betas: list[str] = []
        if current:
            # Degrade instead of failing if a replayed block no longer matches
            # its prefix (a bug here should cost reasoning, not the answer).
            thinking["block_binding"] = {"prefix_mismatch_behavior": "drop_block"}
            betas.append(BETA_THINKING_BINDING)
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # One breakpoint after the system prompt: the handbook and role
            # guide inside it never change between a user's requests.
            "system": [{"type": "text", "text": system, "cache_control": _CACHE}],
            "thinking": thinking,
            "messages": self._to_anthropic_messages(messages),
        }
        if not self.model.startswith(_NO_EFFORT):
            kwargs["output_config"] = {"effort": self.effort}
        if current and self.refusal_fallback:
            kwargs["fallbacks"] = self.refusal_fallback
            betas.append(BETA_FALLBACK)
        if tools:
            specs = []
            for t in tools:
                spec = {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                if eager_tools:
                    spec["eager_input_streaming"] = True
                specs.append(spec)
            # Tools render before the system prompt in the cached prefix; a
            # breakpoint on the last one caches the whole list.
            specs[-1] = {**specs[-1], "cache_control": _CACHE}
            kwargs["tools"] = specs
            if tool_choice:
                kwargs["tool_choice"] = {"type": tool_choice}
        if betas:
            kwargs["betas"] = betas
        return kwargs

    async def generate(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        on_delta: DeltaCallback | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        anthropic = _sdk()
        kwargs = self._request(system, messages, tools, tool_choice=tool_choice)
        streamed = False

        async def forward(text: str) -> None:
            nonlocal streamed
            streamed = True
            await on_delta(text)  # type: ignore[misc]

        sink = forward if on_delta is not None else None

        async def restart() -> None:
            # A retry starts the answer over; tell the client to drop the
            # partial text it has already shown.
            if streamed and on_delta is not None:
                await on_delta(STREAM_RESET)

        try:
            resp = await self._stream(kwargs, sink)
        except ValueError as exc:
            # Eager tool-input streaming hands JSON validation to the client;
            # the SDK raises ValueError when the accumulated input does not
            # parse at all. Ask again with the server buffering the input.
            log.warning("unparseable streamed tool input (%s) — retrying buffered", exc)
            kwargs = self._request(
                system, messages, tools, tool_choice=tool_choice, eager_tools=False
            )
            await restart()
            resp = await self._stream(kwargs, sink, wrap=anthropic)
        except anthropic.BadRequestError as exc:
            if "signature" in str(exc) and "thinking" in str(exc):
                # A replayed thinking block was refused. One recovery: send the
                # turn again without any thinking blocks (always valid).
                log.warning("thinking blocks refused (%s) — retrying without them", exc)
                kwargs["messages"] = self._to_anthropic_messages(
                    messages, keep_thinking=False
                )
                await restart()
                resp = await self._stream(kwargs, sink, wrap=anthropic)
            else:
                raise GenerationError(f"anthropic: BadRequestError: {exc}") from exc
        except anthropic.APIError as exc:
            raise GenerationError(f"anthropic: {type(exc).__name__}: {exc}") from exc
        return self._parse(resp, requested_model=self.model)

    async def _stream(self, kwargs: dict, on_delta: DeltaCallback | None, wrap=None):
        """Run one streamed request and return the assembled final message."""
        client = self._client()
        try:
            async with client.beta.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    if text and on_delta is not None:
                        await on_delta(text)
                return await stream.get_final_message()
        except Exception as exc:
            if wrap is not None and isinstance(exc, wrap.APIError):
                raise GenerationError(f"anthropic: {type(exc).__name__}: {exc}") from exc
            raise

    # ------------------------------------------------------------ response

    @staticmethod
    def _parse(resp, *, requested_model: str = "") -> LLMResponse:
        usage = {
            "input_tokens": getattr(resp.usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(resp.usage, "output_tokens", 0) or 0,
        }
        for key in ("cache_read_input_tokens", "cache_creation_input_tokens"):
            value = getattr(resp.usage, key, None)
            if value:
                usage[key] = value
        served = getattr(resp, "model", "") or ""
        if served and requested_model and served != requested_model:
            # A server-side refusal fallback answered: bill the model that did.
            usage["served_by"] = served

        if resp.stop_reason == "refusal":
            return LLMResponse(text="", stop_reason="refusal", usage=usage)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}))
                )
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason or "end_turn",
            usage=usage,
            provider_blocks=_replayable(list(resp.content)),
            provider="anthropic",
        )

    # ------------------------------------------------------------ messages

    @staticmethod
    def _to_anthropic_messages(
        messages: list[ChatMessage], *, keep_thinking: bool = True
    ) -> list[dict]:
        """Map our neutral messages onto the Anthropic content-block shape.

        Tool results become ``tool_result`` blocks in a user turn, keyed by the
        originating ``tool_use_id``. Consecutive tool results are merged into
        one user turn — the API wants every result of a parallel tool call in
        a single message. An assistant tool-call turn produced by this adapter
        is replayed from its original content blocks, thinking included.
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
                if m.provider_blocks and m.provider == "anthropic":
                    blocks = [
                        b for b in m.provider_blocks
                        if keep_thinking or _block_type(b) not in ("thinking", "redacted_thinking")
                    ]
                    out.append({"role": "assistant", "content": blocks})
                    continue
                blocks: list = []
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


def _block_type(block) -> str:
    if isinstance(block, dict):
        return str(block.get("type", ""))
    return str(getattr(block, "type", ""))


# Blocks safe to echo on either side of a server-side fallback boundary.
_ECHO_BEFORE_FALLBACK = ("text", "fallback")


def _replayable(content: list) -> list:
    """The response's content as it must be sent back on the next request.

    Unchanged, except after a mid-output refusal fallback: blocks the declined
    model produced before the last ``fallback`` marker (its thinking and any
    half-made tool call) are omitted, while the marker itself stays exactly
    where it appeared — the API validates the thinking around it by position.
    """
    last = max(
        (i for i, b in enumerate(content) if _block_type(b) == "fallback"), default=-1
    )
    if last < 0:
        return content
    return [
        b for i, b in enumerate(content)
        if i >= last or _block_type(b) in _ECHO_BEFORE_FALLBACK
    ]
