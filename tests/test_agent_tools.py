from datetime import date

import pytest

from app.agent.catalog import ModelCatalog
from app.agent.options import InvalidQuestionError, parse_question
from app.agent.tools import ToolRegistry
from app.agent.types import ToolCall
from app.i18n import Translator
from app.tenants import TenantRegistry
from tests.conftest import ROOT
from tests.stubs import StubModel, say, with_sources


def option(title, recommended=False, **extra):
    base = {
        "title": title,
        "description": f"{title} d",
        "cost": "500 RUB, 2 h",
        "pros": ["fast"],
        "cons": ["pricey"],
        "recommended": recommended,
    }
    return base | extra


def question(**changes):
    options = [option("A", True), option("B"), option("C"), option("D")]
    return {"question": "Which way?", "options": options} | changes


def test_a_well_formed_question_passes_and_knows_its_recommendation():
    parsed = parse_question(question())
    assert len(parsed.options) == 4 and parsed.recommended_index == 0 and parsed.id


@pytest.mark.parametrize(
    "bad",
    [
        question(options=[option("A", True), option("B"), option("C")]),
        question(options=[option("A", True), option("B"), option("C"), option("D"), option("E")]),
        question(options=[option("A"), option("B"), option("C"), option("D")]),
        question(options=[option("A", True), option("B", True), option("C"), option("D")]),
        question(options=[option("A", True), option("a"), option("C"), option("D")]),
        question(options=[option("A", True, cost=""), option("B"), option("C"), option("D")]),
        question(options=[option("A", True, pros=[]), option("B"), option("C"), option("D")]),
        question(question=" "),
    ],
)
def test_lazy_or_malformed_questions_are_rejected(bad):
    with pytest.raises(InvalidQuestionError):
        parse_question(bad)


@pytest.fixture
def make_tools(tenants_dir):
    def build(model: StubModel, catalog: ModelCatalog | None = None) -> ToolRegistry:
        tenants = TenantRegistry.load(tenants_dir)
        return ToolRegistry(
            model=model,
            catalog=catalog or ModelCatalog([]),
            translator=Translator(ROOT / "locales", tenants),
            tenant_id="default",
            prompts_dir=ROOT / "prompts",
            today=lambda: date(2026, 10, 27),
        )

    return build


async def test_research_returns_facts_with_links_and_the_collection_date(make_tools):
    model = StubModel(
        {"research": [with_sources("fact -> link -> date -> confirmed", "https://a.test")]}
    )
    out = await make_tools(model).run(ToolCall("1", "run_research", {"query": "competitors"}))
    assert "https://a.test" in out.text and "собрано 2026-10-27" in out.text
    (request,) = model.of("research")
    assert request.builtin_tools == ("web_search", "web_extractor") and request.functions == ()


async def test_research_without_a_single_source_says_not_found_and_drops_the_text(make_tools):
    model = StubModel({"research": [say("A confident claim from memory")]})
    out = await make_tools(model).run(ToolCall("1", "run_research", {"query": "market size"}))
    assert out.text.startswith("не найдено") and "memory" not in out.text


async def test_sandbox_shows_the_code_or_admits_there_is_none(make_tools):
    with_code = say("result 42")
    with_code.code_blocks = ["print(6*7)"]
    model = StubModel({"sandbox": [with_code, say("result 7")]})
    tools = make_tools(model)
    first = await tools.run(ToolCall("1", "run_sandbox", {"task": "6*7"}))
    assert "print(6*7)" in first.text and "Код расчёта:" in first.text
    second = await tools.run(ToolCall("2", "run_sandbox", {"task": "3+4"}))
    assert "не получен" in second.text
    assert all(
        r.functions == () and "code_interpreter" in r.builtin_tools for r in model.of("sandbox")
    )


async def test_prices_come_from_the_catalog_only(make_tools, tmp_path):
    catalog_file = tmp_path / "catalog.yaml"
    catalog_file.write_text(
        "models:\n  - {provider: p, model_id: big-1, capability: text,"
        " prices: {input_per_mtok_usd: 2.5}, synced_at: '2026-10-26'}\n",
        encoding="utf-8",
    )
    tools = make_tools(StubModel({}), ModelCatalog.load(catalog_file))
    hit = await tools.run(ToolCall("1", "lookup_model_price", {"query": "BIG-1"}))
    assert "2.5" in hit.text and "2026-10-26" in hit.text
    by_capability = await tools.run(ToolCall("2", "lookup_model_price", {"query": "text"}))
    assert "big-1" in by_capability.text
    miss = await tools.run(ToolCall("3", "lookup_model_price", {"query": "video"}))
    assert miss.text.startswith("не найдено")


async def test_empty_catalog_never_invents_a_price(make_tools):
    out = await make_tools(StubModel({})).run(
        ToolCall("1", "lookup_model_price", {"query": "text"})
    )
    assert out.text.startswith("не найдено")


async def test_ask_options_hands_back_a_question_or_an_error_for_the_model(make_tools):
    tools = make_tools(StubModel({}))
    ok = await tools.run(ToolCall("1", "ask_options", question()))
    assert ok.question is not None and ok.question.text == "Which way?"
    bad = await tools.run(ToolCall("2", "ask_options", question(options=[])))
    assert bad.question is None and "invalid question" in bad.text
    unknown = await tools.run(ToolCall("3", "format_disk", {}))
    assert unknown.text == "unknown tool: format_disk"
