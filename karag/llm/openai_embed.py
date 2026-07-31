"""OpenAI embeddings adapter (production knowledge-plane index).

Default model ``text-embedding-3-large`` with a configurable ``dimensions`` (the
v3 models support truncation to a smaller dimension). Request building and
response parsing are pure functions so they can be unit-tested without a network
or an API key; only ``embed`` performs I/O (lazy ``httpx``).
"""

from __future__ import annotations

import os

from ..domain import Vector
from ..errors import ConfigError


def _httpx():
    try:
        import httpx  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("openai embedder requires httpx: pip install httpx") from exc
    return httpx


class OpenAIEmbedder:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-large",
        dim: int = 1024,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.dim = dim
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _body(self, texts: list[str]) -> dict:
        # v3 models accept `dimensions` to truncate the vector length.
        return {"model": self.model, "input": texts, "dimensions": self.dim}

    @staticmethod
    def _parse(data: dict) -> list[Vector]:
        items = sorted(data["data"], key=lambda d: d["index"])
        return [list(map(float, d["embedding"])) for d in items]

    async def embed(self, texts: list[str]) -> list[Vector]:
        if not self._api_key:
            raise ConfigError("OPENAI_API_KEY is not set")
        httpx = _httpx()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=self._body(texts),
            )
            resp.raise_for_status()
            return self._parse(resp.json())
