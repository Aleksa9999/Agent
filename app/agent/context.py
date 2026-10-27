"""Context assembly: stable layers first (they cache well), the live conversation last.

Order: 1 studio constitution, 2 skills catalog, 3 agent passport, 4 project memory,
5 current skill, 6 session summary and the last messages, 7 the current message.
When the whole thing exceeds the budget, the oldest messages are folded into a summary.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.agent.types import Message

CHARS_PER_TOKEN = 3  # conservative for Russian text


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


@dataclass
class ContextInputs:
    constitution: str
    methods_index: str
    passport: dict
    project_docs: dict[str, str] = field(default_factory=dict)
    skill_context: str | None = None
    summary: str | None = None
    history: list[Message] = field(default_factory=list)
    current: str = ""
    attachments: list[str] = field(default_factory=list)
    tool_scope: object | None = None  # what the tools of this turn may touch (a skill run)


@dataclass
class BuiltContext:
    instructions: str
    messages: list[Message]
    summary: str | None
    summarized_count: int  # how many history messages were folded into the summary this time
    tokens: int


Summarizer = Callable[[str | None, list[Message]], Awaitable[str]]


def _layers(inputs: ContextInputs) -> str:
    parts = [
        "## Studio constitution\n" + inputs.constitution,
        "## Skills catalog\n" + inputs.methods_index,
        "## Agent passport\n" + json.dumps(inputs.passport, ensure_ascii=False, indent=1),
    ]
    if inputs.project_docs:
        docs = "\n\n".join(
            f"### {name}\n{text}" for name, text in sorted(inputs.project_docs.items())
        )
        parts.append("## Project memory\n" + docs)
    if inputs.skill_context:
        parts.append("## Current skill\n" + inputs.skill_context)
    return "\n\n".join(parts)


def _live(inputs: ContextInputs, history: list[Message], summary: str | None) -> list[Message]:
    messages: list[Message] = []
    if summary:
        messages.append(Message("system", "Summary of earlier sessions:\n" + summary))
    messages.extend(history)
    current = inputs.current
    if inputs.attachments:
        current += "\n\n[Attachments]\n" + "\n".join(inputs.attachments)
    messages.append(Message("user", current))
    return messages


def _size(instructions: str, messages: list[Message]) -> int:
    return estimate_tokens(instructions) + sum(estimate_tokens(m.content) for m in messages)


class ContextBuilder:
    def __init__(self, *, budget_tokens: int = 60000, keep_last: int = 30):
        self.budget = budget_tokens
        self.keep_last = keep_last

    async def build(self, inputs: ContextInputs, summarize: Summarizer) -> BuiltContext:
        instructions = _layers(inputs)
        history = list(inputs.history)
        summary = inputs.summary
        folded = 0
        # fold the oldest messages while the context is over budget and older messages exist
        while _size(instructions, _live(inputs, history, summary)) > self.budget:
            older = history[: max(len(history) - self.keep_last, 0)]
            if not older:
                break
            summary = await summarize(summary, older)
            history = history[len(older) :]
            folded += len(older)
        messages = _live(inputs, history, summary)
        return BuiltContext(
            instructions=instructions,
            messages=messages,
            summary=summary,
            summarized_count=folded,
            tokens=_size(instructions, messages),
        )
