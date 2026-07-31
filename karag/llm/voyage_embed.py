"""Voyage AI embeddings adapter — Anthropic's recommended pairing for Claude.

``voyage-3`` (1024-dim) is multilingual, which matters for the RU/TJ corpus in
KARAG. Request building / response parsing are pure and unit-testable; only
``embed`` does I/O.
"""

from __future__ import annotations

import os

from ..domain import Vector
from ..errors import ConfigError


def _httpx():
    try:
        import httpx  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("voyage embedder requires httpx: pip install httpx") from exc
    return httpx


class VoyageEmbedder:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "voyage-3",
        dim: int = 1024,
        base_url: str = "https://api.voyageai.com/v1",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("VOYAGE_API_KEY")
        self.model = model
        self.dim = dim
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _body(self, texts: list[str], *, input_type: str = "document") -> dict:
        return {"model": self.model, "input": texts, "input_type": input_type}

    @staticmethod
    def _parse(data: dict) -> list[Vector]:
        items = sorted(data["data"], key=lambda d: d["index"])
        return [list(map(float, d["embedding"])) for d in items]

    async def embed(self, texts: list[str]) -> list[Vector]:
        if not self._api_key:
            raise ConfigError("VOYAGE_API_KEY is not set")
        httpx = _httpx()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=self._body(texts),
            )
            resp.raise_for_status()
            return self._parse(resp.json())
