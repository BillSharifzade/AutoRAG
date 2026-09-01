"""Reaching the public internet, under a policy.

The rest of KARAG points inward — the company's documents, the company's
databases. This package is the one part that points outward, so it is also the
one part with a guard in front of it (:mod:`karag.web.guard`) and a rule that
everything it brings back is untrusted evidence carrying a citation.
"""

from .base import FetchedPage, PageFetcher, SearchResult, WebSearcher
from .guard import WebAccessDenied, WebPolicy
from .skills import web_skills

__all__ = [
    "FetchedPage",
    "PageFetcher",
    "SearchResult",
    "WebAccessDenied",
    "WebPolicy",
    "WebSearcher",
    "web_skills",
]
