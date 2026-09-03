"""Primary → fallback generator chain.

Wraps two generators; every request goes to the primary and, on any provider
failure (missing key, outage, rate limit), is retried once on the fallback.
The switch is per-request and automatic, so the platform keeps answering while
a provider is down — and starts using the primary again the moment it recovers.
"""

from __future__ import annotations

import logging

from .base import ChatMessage, DeltaCallback, Generator, LLMResponse, ToolSpec

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
    ) -> LLMResponse:
        extra = {"on_delta": on_delta} if on_delta is not None else {}
        try:
            response = await self.primary.generate(
                system=system, messages=messages, tools=tools, **extra
            )
        except Exception as exc:
            log.warning(
                "primary generator %s failed (%s: %s) — falling back to %s",
                self.primary.model, type(exc).__name__, exc, self.fallback.model,
            )
            response = await self.fallback.generate(
                system=system, messages=messages, tools=tools, **extra
            )
            response.usage.setdefault("served_by", self.fallback.model)
            return response
        response.usage.setdefault("served_by", self.primary.model)
        return response
