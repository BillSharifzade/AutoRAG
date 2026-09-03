"""Read-only REST connector — the "expose a limited API" data path.

Only GET requests to a fixed base URL are allowed; the company's own API returns
ready business objects, so the platform never touches its database. Auth headers
are injected server-side and never seen by the model. Lazy ``httpx``.

The base URL is checked by the same guard that protects web fetching: a
connector may not point at the loopback interface, a private range or a cloud
metadata endpoint. A skill author is trusted with company data, not with the
platform's own network. An operator who really runs the API on a private
address opts in with ``allow_private: true`` in the connector config.
"""

from __future__ import annotations

from ..errors import KaragError
from ..web.guard import WebAccessDenied, WebPolicy, check_url


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
        allow_private: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self.timeout_s = timeout_s
        self._policy = WebPolicy(allow_private_addresses=allow_private)

    def check(self) -> None:
        """Refuse a base URL inside the perimeter (scheme, host, resolved IPs)."""
        try:
            check_url(self.base_url, self._policy)
        except WebAccessDenied as exc:
            raise KaragError(f"connector base_url refused: {exc}") from exc

    async def get(self, path: str, params: dict | None = None) -> object:
        httpx = _httpx()
        if "://" in path:
            raise KaragError("path must be relative to the connector base_url")
        if path.startswith("//") or ".." in path.split("?", 1)[0]:
            raise KaragError("path may not leave the connector base_url")
        # Re-checked on every call: DNS can change after the connector was made.
        self.check()
        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=False) as client:
            resp = await client.get(
                f"{self.base_url}/{path.lstrip('/')}",
                params=params or {},
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()
