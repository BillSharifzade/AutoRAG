"""Offline coverage of the OpenAI generator's message mapping + response parsing.

The network call needs a key, but the tool-use round-trip translation — the part
most likely to break — is pure and tested directly here.
"""

import json

from karag.llm.base import ChatMessage, MsgRole, ToolCall, ToolSpec
from karag.llm.openai_gen import OpenAIGenerator


def _map(system, messages):
    return OpenAIGenerator._to_openai_messages(system, messages)


def test_system_prompt_leads():
    out = _map("be nice", [ChatMessage(role=MsgRole.USER, content="hi")])
    assert out[0] == {"role": "system", "content": "be nice"}
    assert out[1] == {"role": "user", "content": "hi"}


def test_assistant_tool_calls_serialize_arguments_as_json_string():
    msg = ChatMessage(
        role=MsgRole.ASSISTANT,
        content="checking",
        tool_calls=[ToolCall(id="call_1", name="sales", arguments={"store_id": 5})],
    )
    out = _map("", [msg])
    tc = out[0]["tool_calls"][0]
    assert out[0]["role"] == "assistant" and out[0]["content"] == "checking"
    assert tc["id"] == "call_1" and tc["type"] == "function"
    assert tc["function"]["name"] == "sales"
    # OpenAI requires arguments to be a JSON *string*, not an object
    assert json.loads(tc["function"]["arguments"]) == {"store_id": 5}


def test_tool_result_becomes_tool_role_message():
    msg = ChatMessage(
        role=MsgRole.TOOL, content='{"total": 18450}', tool_call_id="call_1", name="sales"
    )
    out = _map("", [msg])
    assert out == [{"role": "tool", "tool_call_id": "call_1", "content": '{"total": 18450}'}]


def test_body_uses_max_completion_tokens_and_tool_schema():
    gen = OpenAIGenerator(model="gpt-5.5", api_key="x")
    body = gen._body(
        "sys",
        [ChatMessage(role=MsgRole.USER, content="hi")],
        [ToolSpec(name="sales", description="d", input_schema={"type": "object"})],
    )
    assert "max_tokens" not in body  # legacy key rejected by gpt-5.x
    assert body["max_completion_tokens"] == 4096
    assert body["tools"][0]["type"] == "function"
    assert body["tools"][0]["function"]["parameters"] == {"type": "object"}
    assert "reasoning_effort" not in body  # omitted unless configured


def test_reasoning_effort_included_when_set():
    gen = OpenAIGenerator(model="gpt-5.6-terra", api_key="x", reasoning_effort="none")
    body = gen._body("sys", [ChatMessage(role=MsgRole.USER, content="hi")], None)
    assert body["reasoning_effort"] == "none"


def test_parse_tool_call_response():
    data = {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {"content": None, "tool_calls": [
                {"id": "call_9", "type": "function",
                 "function": {"name": "sales", "arguments": '{"store_id": 5}'}}
            ]},
        }],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }
    resp = OpenAIGenerator._parse(data)
    assert resp.stop_reason == "tool_use"
    assert resp.tool_calls[0].name == "sales"
    assert resp.tool_calls[0].arguments == {"store_id": 5}
    assert resp.usage == {"input_tokens": 12, "output_tokens": 3}


def test_parse_text_and_content_filter():
    text = OpenAIGenerator._parse(
        {"choices": [{"finish_reason": "stop", "message": {"content": "hello"}}]}
    )
    assert text.stop_reason == "end_turn" and text.text == "hello"
    blocked = OpenAIGenerator._parse(
        {"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]}
    )
    assert blocked.stop_reason == "refusal"


def test_user_images_become_content_parts():
    from karag.llm.base import ImagePart

    msgs = _map("sys", [
        ChatMessage(
            role=MsgRole.USER,
            content="what is this?",
            images=[ImagePart(media_type="image/png", data_b64="QUJD")],
        )
    ])
    user = msgs[1]
    assert user["role"] == "user"
    assert user["content"][0] == {"type": "text", "text": "what is this?"}
    assert user["content"][1]["type"] == "image_url"
    assert user["content"][1]["image_url"]["url"] == "data:image/png;base64,QUJD"
