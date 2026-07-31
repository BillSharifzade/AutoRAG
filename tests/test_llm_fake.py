"""The deterministic fake gateway: embeddings and generation policy."""

import pytest

from karag.llm.base import ChatMessage, MsgRole, ToolSpec
from karag.llm.fake import FakeGenerator, HashingEmbedder



async def test_embeddings_are_deterministic():
    e = HashingEmbedder(dim=128)
    a = (await e.embed(["hello world"]))[0]
    b = (await e.embed(["hello world"]))[0]
    assert a == b
    assert len(a) == 128


async def test_shared_words_raise_similarity():
    from karag.vectorstore.memory import cosine

    e = HashingEmbedder(dim=256)
    q, near, far = await e.embed(
        [
            "financial revenue and profit report",
            "quarterly revenue and profit figures",
            "warehouse forklift maintenance schedule",
        ]
    )
    assert cosine(q, near) > cosine(q, far)


async def test_generator_knowledge_grounding():
    g = FakeGenerator()
    msg = ChatMessage(role=MsgRole.USER, content="Question: policy?\n[1] refunds within 14 days")
    resp = await g.generate(system="s", messages=[msg])
    assert resp.stop_reason == "end_turn"
    assert "refunds within 14 days" in resp.text


async def test_generator_emits_tool_call_on_kv():
    g = FakeGenerator()
    tool = ToolSpec(
        name="sales_by_store",
        description="sales",
        input_schema={
            "type": "object",
            "properties": {"store_id": {"type": "integer"}, "date": {"type": "string"}},
            "required": ["store_id", "date"],
        },
    )
    msg = ChatMessage(role=MsgRole.USER, content="sales store_id=5 date=2026-07-20")
    resp = await g.generate(system="s", messages=[msg], tools=[tool])
    assert resp.stop_reason == "tool_use"
    call = resp.tool_calls[0]
    assert call.name == "sales_by_store"
    assert call.arguments == {"store_id": 5, "date": "2026-07-20"}  # int coerced


async def test_generator_summarises_tool_result():
    g = FakeGenerator()
    messages = [
        ChatMessage(role=MsgRole.USER, content="sales store_id=5 date=2026-07-20"),
        ChatMessage(role=MsgRole.TOOL, content='{"total": 18450}', name="sales_by_store"),
    ]
    resp = await g.generate(system="s", messages=messages, tools=[])
    assert resp.stop_reason == "end_turn"
    assert "18450" in resp.text
