"""Deterministic, offline generator + embedder for tests and local demos.

No network, no model weights, fully reproducible. It is good enough to exercise
*every plane of the system end to end*:

  * ``HashingEmbedder`` maps text to a fixed-dim vector via a signed hashing
    trick. Shared tokens raise cosine similarity, so retrieval ranking is
    meaningful (documents about the same topic really do score higher).

  * ``FakeGenerator`` implements a small, documented, deterministic policy:
      - If the last message is a TOOL result, it summarises that result and
        stops (terminating the agentic loop).
      - Else, if the query contains ``key=value`` tokens AND a tool's schema
        matches those keys, it emits a tool call (the data plane).
      - Otherwise it answers from the ``[n]`` context lines it was given,
        grounded in the retrieved passages (the knowledge plane).

The real Anthropic/Ollama generators extract arguments from natural language;
the fake uses the explicit ``key=value`` contract only so tests are exact.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass

from ..domain import Vector, new_id
from .base import ChatMessage, LLMResponse, MsgRole, ToolCall, ToolSpec

_WORD = re.compile(r"[a-z0-9_]+")
_KV = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)=([^\s]+)")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


@dataclass
class HashingEmbedder:
    dim: int = 256

    async def embed(self, texts: list[str]) -> list[Vector]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> Vector:
        v = [0.0] * self.dim
        for tok in _tokens(text):
            h = int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h // self.dim) % 2 == 0 else -1.0
            v[idx] += sign
        norm = math.sqrt(sum(x * x for x in v))
        if norm > 0.0:
            v = [x / norm for x in v]
        return v


class FakeGenerator:
    model = "fake-deterministic"

    async def generate(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        # 1. If we just received a tool result, produce the final answer.
        if messages and messages[-1].role == MsgRole.TOOL:
            payloads = [m.content for m in messages if m.role == MsgRole.TOOL]
            joined = " | ".join(payloads)
            return LLMResponse(
                text=f"Based on the retrieved data: {joined}",
                stop_reason="end_turn",
            )

        last_user = next(
            (m.content for m in reversed(messages) if m.role == MsgRole.USER),
            "",
        )

        # 2. Data-plane intent is signalled by explicit key=value pairs.
        kv = {k: v for k, v in _KV.findall(last_user)}
        if kv and tools:
            chosen = self._pick_tool(tools, kv)
            if chosen is not None:
                args = self._coerce_args(chosen, kv)
                return LLMResponse(
                    tool_calls=[ToolCall(new_id("call"), chosen.name, args)],
                    stop_reason="tool_use",
                )

        # 3. Knowledge plane: ground the answer in the provided [n] context.
        passages = self._context_lines(messages)
        if passages:
            body = " ".join(passages)
            return LLMResponse(
                text=f"According to the sources: {body}",
                stop_reason="end_turn",
            )
        return LLMResponse(
            text="I don't have information I'm permitted to share on that.",
            stop_reason="end_turn",
        )

    @staticmethod
    def _pick_tool(tools: list[ToolSpec], kv: dict) -> ToolSpec | None:
        """Pick the tool whose schema properties best match the kv keys."""
        best: ToolSpec | None = None
        best_score = 0
        for t in tools:
            props = set(t.input_schema.get("properties", {}))
            score = len(props & set(kv))
            if score > best_score:
                best_score, best = score, t
        return best

    @staticmethod
    def _coerce_args(tool: ToolSpec, kv: dict) -> dict:
        props = tool.input_schema.get("properties", {})
        out: dict = {}
        for key, raw in kv.items():
            if key not in props:
                continue
            typ = props[key].get("type")
            if typ == "integer":
                try:
                    out[key] = int(raw)
                except ValueError:
                    out[key] = raw
            elif typ == "number":
                try:
                    out[key] = float(raw)
                except ValueError:
                    out[key] = raw
            elif typ == "boolean":
                out[key] = raw.lower() in ("true", "1", "yes")
            else:
                out[key] = raw
        return out

    @staticmethod
    def _context_lines(messages: list[ChatMessage]) -> list[str]:
        lines: list[str] = []
        for m in messages:
            for ln in m.content.splitlines():
                mo = re.match(r"\s*\[\d+\]\s*(.+)", ln)
                if mo:
                    lines.append(mo.group(1).strip())
        return lines


def build_fake_gateway(dim: int = 256):
    """Convenience: a Gateway wired to the fake generator + embedder."""
    from .base import Gateway

    return Gateway(generator=FakeGenerator(), embedder=HashingEmbedder(dim=dim))
