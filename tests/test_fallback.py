"""Primary → fallback generator chain."""

import pytest

from karag.config import Settings
from karag.factory import build_generator
from karag.llm.base import LLMResponse
from karag.llm.fallback import FallbackGenerator


class _Ok:
    model = "ok-model"

    async def generate(self, *, system, messages, tools=None):
        return LLMResponse(text="primary answer")


class _Boom:
    model = "boom-model"

    async def generate(self, *, system, messages, tools=None):
        raise RuntimeError("provider down")


async def test_primary_wins_when_healthy():
    gen = FallbackGenerator(_Ok(), _Boom())
    r = await gen.generate(system="s", messages=[])
    assert r.text == "primary answer"
    assert r.usage["served_by"] == "ok-model"


async def test_falls_back_on_primary_failure():
    gen = FallbackGenerator(_Boom(), _Ok())
    r = await gen.generate(system="s", messages=[])
    assert r.text == "primary answer"
    assert r.usage["served_by"] == "ok-model"


async def test_raises_when_both_fail():
    gen = FallbackGenerator(_Boom(), _Boom())
    with pytest.raises(RuntimeError):
        await gen.generate(system="s", messages=[])


def test_model_names_both_providers():
    gen = FallbackGenerator(_Ok(), _Boom())
    assert gen.model == "ok-model (fallback: boom-model)"


def test_factory_wraps_when_fallback_configured():
    s = Settings(generator="fake", fallback_generator="ollama")
    gen = build_generator(s)
    assert isinstance(gen, FallbackGenerator)


def test_factory_skips_wrap_when_same_or_unset():
    assert not isinstance(build_generator(Settings(generator="fake")), FallbackGenerator)
    assert not isinstance(
        build_generator(Settings(generator="fake", fallback_generator="fake")),
        FallbackGenerator,
    )
