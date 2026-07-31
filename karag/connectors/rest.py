"""Read-only REST connector — the "expose a limited API" data path.

Only GET requests to a fixed base URL are allowed; the company's own API returns
ready business objects, so the platform never touches its database. Auth headers
are injected server-side and never seen by the model. Lazy ``httpx``.
"""

from __future__ import annotations

from ..errors import KaragError


def _httpx():
    try:
        import httpx  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise KaragError("rest connector requires httpx: pip install httpx") from exc
    return httpx


class RestConnector:
    def __init__(
        self,
        base_url: str,
        *,
        headers: dict | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self.timeout_s = timeout_s

    async def get(self, path: str, params: dict | None = None) -> object:
        httpx = _httpx()
        if "://" in path:
            raise KaragError("path must be relative to the connector base_url")
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.get(
                f"{self.base_url}/{path.lstrip('/')}",
                params=params or {},
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()
