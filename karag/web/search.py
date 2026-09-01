"""Search providers — Brave, Tavily, Serper.

Three because they are the ones with a usable free tier, and because a company
that already pays for one should not have to switch. They normalise to the same
:class:`~karag.web.base.SearchResult`, so nothing downstream knows which is in
use. Keys come from the environment; ``httpx`` is imported lazily so the core
stays dependency-free.
"""

from __future__ import annotations

from ..errors import KaragError
from .base import SearchResult

SEARCH_TIMEOUT_S = 12.0
# More than this and the results stop being a shortlist and start being a
# context-window problem; the model can always search again with better terms.
MAX_RESULTS = 10


def _httpx():
    try:
        import httpx  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise KaragError("web search requires httpx: pip install httpx") from exc
    return httpx


class BraveSearcher:
    """Brave Search API. Key: ``BRAVE_API_KEY``."""

    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, *, timeout_s: float = SEARCH_TIMEOUT_S) -> None:
        if not api_key:
            raise KaragError("brave search requires BRAVE_API_KEY")
        self._key = api_key
        self._timeout = timeout_s

    async def search(self, query: str, *, count: int = 5) -> list[SearchResult]:
        httpx = _httpx()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                self.endpoint,
                params={"q": query, "count": min(count, MAX_RESULTS)},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self._key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", ""),
                published=r.get("age", "") or r.get("page_age", "") or "",
            )
            for r in (data.get("web", {}).get("results") or [])
            if r.get("url")
        ][:count]


class TavilySearcher:
    """Tavily, which is built for agents and returns cleaner snippets.

    Key: ``TAVILY_API_KEY``.
    """

    endpoint = "https://api.tavily.com/search"

    def __init__(self, api_key: str, *, timeout_s: float = SEARCH_TIMEOUT_S) -> None:
        if not api_key:
            raise KaragError("tavily search requires TAVILY_API_KEY")
        self._key = api_key
        self._timeout = timeout_s

    async def search(self, query: str, *, count: int = 5) -> list[SearchResult]:
        httpx = _httpx()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                self.endpoint,
                json={
                    "api_key": self._key,
                    "query": query,
                    "max_results": min(count, MAX_RESULTS),
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                published=r.get("published_date", "") or "",
            )
            for r in (data.get("results") or [])
            if r.get("url")
        ][:count]


class SerperSearcher:
    """Serper (Google results). Key: ``SERPER_API_KEY``."""

    endpoint = "https://google.serper.dev/search"

    def __init__(self, api_key: str, *, timeout_s: float = SEARCH_TIMEOUT_S) -> None:
        if not api_key:
            raise KaragError("serper search requires SERPER_API_KEY")
        self._key = api_key
        self._timeout = timeout_s

    async def search(self, query: str, *, count: int = 5) -> list[SearchResult]:
        httpx = _httpx()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                self.endpoint,
                json={"q": query, "num": min(count, MAX_RESULTS)},
                headers={"X-API-KEY": self._key, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", ""),
                published=r.get("date", "") or "",
            )
            for r in (data.get("organic") or [])
            if r.get("link")
        ][:count]
