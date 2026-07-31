"""Offline coverage of the Claude adapter's message translation.

The network call needs the SDK + a key, but the message mapping — the part most
likely to break the real tool-use round-trip — is a pure function we can test
directly. This guards the assistant tool_use / user tool_result pairing that the
Anthropic API requires.
"""

from karag.llm.anthropic_adapter import AnthropicGenerator
from karag.llm.base import ChatMessage, MsgRole, ToolCall


def _map(messages):
    return AnthropicGenerator._to_anthropic_messages(messages)


def test_plain_user_and_assistant():
    out = _map([
        ChatMessage(role=MsgRole.USER, content="hi"),
        ChatMessage(role=MsgRole.ASSISTANT, content="hello"),
    ])
    assert out == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_assistant_tool_calls_become_tool_use_blocks():
    msg = ChatMessage(
        role=MsgRole.ASSISTANT,
        content="let me check",
        tool_calls=[ToolCall(id="tu_1", name="sales", arguments={"store_id": 5})],
    )
    out = _map([msg])
    blocks = out[0]["content"]
    assert out[0]["role"] == "assistant"
    assert blocks[0] == {"type": "text", "text": "let me check"}
    assert blocks[1] == {
        "type": "tool_use",
        "id": "tu_1",
        "name": "sales",
        "input": {"store_id": 5},
    }


def test_tool_result_pairs_by_id():
    msg = ChatMessage(
        role=MsgRole.TOOL, content='{"total": 18450}', tool_call_id="tu_1", name="sales"
    )
    out = _map([msg])
    assert out == [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": '{"total": 18450}'}
            ],
        }
    ]


def test_full_roundtrip_shape():
    # user -> assistant(tool_use) -> tool_result: valid Anthropic ordering
    seq = [
        ChatMessage(role=MsgRole.USER, content="sales for store 5"),
        ChatMessage(
            role=MsgRole.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="tu_1", name="sales", arguments={"store_id": 5})],
        ),
        ChatMessage(role=MsgRole.TOOL, content="18450", tool_call_id="tu_1"),
    ]
    out = _map(seq)
    assert out[0]["role"] == "user"
    assert out[1]["role"] == "assistant"
    assert any(b["type"] == "tool_use" for b in out[1]["content"])
    assert out[2]["content"][0]["type"] == "tool_result"
    assert out[2]["content"][0]["tool_use_id"] == "tu_1"


def test_user_images_become_image_blocks():
    from karag.llm.base import ImagePart

    msgs = _map([
        ChatMessage(
            role=MsgRole.USER,
            content="what is this?",
            images=[ImagePart(media_type="image/jpeg", data_b64="QUJD")],
        )
    ])
    blocks = msgs[0]["content"]
    assert blocks[0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"},
    }
    assert blocks[-1] == {"type": "text", "text": "what is this?"}
