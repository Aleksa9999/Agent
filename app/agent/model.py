"""The model port and the Qwen adapter (OpenAI-compatible Responses API of Model Studio).

Rules that the adapter enforces by construction:
  * built-in tools (web_search, web_extractor, code_interpreter) and our own functions are never
    sent in one request: the API rejects that combination, so each mode uses one kind only;
  * model IDs come from settings, never from code.

The wire format follows the Model Studio documentation (POST {base}/responses, `tools`,
`enable_thinking`, output items `message`, `function_call`, `web_search_call`, ...). It has been
checked against recorded payloads only; the first call with a real key happens at gate 1.
"""

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from app.agent.types import (
    Citation,
    Completed,
    Message,
    ModelRequest,
    ModelResult,
    StreamEvent,
    TextDelta,
    ToolCall,
    ToolCallEvent,
    Usage,
)

log = logging.getLogger("app.agent")

BUILTIN_TOOLS = frozenset({"web_search", "web_extractor", "code_interpreter"})


class ModelError(Exception):
    """A failed model call. The message never contains keys or request bodies."""


class ToolConflictError(ValueError):
    """Built-in tools and custom functions were requested together."""


class ModelPort(Protocol):
    async def complete(self, request: ModelRequest) -> ModelResult: ...

    def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]: ...


def _input_items(messages: list[Message]) -> list[dict]:
    items: list[dict] = []
    for m in messages:
        if m.role == "tool":
            items.append(
                {"type": "function_call_output", "call_id": m.tool_call_id, "output": m.content}
            )
            continue
        if m.content:
            items.append({"role": m.role, "content": m.content})
        for call in m.tool_calls:
            items.append(
                {
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                }
            )
    return items


def build_payload(request: ModelRequest, *, model_id: str) -> dict:
    if request.functions and request.builtin_tools:
        raise ToolConflictError("built-in tools and custom functions cannot share one request")
    unknown = set(request.builtin_tools) - BUILTIN_TOOLS
    if unknown:
        raise ValueError(f"unknown built-in tool: {sorted(unknown)}")
    payload: dict = {
        "model": model_id,
        "instructions": request.instructions,
        "input": _input_items(request.messages),
        "stream": request.stream,
    }
    if request.builtin_tools:
        payload["tools"] = [{"type": name} for name in request.builtin_tools]
    elif request.functions:
        payload["tools"] = [
            {
                "type": "function",
                "name": f.name,
                "description": f.description,
                "parameters": f.parameters,
            }
            for f in request.functions
        ]
    payload["enable_thinking"] = request.mode != "summary"
    return payload


def parse_response(data: dict) -> ModelResult:
    result = ModelResult()
    for item in data.get("output", []):
        kind = item.get("type")
        if kind == "message":
            for part in item.get("content", []):
                if part.get("type") in ("output_text", "text"):
                    result.text += part.get("text", "")
                    for note in part.get("annotations", []) or []:
                        if note.get("type") == "url_citation" and note.get("url"):
                            result.citations.append(
                                Citation(url=note["url"], title=note.get("title", ""))
                            )
        elif kind == "function_call":
            result.tool_calls.append(_tool_call(item))
        elif kind == "code_interpreter_call" and item.get("code"):
            result.code_blocks.append(item["code"])
    usage = data.get("usage") or {}
    details = usage.get("input_tokens_details") or {}
    result.usage = Usage(
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cached_tokens=details.get("cached_tokens", 0),
    )
    seen: set[str] = set()
    result.citations = [c for c in result.citations if not (c.url in seen or seen.add(c.url))]
    return result


def _tool_call(item: dict) -> ToolCall:
    try:
        arguments = json.loads(item.get("arguments") or "{}")
    except json.JSONDecodeError:
        arguments = {}
    return ToolCall(
        id=item.get("call_id") or item.get("id", ""),
        name=item["name"],
        arguments=arguments if isinstance(arguments, dict) else {},
    )


_KEYLIKE = re.compile(r"sk-[A-Za-z0-9*._-]+")


def provider_error(body: bytes | str) -> str:
    """The provider's own error code and message, short and without anything key-like."""
    try:
        data = json.loads(body)
        error = data.get("error", data) if isinstance(data, dict) else {}
        code = str(error.get("code") or error.get("type") or "")
        message = str(error.get("message") or "")
    except (ValueError, AttributeError):
        return ""
    text = _KEYLIKE.sub("sk-***", f"{code}: {message}".strip(": "))
    return text[:300]


class QwenResponsesClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        fast_model: str | None = None,
        timeout: float = 120.0,
        http: httpx.AsyncClient | None = None,
    ):
        self._url = base_url.rstrip("/") + "/responses"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._model = model
        self._fast_model = fast_model or model
        self._http = http or httpx.AsyncClient(timeout=timeout)

    def _model_for(self, request: ModelRequest) -> str:
        return self._fast_model if request.mode == "summary" else self._model

    async def complete(self, request: ModelRequest) -> ModelResult:
        payload = build_payload(request, model_id=self._model_for(request))
        payload["stream"] = False
        try:
            response = await self._http.post(self._url, headers=self._headers, json=payload)
        except httpx.HTTPError as exc:
            raise ModelError(f"model request failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            detail = provider_error(response.content)
            raise ModelError(f"model returned HTTP {response.status_code} {detail}".strip())
        return parse_response(response.json())

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        payload = build_payload(request, model_id=self._model_for(request))
        payload["stream"] = True
        try:
            async with self._http.stream(
                "POST", self._url, headers=self._headers, json=payload
            ) as response:
                if response.status_code != 200:
                    detail = provider_error(await response.aread())
                    raise ModelError(f"model returned HTTP {response.status_code} {detail}".strip())
                async for line in response.aiter_lines():
                    event = _sse_event(line)
                    if event is not None:
                        yield event
        except httpx.HTTPError as exc:
            raise ModelError(f"model stream failed: {type(exc).__name__}") from None


def _sse_event(line: str) -> StreamEvent | None:
    if not line.startswith("data:"):
        return None
    body = line[5:].strip()
    if not body or body == "[DONE]":
        return None
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        return None
    kind = event.get("type")
    if kind == "response.output_text.delta":
        return TextDelta(event.get("delta", ""))
    if kind == "response.output_item.done" and event.get("item", {}).get("type") == "function_call":
        return ToolCallEvent(_tool_call(event["item"]))
    if kind == "response.completed":
        return Completed(parse_response(event.get("response", {})))
    return None
