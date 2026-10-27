"""Tools the mentor can call. Research and calculations are separate model requests with built-in
tools only, so the mentor itself (custom functions only) never mixes the two kinds in one call."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.agent.catalog import ModelCatalog
from app.agent.model import ModelError, ModelPort
from app.agent.options import QUESTION_SCHEMA, InvalidQuestionError, Question, parse_question
from app.agent.prompts import load_prompt
from app.agent.types import FunctionSpec, Message, ModelRequest, ToolCall, Usage
from app.i18n import Translator

log = logging.getLogger("app.agent")

RESEARCH_TOOLS = ("web_search", "web_extractor")
SANDBOX_TOOLS = ("code_interpreter", "web_search", "web_extractor")


@dataclass
class ToolOutput:
    text: str
    question: Question | None = None  # set by ask_options: the turn ends and the person answers
    usage: Usage | None = None


def _simple(name: str, description: str, field: str, field_doc: str) -> FunctionSpec:
    return FunctionSpec(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": {field: {"type": "string", "description": field_doc}},
            "required": [field],
        },
    )


SPECS = (
    FunctionSpec(
        "ask_options",
        "Ask the person a question or offer a fork: exactly four different options with price and "
        "time, one recommended.",
        QUESTION_SCHEMA,
    ),
    _simple(
        "run_research",
        "Find facts on the web with sources. Use for markets, competitors, prices, laws, exams.",
        "query",
        "What to find out.",
    ),
    _simple(
        "run_sandbox",
        "Calculate with code. Use for any arithmetic, unit economics or table analysis.",
        "task",
        "What to calculate, with the input numbers.",
    ),
    _simple(
        "lookup_model_price",
        "Get the price of an AI model or capability from the catalog. "
        "This is the only source of such prices.",
        "query",
        "A model id or a capability: text, vision, image, video, tts, asr.",
    ),
)


class ToolRegistry:
    def __init__(
        self,
        *,
        model: ModelPort,
        catalog: ModelCatalog,
        translator: Translator,
        tenant_id: str,
        prompts_dir: Path,
        today: Callable[[], date] = date.today,
    ):
        self._model = model
        self._catalog = catalog
        self._tr = translator
        self._tenant = tenant_id
        self._prompts = prompts_dir
        self._today = today

    def specs(self) -> tuple[FunctionSpec, ...]:
        return SPECS

    def _t(self, key: str, **values: object) -> str:
        return self._tr.t(self._tenant, key, **values)

    async def run(self, call: ToolCall) -> ToolOutput:
        handlers = {
            "ask_options": self._ask_options,
            "run_research": self._research,
            "run_sandbox": self._sandbox,
            "lookup_model_price": self._price,
        }
        handler = handlers.get(call.name)
        if handler is None:
            return ToolOutput(f"unknown tool: {call.name}")
        try:
            return await handler(call.arguments)
        except ModelError as exc:
            log.warning("tool %s failed: %s", call.name, exc)
            return ToolOutput(
                "The tool is temporarily unavailable. Tell the person you could not check."
            )

    async def _ask_options(self, arguments: dict) -> ToolOutput:
        try:
            return ToolOutput("question shown to the person", question=parse_question(arguments))
        except InvalidQuestionError as exc:
            return ToolOutput(f"invalid question, fix it and call ask_options again: {exc}")

    async def _research(self, arguments: dict) -> ToolOutput:
        query = str(arguments.get("query", "")).strip()
        result = await self._model.complete(
            ModelRequest(
                mode="research",
                instructions=load_prompt(self._prompts, "modes/research.md"),
                messages=[Message("user", query)],
                builtin_tools=RESEARCH_TOOLS,
            )
        )
        if not result.citations:  # no source, no fact
            return ToolOutput(self._t("research_not_found", query=query), usage=result.usage)
        sources = "\n".join(f"- {c.title or c.url}: {c.url}" for c in result.citations)
        header = self._t("research_sources", date=self._today().isoformat())
        return ToolOutput(f"{result.text}\n\n{header}\n{sources}", usage=result.usage)

    async def _sandbox(self, arguments: dict) -> ToolOutput:
        task = str(arguments.get("task", "")).strip()
        result = await self._model.complete(
            ModelRequest(
                mode="sandbox",
                instructions=load_prompt(self._prompts, "modes/sandbox.md"),
                messages=[Message("user", task)],
                builtin_tools=SANDBOX_TOOLS,
            )
        )
        if result.code_blocks:
            code = self._t("sandbox_code_header") + "\n" + "\n\n".join(result.code_blocks)
        else:
            code = self._t("sandbox_no_code")
        return ToolOutput(f"{result.text}\n\n{code}", usage=result.usage)

    async def _price(self, arguments: dict) -> ToolOutput:
        query = str(arguments.get("query", "")).strip()
        entries = self._catalog.lookup(query)
        if not entries:
            return ToolOutput(self._t("price_not_found", query=query))
        lines = [
            self._t(
                "price_line",
                model_id=e.model_id,
                capability=e.capability,
                prices=json.dumps(e.prices, ensure_ascii=False),
                synced_at=e.synced_at,
            )
            for e in entries
        ]
        return ToolOutput("\n".join(lines))
