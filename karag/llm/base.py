"""Provider-agnostic LLM interfaces.

Two capabilities, kept separate on purpose:

  * ``Generator`` — produces text and may request tool calls (the data plane).
  * ``Embedder``  — turns text into vectors (the knowledge plane's index).

Claude has no first-party embeddings endpoint, so a real deployment pairs the
Anthropic generator with a separate embedder (Ollama / Voyage / OpenAI). The
``Gateway`` composes one of each; application code only ever depends on these
protocols, never on a concrete provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Protocol, runtime_checkable

from ..domain import Vector

# Called with each piece of answer text as the provider produces it. Adapters
# that cannot stream simply never call it; the caller must not depend on it
# having been called to learn the final text — that always comes from the
# returned :class:`LLMResponse`.
DeltaCallback = Callable[[str], Awaitable[None]]


class MsgRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ImagePart:
    """An inline image attached to a user message (base64, no data URL prefix)."""

    media_type: str  # image/png | image/jpeg | image/webp | image/gif
    data_b64: str


@dataclass
class ChatMessage:
    role: MsgRole
    content: str
    # populated only for role == TOOL:
    tool_call_id: str | None = None
    name: str | None = None
    # populated only for role == ASSISTANT that requested tools — needed so the
    # real provider can pair each tool_result with its originating tool_use.
    tool_calls: list["ToolCall"] | None = None
    # populated only for role == USER with image attachments; adapters that
    # cannot send images simply ignore them.
    images: list[ImagePart] | None = None


@dataclass
class ToolSpec:
    """A tool (skill) offered to the generator, as JSON-schema."""

    name: str
    description: str
    input_schema: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # end_turn | tool_use | refusal | max_tokens
    usage: dict = field(default_factory=dict)


@runtime_checkable
class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[Vector]: ...


@runtime_checkable
class Generator(Protocol):
    model: str

    async def generate(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> LLMResponse: ...


@dataclass
class Gateway:
    """Composes a generator and an embedder into a single dependency."""

    generator: Generator
    embedder: Embedder

    @property
    def model(self) -> str:
        return self.generator.model

    @property
    def dim(self) -> int:
        return self.embedder.dim

    async def embed(self, texts: list[str]) -> list[Vector]:
        return await self.embedder.embed(texts)

    async def generate(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> LLMResponse:
        extra = {"on_delta": on_delta} if on_delta is not None else {}
        return await self.generator.generate(
            system=system, messages=messages, tools=tools, **extra
        )
