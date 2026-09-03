"""Free, local, real adapter backed by Ollama (https://ollama.com).

Runs entirely on your own machine — no API key, no data leaving the host, which
also happens to match KARAG's data-sovereignty story. Use this to test the full
pipeline against a real model at zero cost:

    ollama pull llama3.1        # generator (tool-capable)
    ollama pull nomic-embed-text  # embedder

``httpx`` is imported lazily so the offline test suite (which uses the fake
gateway) never needs it installed.
"""

from __future__ import annotations

from ..domain import Vector
from ..errors import GenerationError
from .base import ChatMessage, LLMResponse, MsgRole, ToolCall, ToolSpec


def _httpx():
    try:
        import httpx  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise GenerationError(
            "ollama adapter requires httpx: pip install httpx"
        ) from exc
    return httpx


class OllamaEmbedder:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        dim: int = 768,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[Vector]:
        httpx = _httpx()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
        return [list(map(float, e)) for e in data["embeddings"]]


class OllamaGenerator:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1",
        timeout: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def generate(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        on_delta=None,  # interface parity; this adapter does not stream
    ) -> LLMResponse:
        httpx = _httpx()
        payload: dict = {
            "model": self.model,
            "stream": False,
            "messages": self._to_ollama_messages(system, messages),
        }
        if tools:
            payload["tools"] = [
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
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        msg = data.get("message", {})
        tool_calls = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                import json  # noqa: PLC0415

                args = json.loads(args or "{}")
            tool_calls.append(
                ToolCall(id="", name=fn.get("name", ""), arguments=args)
            )
        return LLMResponse(
            text=msg.get("content", "") or "",
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage={
                "input_tokens": int(data.get("prompt_eval_count", 0) or 0),
                "output_tokens": int(data.get("eval_count", 0) or 0),
            },
        )

    @staticmethod
    def _to_ollama_messages(
        system: str, messages: list[ChatMessage]
    ) -> list[dict]:
        out: list[dict] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            if m.role == MsgRole.ASSISTANT and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content or "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": tc.name,
                                    "arguments": tc.arguments,
                                }
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
                continue
            role = "tool" if m.role == MsgRole.TOOL else m.role.value
            out.append({"role": role, "content": m.content})
        return out
