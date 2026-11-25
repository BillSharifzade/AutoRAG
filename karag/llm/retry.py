"""Retrying one HTTP POST to a model provider through transient failures.

Found on the deployed server: its upstream DNS fails now and then
("Temporary failure in name resolution"), and with no retry a single lookup
failure while embedding the question failed the whole answer. The Anthropic
SDK retries on its own; the plain-httpx adapters (OpenAI, Voyage) use this.

Retried: connection and DNS errors, timeouts, a dropped connection, and the
statuses that mean "try again" (408, 409, 429, 5xx) — honouring Retry-After.
Not retried: everything else (a 400 or 401 will not get better).
"""

from __future__ import annotations

import asyncio
import logging
import random

log = logging.getLogger("karag.llm.retry")

RETRY_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})


async def post_with_retries(
    httpx_module,
    url: str,
    *,
    json: dict,
    headers: dict,
    timeout: float,
    attempts: int = 4,
    base_delay: float = 0.5,
):
    """POST and return the response; raises the last error when every
    attempt failed. The caller still checks the final status."""
    transient = (
        httpx_module.ConnectError,
        httpx_module.ConnectTimeout,
        httpx_module.ReadTimeout,
        httpx_module.WriteTimeout,
        httpx_module.PoolTimeout,
        httpx_module.RemoteProtocolError,
        httpx_module.ReadError,
    )
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with httpx_module.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=json, headers=headers)
            if resp.status_code not in RETRY_STATUSES or attempt == attempts:
                return resp
            delay = _retry_after(resp) or _backoff(attempt, base_delay)
            log.warning("POST %s → %s, retrying in %.1fs (%d/%d)",
                        url, resp.status_code, delay, attempt, attempts)
        except transient as exc:
            last_exc = exc
            if attempt == attempts:
                raise
            delay = _backoff(attempt, base_delay)
            log.warning("POST %s failed (%s: %s), retrying in %.1fs (%d/%d)",
                        url, type(exc).__name__, exc, delay, attempt, attempts)
        await asyncio.sleep(delay)
    raise last_exc or RuntimeError("unreachable")  # pragma: no cover


def _backoff(attempt: int, base: float) -> float:
    return base * (2 ** (attempt - 1)) + random.uniform(0, base / 2)


def _retry_after(resp) -> float | None:
    raw = resp.headers.get("retry-after")
    try:
        return min(float(raw), 30.0) if raw else None
    except ValueError:
        return None
