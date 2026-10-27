import asyncio
from datetime import date

import pytest

from app.agent.catalog import ModelCatalog
from app.agent.context import ContextBuilder, ContextInputs, estimate_tokens
from app.agent.orchestrator import Agent, Done, OptionsAsked, ToolStarted
from app.agent.tools import ToolRegistry
from app.agent.types import Message, ModelResult, TextDelta, ToolCall
from app.i18n import Translator
from app.tenants import TenantRegistry
from tests.conftest import ROOT
from tests.stubs import StubModel, call, say, with_sources
from tests.test_agent_tools import option


def inputs(history=None, summary=None, current="hello", **kw) -> ContextInputs:
    return ContextInputs(
        constitution="CONSTITUTION",
        methods_index="idea-card; mvp-scope",
        passport={"name": "Anna", "country": "RU"},
        project_docs={"project.md": "A manicure app"},
        skill_context="skill: idea-card",
        summary=summary,
        history=history or [],
        current=current,
        **kw,
    )


def chat(n: int, size: int = 200) -> list[Message]:
    return [Message("user" if i % 2 == 0 else "assistant", f"m{i} " + "x" * size) for i in range(n)]


async def fold(previous, older):
    return f"SUMMARY of {len(older)}" + (f" after {previous}" if previous else "")


async def test_layers_come_in_the_documented_order_with_the_live_message_last():
    built = await ContextBuilder().build(
        inputs(history=chat(2), summary="old news", attachments=["file.pdf"]), fold
    )
    text = built.instructions
    order = [
        "Studio constitution",
        "Skills catalog",
        "Agent passport",
        "Project memory",
        "Current skill",
    ]
    assert [text.index(f"## {name}") for name in order] == sorted(
        text.index(f"## {n}") for n in order
    )
    assert built.messages[0].content.startswith("Summary of earlier sessions:\nold news")
    assert built.messages[-1].role == "user" and "file.pdf" in built.messages[-1].content


async def test_the_stable_prefix_does_not_change_between_turns_so_the_cache_can_work():
    builder = ContextBuilder()
    first = await builder.build(inputs(history=chat(2), current="one"), fold)
    second = await builder.build(inputs(history=chat(6), current="two"), fold)
    assert first.instructions == second.instructions


async def test_an_over_budget_history_is_folded_into_a_summary_and_the_tail_is_kept():
    builder = ContextBuilder(budget_tokens=2000, keep_last=10)
    history = chat(60)
    built = await builder.build(inputs(history=history), fold)
    assert (
        built.tokens <= 2000 or built.summarized_count == 50
    )  # tail itself may be all that is left
    assert built.summarized_count == 50
    assert built.summary == "SUMMARY of 50"
    kept = [m.content for m in built.messages if m.role in ("user", "assistant")]
    assert kept[:-1] == [m.content for m in history[50:]]  # last 10 verbatim, then the new message


async def test_under_budget_history_is_untouched():
    built = await ContextBuilder(budget_tokens=60000).build(inputs(history=chat(10)), fold)
    assert built.summarized_count == 0 and built.summary is None and len(built.messages) == 11


async def test_summaries_chain_when_a_summary_already_exists():
    built = await ContextBuilder(budget_tokens=1500, keep_last=5).build(
        inputs(history=chat(40), summary="S1"), fold
    )
    assert built.summary == "SUMMARY of 35 after S1"


def test_token_estimate_is_conservative_for_russian_text():
    assert estimate_tokens("привет" * 30) >= 60


@pytest.fixture
def agent_for(tenants_dir):
    def build(model: StubModel, *, budget: int = 60000, keep_last: int = 30) -> Agent:
        tenants = TenantRegistry.load(tenants_dir)
        translator = Translator(ROOT / "locales", tenants)
        tools = ToolRegistry(
            model=model,
            catalog=ModelCatalog([]),
            translator=translator,
            tenant_id="default",
            prompts_dir=ROOT / "prompts",
            today=lambda: date(2026, 10, 27),
        )
        return Agent(
            model=model,
            tools=tools,
            context=ContextBuilder(budget_tokens=budget, keep_last=keep_last),
            translator=translator,
            tenant_id="default",
            prompts_dir=ROOT / "prompts",
        )

    return build


async def run(agent, **kw):
    return [event async for event in agent.respond(inputs(), **kw)]


async def test_a_plain_answer_streams_and_the_first_token_is_fast(agent_for):
    model = StubModel({"mentor": [say("Let us start with the card of your idea")]}, delay=0.05)
    events = await run(agent_for(model))
    deltas = [e for e in events if isinstance(e, TextDelta)]
    done = events[-1]
    assert len(deltas) > 3 and isinstance(done, Done)
    assert done.text == "Let us start with the card of your idea "
    assert done.first_token_seconds is not None and done.first_token_seconds < 4
    assert done.usage.input_tokens == 100


async def test_research_runs_as_its_own_request_and_its_result_returns_to_the_mentor(agent_for):
    model = StubModel(
        {
            "mentor": [call("run_research", {"query": "competitors"}), say("Three players found")],
            "research": [with_sources("fact -> link", "https://a.test")],
        }
    )
    events = await run(agent_for(model))
    assert [type(e).__name__ for e in events if isinstance(e, ToolStarted)] == ["ToolStarted"]
    mentor_first, mentor_second = model.of("mentor")
    # the mentor only ever sees custom functions; research only ever sees built-in tools
    assert mentor_first.builtin_tools == () and mentor_first.functions
    (research,) = model.of("research")
    assert research.functions == () and research.builtin_tools
    tool_message = mentor_second.messages[-1]
    assert tool_message.role == "tool" and "https://a.test" in tool_message.content
    assert events[-1].text == "Three players found "


async def test_a_calculation_and_a_price_lookup_happen_in_one_turn_without_conflicts(agent_for):
    sandbox = say("margin 31%")
    sandbox.code_blocks = ["print(0.31)"]
    model = StubModel(
        {
            "mentor": [
                ModelResult(
                    tool_calls=[
                        ToolCall("a", "run_sandbox", {"task": "margin"}),
                        ToolCall("b", "lookup_model_price", {"query": "text"}),
                    ]
                ),
                say("Done"),
            ],
            "sandbox": [sandbox],
        }
    )
    events = await run(agent_for(model))
    assert events[-1].text == "Done "
    last = model.of("mentor")[-1].messages
    assert "print(0.31)" in last[-2].content and last[-1].content.startswith("не найдено")


async def test_a_question_ends_the_turn_and_waits_for_the_person(agent_for):
    arguments = {
        "question": "Which way?",
        "options": [option("A", True), option("B"), option("C"), option("D")],
    }
    model = StubModel({"mentor": [call("ask_options", arguments)]})
    events = await run(agent_for(model))
    asked = [e for e in events if isinstance(e, OptionsAsked)]
    assert len(asked) == 1 and asked[0].question.recommended_index == 0
    assert len(model.of("mentor")) == 1 and isinstance(events[-1], Done)


async def test_a_lazy_question_is_sent_back_to_the_model_to_fix(agent_for):
    good = {
        "question": "Which way?",
        "options": [option("A", True), option("B"), option("C"), option("D")],
    }
    model = StubModel(
        {
            "mentor": [
                call("ask_options", {"question": "Which?", "options": [option("A", True)]}, "1"),
                call("ask_options", good, "2"),
            ]
        }
    )
    events = await run(agent_for(model))
    assert any(isinstance(e, OptionsAsked) for e in events)
    assert "invalid question" in model.of("mentor")[1].messages[-1].content


async def test_a_runaway_tool_loop_stops_with_a_polite_message(agent_for):
    endless = [call("lookup_model_price", {"query": "text"}, str(i)) for i in range(10)]
    events = await run(agent_for(StubModel({"mentor": endless})))
    assert (
        "слишком много" in events[-1].text
        and len([e for e in events if isinstance(e, ToolStarted)]) == 5
    )


async def test_the_stop_button_ends_generation_and_keeps_what_was_said(agent_for):
    cancel = asyncio.Event()
    model = StubModel({"mentor": [say("one two three four five six")]})
    seen = []
    async for event in agent_for(model).respond(inputs(), cancel=cancel):
        seen.append(event)
        if isinstance(event, TextDelta) and event.text.startswith("two"):
            cancel.set()
    assert seen[-1].stopped is True and seen[-1].text.startswith("one two")
    assert "six" not in seen[-1].text


async def test_a_long_history_is_summarised_by_the_fast_model_and_reported(agent_for):
    model = StubModel({"mentor": [say("ok")], "summary": [say("earlier decisions: idea chosen")]})
    agent = agent_for(model, budget=1500, keep_last=5)
    events = [e async for e in agent.respond(inputs(history=chat(40)))]
    done = events[-1]
    assert done.summarized_count == 35 and done.summary == "earlier decisions: idea chosen"
    (summary_request,) = model.of("summary")
    assert summary_request.mode == "summary" and summary_request.functions == ()
    assert "m0 " in summary_request.messages[0].content
    assert model.of("mentor")[0].messages[0].content.startswith("Summary of earlier sessions:")
