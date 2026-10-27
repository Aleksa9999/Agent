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
from app.skills.runs import BATCH_LIMIT, RunScope, SpecError

log = logging.getLogger("app.agent")

RUN_HANDLERS = {"record_decision": "_record_decision", "propose_spec": "_propose_spec"}
RESEARCH_TOOLS = ("web_search", "web_extractor")
SANDBOX_TOOLS = ("code_interpreter", "web_search", "web_extractor")


@dataclass
class ToolOutput:
    text: str
    question: Question | None = None  # set by ask_options: the turn ends and the person answers
    usage: Usage | None = None
    spec_text: str | None = None  # set by propose_spec: the turn ends and the person decides


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


RUN_SPECS = (
    FunctionSpec(
        "record_decision",
        "Write a decision into the journal: what was decided and by whom. Use decided_by=agent "
        "when the person said 'decide for me' or 'I do not know'.",
        {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "decision": {"type": "string"},
                "decided_by": {"type": "string", "enum": ["person", "agent"]},
                "why": {"type": "string"},
            },
            "required": ["question", "decision", "decided_by"],
        },
    ),
    FunctionSpec(
        "propose_spec",
        "Show the person the spec of the skill result. It is saved only when the person presses "
        "Agree. Criteria describe what the person will see or check.",
        {
            "type": "object",
            "properties": {
                "how_it_looks": {"type": "string"},
                "criteria": {"type": "array", "items": {"type": "string"}},
                "out_of_scope": {"type": "array", "items": {"type": "string"}},
                "seams": {"type": "array", "items": {"type": "string"}},
                "assumptions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["how_it_looks", "criteria", "out_of_scope"],
        },
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

    def specs(self, scope: object | None = None) -> tuple[FunctionSpec, ...]:
        """The skill-run tools exist only while the person is going through a skill."""
        return SPECS + RUN_SPECS if isinstance(scope, RunScope) else SPECS

    def _t(self, key: str, **values: object) -> str:
        return self._tr.t(self._tenant, key, **values)

    async def run(self, call: ToolCall, scope: object | None = None) -> ToolOutput:
        if isinstance(scope, RunScope) and call.name in RUN_HANDLERS:
            return await getattr(self, RUN_HANDLERS[call.name])(call.arguments, scope)
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
            if call.name == "ask_options" and isinstance(scope, RunScope):
                return await self._ask_in_run(call.arguments, scope)
            return await handler(call.arguments)
        except ModelError as exc:
            log.warning("tool %s failed: %s", call.name, exc)
            return ToolOutput(
                "The tool is temporarily unavailable. Tell the person you could not check."
            )

    async def _ask_in_run(self, arguments: dict, scope: RunScope) -> ToolOutput:
        """A question inside a skill: at most five in a block, and never one already decided."""
        out = await self._ask_options(arguments)
        if out.question is None:
            return out
        run = await scope.service.get(scope.tenant, scope.run_id)
        if run is not None:
            decided = scope.service.find_decision(run, out.question.text)
            if decided is not None:
                return ToolOutput(
                    f"already decided: {decided['decision']}. Do not ask again; go on."
                )
        count = await scope.service.count_question(scope.tenant, scope.run_id)
        if count is not None and count > BATCH_LIMIT:
            return ToolOutput(
                "block limit reached: five questions are asked. Do not ask more now. Say in two "
                "sentences what you understood, and what is still open."
            )
        return out

    async def _record_decision(self, arguments: dict, scope: RunScope) -> ToolOutput:
        ok = await scope.service.record_decision(
            scope.tenant,
            scope.run_id,
            str(arguments.get("question", "")),
            str(arguments.get("decision", "")),
            str(arguments.get("decided_by", "agent")),
            str(arguments.get("why", "")),
        )
        return ToolOutput("recorded" if ok else "not recorded: question and decision are required")

    async def _propose_spec(self, arguments: dict, scope: RunScope) -> ToolOutput:
        run = await scope.service.get(scope.tenant, scope.run_id)
        if run is None:
            return ToolOutput("the skill run is gone")
        try:
            text = await scope.service.propose_spec(scope.tenant, run, arguments)
        except SpecError as exc:
            return ToolOutput(f"spec rejected, fix and call propose_spec again: {exc}")
        return ToolOutput("the spec is shown to the person with the buttons", spec_text=text)

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
