"""Plain data types shared by the agent core. Nothing here talks to the network."""

from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["mentor", "research", "sandbox", "summary"]
Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class ModelRequest:
    mode: Mode
    instructions: str
    messages: list[Message]
    functions: tuple[FunctionSpec, ...] = ()
    builtin_tools: tuple[str, ...] = ()
    stream: bool = False


@dataclass(frozen=True)
class Citation:
    url: str
    title: str = ""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cached_tokens += other.cached_tokens


@dataclass
class ModelResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    code_blocks: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCallEvent:
    call: ToolCall


@dataclass(frozen=True)
class Completed:
    result: ModelResult


StreamEvent = TextDelta | ToolCallEvent | Completed
