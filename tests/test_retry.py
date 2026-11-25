"""Transient provider failures are retried (found on the deployed server,
whose DNS fails now and then)."""

from __future__ import annotations

import types

import httpx
import pytest

from karag.errors import GenerationError
from karag.llm.openai_embed import OpenAIEmbedder
from karag.llm.retry import post_with_retries


def _fake_httpx(script):
    """An httpx look-alike whose client plays back ``script`` (an exception
    to raise or a status to return), one entry per POST."""
    calls = []

    def handler(request):
        step = script[len(calls)]
        calls.append(request)
        if isinstance(step, Exception):
            raise step
        status, body = step
        return httpx.Response(status, json=body, headers={"retry-after": "0"} if status == 503 else {})

    class Client(httpx.AsyncClient):
        def __init__(self, **kw):
            super().__init__(transport=httpx.MockTransport(handler), **kw)

    module = types.SimpleNamespace(**{k: getattr(httpx, k) for k in dir(httpx) if not k.startswith("_")})
    module.AsyncClient = Client
    return module, calls


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr("karag.llm.retry.asyncio.sleep", instant)


async def test_dns_failure_then_busy_then_success():
    mod, calls = _fake_httpx([
        httpx.ConnectError("[Errno -3] Temporary failure in name resolution"),
        (503, {"error": "busy"}),
        (200, {"ok": True}),
    ])
    resp = await post_with_retries(mod, "https://api.example/x", json={}, headers={}, timeout=5)
    assert resp.status_code == 200 and len(calls) == 3


async def test_a_client_error_is_not_retried():
    mod, calls = _fake_httpx([(401, {"error": "bad key"}), (200, {})])
    resp = await post_with_retries(mod, "https://api.example/x", json={}, headers={}, timeout=5)
    assert resp.status_code == 401 and len(calls) == 1


async def test_embedder_reports_a_lasting_outage_as_a_generation_error(monkeypatch):
    mod, calls = _fake_httpx([httpx.ConnectError("down")] * 4)
    monkeypatch.setattr("karag.llm.openai_embed._httpx", lambda: mod)
    with pytest.raises(GenerationError, match="could not be reached"):
        await OpenAIEmbedder(api_key="k").embed(["text"])
    assert len(calls) == 4
