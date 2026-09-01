"""Web search and page reading, behind protocols.

Same shape as :mod:`karag.llm.base`: the platform depends on ``WebSearcher``
and ``PageFetcher``, never on Brave or Tavily, so the search vendor is a
configuration choice and the offline test suite runs with a deterministic fake.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SearchResult:
    """One hit. ``url`` is what makes the claim checkable, so it is required."""

    title: str
    url: str
    snippet: str = ""
    # ISO date when the provider reports one; "" when it does not
    published: str = ""

    def to_dict(self) -> dict:
        d = {"title": self.title, "url": self.url, "snippet": self.snippet}
        if self.published:
            d["published"] = self.published
        return d


@dataclass(frozen=True)
class FetchedPage:
    url: str  # the *final* URL, after any redirects
    title: str
    text: str
    truncated: bool = False


class WebSearcher(Protocol):
    async def search(self, query: str, *, count: int = 5) -> list[SearchResult]: ...


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> FetchedPage: ...


@dataclass
class FakeSearcher:
    """Deterministic results for tests — no network, no key, stable output."""

    results: list[SearchResult] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)

    async def search(self, query: str, *, count: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        if self.results:
            return self.results[:count]
        return [
            SearchResult(
                title=f"Result {i + 1} for {query}",
                url=f"https://example.com/{i + 1}",
                snippet=f"A passage about {query}.",
            )
            for i in range(min(count, 3))
        ]


@dataclass
class FakeFetcher:
    pages: dict[str, FetchedPage] = field(default_factory=dict)
    fetched: list[str] = field(default_factory=list)

    async def fetch(self, url: str) -> FetchedPage:
        self.fetched.append(url)
        if url in self.pages:
            return self.pages[url]
        return FetchedPage(url=url, title="Example page", text=f"Contents of {url}.")
