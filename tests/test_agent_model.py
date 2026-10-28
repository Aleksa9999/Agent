import json

import httpx
import pytest

from app.agent.model import (
    ModelError,
    QwenResponsesClient,
    ToolConflictError,
    _sse_event,
    build_payload,
    parse_response,
)
from app.agent.types import (
    Completed,
    FunctionSpec,
    Message,
    ModelRequest,
    TextDelta,
    ToolCall,
    ToolCallEvent,
)

FAKE_KEY = "sk-" + "fake" * 6  # built at runtime: never a literal that looks like a key
FN = FunctionSpec("ask_options", "d", {"type": "object", "properties": {}})


def _req(mode="mentor", **kw):
    return ModelRequest(mode=mode, instructions="rules", messages=[Message("user", "hi")], **kw)


def test_mentor_payload_has_custom_functions_only():
    payload = build_payload(_req(functions=(FN,)), model_id="m1")
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "ask_options",
            "description": "d",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    assert payload["model"] == "m1" and payload["enable_thinking"] is True


def test_research_payload_has_builtin_tools_only():
    payload = build_payload(
        _req("research", builtin_tools=("web_search", "web_extractor")), model_id="m"
    )
    assert payload["tools"] == [{"type": "web_search"}, {"type": "web_extractor"}]


def test_builtin_tools_and_functions_can_never_share_a_request():
    with pytest.raises(ToolConflictError):
        build_payload(_req(functions=(FN,), builtin_tools=("code_interpreter",)), model_id="m")
    with pytest.raises(ValueError):
        build_payload(_req("research", builtin_tools=("shell",)), model_id="m")


def test_summary_runs_without_thinking_and_tool_results_map_to_call_outputs():
    messages = [
        Message("user", "q"),
        Message("assistant", "", (ToolCall("c9", "run_research", {"query": "x"}),)),
        Message("tool", "answer", tool_call_id="c9"),
    ]
    payload = build_payload(ModelRequest("summary", "s", messages), model_id="fast")
    assert payload["enable_thinking"] is False and "tools" not in payload
    assert payload["input"][1]["type"] == "function_call" and payload["input"][1]["call_id"] == "c9"
    assert payload["input"][2] == {
        "type": "function_call_output",
        "call_id": "c9",
        "output": "answer",
    }


RESPONSE = {
    "output": [
        {"type": "reasoning"},
        {"type": "web_search_call", "action": {"query": "q"}},
        {"type": "code_interpreter_call", "code": "print(1+1)"},
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": "Hello",
                    "annotations": [
                        {"type": "url_citation", "url": "https://a.test", "title": "A"},
                        {"type": "url_citation", "url": "https://a.test", "title": "A again"},
                    ],
                }
            ],
        },
        {"type": "function_call", "call_id": "k1", "name": "ask_options", "arguments": '{"x": 1}'},
    ],
    "usage": {"input_tokens": 10, "output_tokens": 4, "input_tokens_details": {"cached_tokens": 6}},
}


def test_response_is_parsed_into_text_citations_calls_code_and_usage():
    result = parse_response(RESPONSE)
    assert result.text == "Hello"
    assert [c.url for c in result.citations] == ["https://a.test"]  # duplicates removed
    assert result.tool_calls == [ToolCall("k1", "ask_options", {"x": 1})]
    assert result.code_blocks == ["print(1+1)"]
    assert (result.usage.input_tokens, result.usage.cached_tokens) == (10, 6)


def test_stream_events_are_recognised_and_noise_is_ignored():
    assert _sse_event('data: {"type":"response.output_text.delta","delta":"Hi"}') == TextDelta("Hi")
    done = _sse_event(
        'data: {"type":"response.output_item.done","item":{"type":"function_call",'
        '"call_id":"c","name":"n","arguments":"{}"}}'
    )
    assert isinstance(done, ToolCallEvent) and done.call.name == "n"
    assert isinstance(_sse_event('data: {"type":"response.completed","response":{}}'), Completed)
    for noise in ("", "event: x", "data: [DONE]", "data: not json", 'data: {"type":"other"}'):
        assert _sse_event(noise) is None


def _client(handler) -> QwenResponsesClient:
    return QwenResponsesClient(
        base_url="https://models.example.test/v1/",
        api_key=FAKE_KEY,
        model="big",
        fast_model="small",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_client_posts_to_responses_with_a_bearer_key_and_the_right_model():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=RESPONSE)

    client = _client(handler)
    result = await client.complete(_req("summary"))
    assert seen["url"] == "https://models.example.test/v1/responses"
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert seen["body"]["model"] == "small" and seen["body"]["stream"] is False
    assert result.text == "Hello"
    await client.complete(_req("mentor", functions=(FN,)))
    assert seen["body"]["model"] == "big"


async def test_client_errors_never_contain_the_key():
    client = _client(lambda request: httpx.Response(500, text=f"boom {FAKE_KEY}"))
    with pytest.raises(ModelError) as caught:
        await client.complete(_req())
    assert FAKE_KEY not in str(caught.value) and "500" in str(caught.value)

    def refuse(request):
        raise httpx.ConnectError(f"no route to host {FAKE_KEY}")

    with pytest.raises(ModelError) as caught:
        await _client(refuse).complete(_req())
    assert FAKE_KEY not in str(caught.value)


async def test_a_refusal_carries_the_provider_code_but_never_a_key():
    body = {"error": {"code": "invalid_parameter_error", "message": f"bad field, key {FAKE_KEY}"}}
    client = _client(lambda request: httpx.Response(400, json=body))
    with pytest.raises(ModelError) as caught:
        await client.complete(_req())
    assert "HTTP 400" in str(caught.value) and "invalid_parameter_error" in str(caught.value)
    assert FAKE_KEY not in str(caught.value)
    with pytest.raises(ModelError) as caught:  # the same for a streamed request
        async for _ in client.stream(_req()):
            pass
    assert "invalid_parameter_error" in str(caught.value)
    odd = _client(lambda request: httpx.Response(502, text="<html>gateway</html>"))
    with pytest.raises(ModelError) as caught:
        await odd.complete(_req())
    assert str(caught.value) == "model returned HTTP 502"


async def test_client_streams_server_sent_events():
    body = (
        'data: {"type":"response.output_text.delta","delta":"A"}\n\n'
        'data: {"type":"response.output_text.delta","delta":"B"}\n\n'
        'data: {"type":"response.completed","response":{"output":[]}}\n\n'
    )
    client = _client(lambda request: httpx.Response(200, text=body))
    events = [e async for e in client.stream(_req())]
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["A", "B"]
    assert isinstance(events[-1], Completed)
