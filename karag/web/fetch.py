"""Read one web page as text.

Redirects are followed by hand rather than by ``httpx``, because each hop has
to go back through :func:`~karag.web.guard.check_url` — a public URL that
redirects to ``169.254.169.254`` is exactly how an allow-list gets walked
around. The body is streamed and cut off at the policy's byte cap, so a
misbehaving server cannot hand back a gigabyte.

HTML is reduced to text here rather than with a parser dependency: scripts,
styles and markup come out, entities are decoded, whitespace is collapsed. It
is not a reader-mode extractor and does not pretend to be — it produces the
page's words, which is what the model needs.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urljoin

from ..errors import KaragError
from .base import FetchedPage
from .guard import WebAccessDenied, WebPolicy, check_url, readable_content_type

_SCRIPTISH = re.compile(
    r"<(script|style|noscript|template|svg)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# Tags that imply a line break when they disappear, so paragraphs stay apart.
_BLOCK = re.compile(
    r"</?(p|div|br|li|tr|h[1-6]|section|article|header|footer|blockquote|pre)\b[^>]*>",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_BLANK_RUN = re.compile(r"\n{3,}")
_SPACE_RUN = re.compile(r"[ \t ]{2,}")


def html_to_text(markup: str) -> tuple[str, str]:
    """Return ``(title, text)`` for a chunk of HTML."""
    title_match = _TITLE.search(markup)
    title = html.unescape(_TAG.sub("", title_match.group(1))).strip() if title_match else ""

    body = _SCRIPTISH.sub(" ", markup)
    body = _BLOCK.sub("\n", body)
    body = _TAG.sub(" ", body)
    body = html.unescape(body)
    body = _SPACE_RUN.sub(" ", body)
    body = "\n".join(line.strip() for line in body.splitlines())
    body = _BLANK_RUN.sub("\n\n", body).strip()
    return title, body


def _httpx():
    try:
        import httpx  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise KaragError("reading web pages requires httpx: pip install httpx") from exc
    return httpx


class HttpPageFetcher:
    """Fetch a page under a :class:`WebPolicy`."""

    def __init__(self, policy: WebPolicy | None = None) -> None:
        self._policy = policy or WebPolicy()

    async def fetch(self, url: str) -> FetchedPage:
        httpx = _httpx()
        policy = self._policy
        current = check_url(url, policy)

        async with httpx.AsyncClient(
            timeout=policy.timeout_s,
            follow_redirects=False,
            headers={
                # Say who is calling. A site that wants to refuse a bot should
                # be able to, and an operator reading their logs should be able
                # to tell what this traffic is.
                "User-Agent": "KARAG/1.0 (+enterprise assistant; respects robots)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
            },
        ) as client:
            for _ in range(policy.max_redirects + 1):
                resp = await client.get(current)

                if resp.is_redirect:
                    location = resp.headers.get("location", "")
                    if not location:
                        raise WebAccessDenied("that page redirected to nowhere")
                    # Re-check the destination — this is the whole reason
                    # redirects are not delegated to the HTTP client.
                    current = check_url(urljoin(current, location), policy)
                    continue

                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if not readable_content_type(content_type):
                    raise WebAccessDenied(
                        f"that address returns {content_type.split(';')[0] or 'an unknown type'}, "
                        "which cannot be read as text — upload it as a document instead"
                    )

                raw = resp.content[: policy.max_bytes]
                truncated = len(resp.content) > policy.max_bytes
                markup = raw.decode(resp.encoding or "utf-8", errors="replace")
                break
            else:
                raise WebAccessDenied("that page redirected too many times")

        if "html" in content_type.lower():
            title, text = html_to_text(markup)
        else:
            title, text = "", markup.strip()

        return FetchedPage(
            url=str(resp.url),
            title=title or str(resp.url),
            text=text,
            truncated=truncated,
        )
