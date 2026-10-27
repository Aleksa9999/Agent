"""A scripted model: replays recorded answers and records every request it receives."""

import asyncio
from collections.abc import AsyncIterator

from app.agent.model import build_payload
from app.agent.types import (
    Citation,
    Completed,
    ModelRequest,
    ModelResult,
    StreamEvent,
    TextDelta,
    ToolCall,
    ToolCallEvent,
    Usage,
)


def say(text: str, *, tokens: int = 3) -> ModelResult:
    return ModelResult(text=text, usage=Usage(input_tokens=100, output_tokens=tokens))


def call(name: str, arguments: dict, call_id: str = "c1") -> ModelResult:
    return ModelResult(tool_calls=[ToolCall(call_id, name, arguments)], usage=Usage(100, 5))


class StubModel:
    """`script` maps a mode to a list of results consumed in order for that mode."""

    def __init__(self, script: dict[str, list[ModelResult]], delay: float = 0.0):
        self.script = {mode: list(results) for mode, results in script.items()}
        self.requests: list[ModelRequest] = []
        self.delay = delay

    def _next(self, request: ModelRequest) -> ModelResult:
        build_payload(request, model_id="stub")  # the real adapter's rules apply to the stub too
        self.requests.append(request)
        return self.script[request.mode].pop(0)

    def of(self, mode: str) -> list[ModelRequest]:
        return [r for r in self.requests if r.mode == mode]

    async def complete(self, request: ModelRequest) -> ModelResult:
        return self._next(request)

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamEvent]:
        result = self._next(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        for word in result.text.split(" ") if result.text else []:
            yield TextDelta(word + " ")
        for tool_call in result.tool_calls:
            yield ToolCallEvent(tool_call)
        yield Completed(result)


def with_sources(text: str, *urls: str) -> ModelResult:
    result = say(text)
    result.citations = [Citation(url=u, title=f"title {i}") for i, u in enumerate(urls)]
    return result
