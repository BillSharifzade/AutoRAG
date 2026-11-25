"""Primary → fallback generator chain.

Wraps two generators; every request goes to the primary and, on any provider
failure (missing key, outage, rate limit), is retried once on the fallback.
The switch is per-request and automatic, so the platform keeps answering while
a provider is down — and starts using the primary again the moment it recovers.
Longer chains are nested pairs: ``chain([a, b, c])`` is ``a → (b → c)``.

If the primary had already streamed part of an answer before failing, the
client is told to discard it (:data:`STREAM_RESET`) before the fallback starts
over — otherwise the reader would see two answers glued together.
"""

from __future__ import annotations

import logging

from .base import STREAM_RESET, ChatMessage, DeltaCallback, Generator, LLMResponse, ToolSpec

log = logging.getLogger("karag.llm.fallback")


class FallbackGenerator:
    def __init__(self, primary: Generator, fallback: Generator) -> None:
        self.primary = primary
        self.fallback = fallback

    @property
    def model(self) -> str:
        return f"{self.primary.model} (fallback: {self.fallback.model})"

    async def generate(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        on_delta: DeltaCallback | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        streamed = False

        async def forward(text: str) -> None:
            nonlocal streamed
            if text != STREAM_RESET:
                streamed = True
            await on_delta(text)  # type: ignore[misc]

        extra: dict = {}
        if on_delta is not None:
            extra["on_delta"] = forward
        if tool_choice is not None:
            extra["tool_choice"] = tool_choice
        try:
            response = await self.primary.generate(
                system=system, messages=messages, tools=tools, **extra
            )
        except Exception as exc:
            log.warning(
                "primary generator %s failed (%s: %s) — falling back to %s",
                self.primary.model, type(exc).__name__, exc, self.fallback.model,
            )
            if streamed and on_delta is not None:
                await on_delta(STREAM_RESET)
            fallback_extra: dict = {}
            if on_delta is not None:
                fallback_extra["on_delta"] = on_delta
            if tool_choice is not None:
                fallback_extra["tool_choice"] = tool_choice
            response = await self.fallback.generate(
                system=system, messages=messages, tools=tools, **fallback_extra
            )
            response.usage.setdefault("served_by", _served(self.fallback))
            return response
        response.usage.setdefault("served_by", _served(self.primary))
        return response


def _served(generator: Generator) -> str:
    """The model to bill: a nested chain reports its own first link."""
    inner = getattr(generator, "primary", None)
    return _served(inner) if inner is not None else generator.model


def chain(generators: list[Generator]) -> Generator:
    """``[a, b, c]`` → ``a`` falling back to ``b`` falling back to ``c``."""
    if not generators:
        raise ValueError("chain() needs at least one generator")
    result = generators[-1]
    for gen in reversed(generators[:-1]):
        result = FallbackGenerator(gen, result)
    return result
