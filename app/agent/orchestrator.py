"""The mentor loop: stream the answer, run the tools the model asks for, repeat.

The mentor request carries custom functions only. Research and calculations run as their own
requests inside the tools (see tools.py), and their results come back as tool outputs.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app.agent.context import ContextBuilder, ContextInputs
from app.agent.model import ModelPort
from app.agent.options import Question
from app.agent.prompts import load_prompt
from app.agent.tools import ToolRegistry
from app.agent.types import (
    Completed,
    Message,
    ModelRequest,
    TextDelta,
    ToolCall,
    ToolCallEvent,
    Usage,
)
from app.i18n import Translator

MAX_TOOL_ROUNDS = 5


@dataclass(frozen=True)
class ToolStarted:
    name: str


@dataclass(frozen=True)
class OptionsAsked:
    question: Question


@dataclass
class Done:
    text: str
    usage: Usage = field(default_factory=Usage)
    first_token_seconds: float | None = None
    summary: str | None = None
    summarized_count: int = 0
    stopped: bool = False


AgentEvent = TextDelta | ToolStarted | OptionsAsked | Done


class Agent:
    def __init__(
        self,
        *,
        model: ModelPort,
        tools: ToolRegistry,
        context: ContextBuilder,
        translator: Translator,
        tenant_id: str,
        prompts_dir,
    ):
        self._model = model
        self._tools = tools
        self._context = context
        self._tr = translator
        self._tenant = tenant_id
        self._prompts = prompts_dir

    async def _summarize(self, previous: str | None, older: list[Message]) -> str:
        transcript = "\n".join(f"{m.role}: {m.content}" for m in older)
        prefix = f"Earlier summary:\n{previous}\n\n" if previous else ""
        result = await self._model.complete(
            ModelRequest(
                mode="summary",
                instructions=load_prompt(self._prompts, "modes/summary.md"),
                messages=[Message("user", prefix + transcript)],
            )
        )
        return result.text

    async def respond(
        self, inputs: ContextInputs, *, cancel: asyncio.Event | None = None
    ) -> AsyncIterator[AgentEvent]:
        started = time.monotonic()
        built = await self._context.build(inputs, self._summarize)
        messages = list(built.messages)
        usage = Usage()
        first_token: float | None = None
        spoken: list[str] = []

        def done(stopped: bool = False) -> Done:
            return Done(
                text="".join(spoken),
                usage=usage,
                first_token_seconds=first_token,
                summary=built.summary,
                summarized_count=built.summarized_count,
                stopped=stopped,
            )

        for _ in range(MAX_TOOL_ROUNDS):
            request = ModelRequest(
                mode="mentor",
                instructions=built.instructions,
                messages=list(messages),
                functions=self._tools.specs(),
                stream=True,
            )
            calls: list[ToolCall] = []
            turn_text: list[str] = []
            async for event in self._model.stream(request):
                if cancel is not None and cancel.is_set():
                    yield done(stopped=True)
                    return
                if isinstance(event, TextDelta):
                    if first_token is None:
                        first_token = time.monotonic() - started
                    turn_text.append(event.text)
                    spoken.append(event.text)
                    yield event
                elif isinstance(event, ToolCallEvent):
                    calls.append(event.call)
                elif isinstance(event, Completed):
                    usage.add(event.result.usage)
            if not calls:
                yield done()
                return
            messages.append(Message("assistant", "".join(turn_text), tuple(calls)))
            for call in calls:
                yield ToolStarted(call.name)
                output = await self._tools.run(call)
                if output.usage:
                    usage.add(output.usage)
                if output.question is not None:
                    yield OptionsAsked(output.question)
                    yield done()
                    return
                messages.append(Message("tool", output.text, tool_call_id=call.id))
        limit_text = self._tr.t(self._tenant, "agent_tool_limit")
        spoken.append(limit_text)
        yield TextDelta(limit_text)
        yield done()
