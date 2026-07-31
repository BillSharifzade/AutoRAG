"""Production embedders: request building + response parsing (offline)."""

import pytest

from karag.errors import ConfigError
from karag.llm.openai_embed import OpenAIEmbedder
from karag.llm.voyage_embed import VoyageEmbedder


def test_openai_body_and_parse():
    e = OpenAIEmbedder(api_key="k", model="text-embedding-3-large", dim=1024)
    body = e._body(["a", "b"])
    assert body == {"model": "text-embedding-3-large", "input": ["a", "b"], "dimensions": 1024}
    # response items may arrive out of order — parse must sort by index
    parsed = e._parse(
        {"data": [
            {"index": 1, "embedding": [0.3, 0.4]},
            {"index": 0, "embedding": [0.1, 0.2]},
        ]}
    )
    assert parsed == [[0.1, 0.2], [0.3, 0.4]]


def test_voyage_body_and_parse():
    e = VoyageEmbedder(api_key="k", model="voyage-3", dim=1024)
    body = e._body(["x"])
    assert body == {"model": "voyage-3", "input": ["x"], "input_type": "document"}
    assert e._parse({"data": [{"index": 0, "embedding": [1.0]}]}) == [[1.0]]


async def test_missing_key_fails_closed(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        await OpenAIEmbedder(api_key=None).embed(["x"])
    with pytest.raises(ConfigError):
        await VoyageEmbedder(api_key=None).embed(["x"])
