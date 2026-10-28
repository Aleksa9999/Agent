"""Slice 09: starting a skill, the interrogation rules and the spec that needs a button."""

import time

import pytest
from fastapi.testclient import TestClient

from app.agent.catalog import CatalogEntry, ModelCatalog
from app.agent.tools import ToolRegistry
from app.agent.types import ToolCall
from app.main import create_app
from app.skills.estimate import estimate_text
from app.skills.runs import BATCH_LIMIT, RunScope
from tests.conftest import ROOT
from tests.fake_telegram import callback_update, command_update, person, text_update
from tests.stubs import StubModel, call, say
from tests.test_miniapp import TOKEN, signed

ANNA = person(7, "Anna", "Ivanova")
BORIS = person(8, "Boris", None)


def question(text: str = "Какой сайт нужен?") -> dict:
    options = [
        {
            "title": f"Вариант {i}",
            "description": "описание",
            "cost": "500 рублей, 2 часа",
            "pros": ["плюс"],
            "cons": ["минус"],
            "recommended": i == 2,
        }
        for i in range(1, 5)
    ]
    return {"question": text, "options": options}


SPEC = {
    "how_it_looks": "Человек открывает сайт студии маникюра и записывается на приём онлайн.",
    "criteria": [
        "На главной странице есть форма записи, заявка приходит владельцу в Telegram",
        "Страница открывается на телефоне без горизонтальной прокрутки",
    ],
    "out_of_scope": ["Онлайн-оплата", "Личный кабинет клиента"],
    "seams": ["Открыть страницу на телефоне и отправить заявку"],
    "assumptions": ["Домен уже куплен"],
}


@pytest.fixture
async def anna(runtime):
    """Anna pressed /start: she has a chat and the topics."""
    await runtime.feed("default", command_update(ANNA, "/start"))
    return await runtime.repo.get_user("default", 7)


def keyboard_of(message):
    return [b for row in message.reply_markup.inline_keyboard for b in row]


def last_message(session):
    return session.of("sendMessage")[-1]


async def start_skill(runtime, session, slug="site-with-ai", road="agent"):
    assert await runtime.flow("default").start(7, slug) == "ok"
    intro = last_message(session)
    button = next(b for b in keyboard_of(intro) if f":road:{road}:" in b.callback_data)
    await runtime.feed("default", callback_update(ANNA, button.callback_data, update_id=50))
    return intro


# starting ---------------------------------------------------------------------------------
async def test_starting_a_skill_shows_the_roads_the_estimate_and_asks_for_the_road(
    runtime, session, anna
):
    assert await runtime.flow("default").start(7, "site-with-ai") == "ok"
    intro = last_message(session)
    skills_topic = await runtime.repo.get_topic("default", anna.id, "dm_skills")
    assert intro.message_thread_id == skills_topic.thread_id  # in the "Skills" topic
    assert "Делает агент" in intro.text and "Пройду сам" in intro.text
    assert "Эконом:" in intro.text and "Стандарт:" in intro.text and "Премиум:" in intro.text
    assert "reasoning" in intro.text  # the roles of the box
    assert "не найдено" in intro.text and "из памяти" in intro.text  # the catalog has no prices
    assert "код проекта пишется позже" in intro.text  # a skill with code: concept first
    labels = [b.text for b in keyboard_of(intro)]
    assert labels == ["Делает агент", "Пройду сам"]


async def test_an_unknown_skill_or_a_person_without_a_chat_is_refused(runtime, session, anna):
    assert await runtime.flow("default").start(7, "no-such-skill") == "unknown_skill"
    assert await runtime.flow("default").start(999, "site-with-ai") == "no_chat"


def test_estimate_prices_come_from_the_catalog_only(runtime):
    doc = runtime.skills.get("default", "idea-card")
    entry = CatalogEntry("modelstudio", "m-1", "text", {"input_per_mtok_usd": 1.0}, "2026-10-27")
    text = estimate_text(runtime.translator, "default", doc, ModelCatalog([entry]))
    assert "m-1 (text)" in text and "2026-10-27" in text
    empty = estimate_text(runtime.translator, "default", doc, ModelCatalog([]))
    assert "m-1" not in empty and "не найдено" in empty


async def test_a_new_skill_pauses_the_previous_one(runtime, session, anna, skill_run_store):
    await runtime.flow("default").start(7, "site-with-ai")
    await runtime.flow("default").start(7, "idea-card")
    active = skill_run_store.active("default", anna.id)
    assert active.slug == "idea-card"
    first = skill_run_store.get("default", 1)
    assert first.status == "paused"


# the road ---------------------------------------------------------------------------------
async def test_the_road_button_starts_the_interrogation_with_the_skill_in_context(
    make_runtime, session
):
    model = StubModel({"mentor": [call("ask_options", question())]})
    runtime = make_runtime(model)
    await runtime.feed("default", command_update(ANNA, "/start"))
    await start_skill(runtime, session, "site-with-ai", "agent")
    (request,) = model.requests
    text = request.instructions
    assert "## Current skill" in text and "Делаю сайт с ИИ" in text and "Дорога: agent" in text
    assert (
        "### Допрос" in text and "### Критерии приёмки" in text and "### Отказы и границы" in text
    )
    assert "код проекта человека не пиши" in text  # a skill with code in wave 1
    names = {f.name for f in request.functions}
    assert {"ask_options", "run_research", "record_decision", "propose_spec"} <= names
    asked = last_message(session)
    assert "Какой сайт нужен?" in asked.text and "⭐" in asked.text  # standard A with a star
    assert len(keyboard_of(asked)) >= 8  # four options and the four controls


async def test_a_road_is_chosen_once_and_only_by_the_owner_of_the_run(make_runtime, session):
    model = StubModel({"mentor": [say("Начнём")]})
    runtime = make_runtime(model)
    await runtime.feed("default", command_update(ANNA, "/start"))
    await runtime.feed("default", command_update(BORIS, "/start", update_id=4))
    await runtime.flow("default").start(7, "site-with-ai")
    data = keyboard_of(last_message(session))[0].callback_data
    await runtime.feed("default", callback_update(BORIS, data, update_id=60))  # not Anna
    assert session.of("answerCallbackQuery")[-1].show_alert is True and not model.requests
    await runtime.feed("default", callback_update(ANNA, data, update_id=61))
    assert len(model.requests) == 1
    await runtime.feed("default", callback_update(ANNA, data, update_id=62))  # pressed twice
    assert session.of("answerCallbackQuery")[-1].show_alert is True and len(model.requests) == 1


async def test_outside_the_skills_topic_the_skill_tools_are_off(make_runtime, session):
    model = StubModel({"mentor": [call("ask_options", question()), say("Это профиль")]})
    runtime = make_runtime(model)
    await runtime.feed("default", command_update(ANNA, "/start"))
    await start_skill(runtime, session)
    anna = await runtime.repo.get_user("default", 7)
    profile = await runtime.repo.get_topic("default", anna.id, "dm_profile")
    await runtime.feed(
        "default", text_update(ANNA, "привет", update_id=70, thread_id=profile.thread_id)
    )
    names = {f.name for f in model.requests[-1].functions}
    assert (
        "record_decision" not in names and "## Current skill" not in model.requests[-1].instructions
    )


# the interrogation rules ---------------------------------------------------------------------
@pytest.fixture
async def scope(runtime, anna, skill_run_store):
    started = await runtime.runs("default").start("default", anna.id, "site-with-ai")
    run, _ = started
    await runtime.runs("default").choose_road("default", run.id, "agent")
    tools = ToolRegistry(
        model=StubModel({}),
        catalog=ModelCatalog([]),
        translator=runtime.translator,
        tenant_id="default",
        prompts_dir=ROOT / "prompts",
    )
    return tools, RunScope(runtime.runs("default"), "default", run.id)


async def ask(tools, scope, text):
    return await tools.run(ToolCall("c", "ask_options", question(text)), scope)


async def test_at_most_five_questions_in_a_block_then_the_block_closes(scope):
    tools, scope = scope
    for n in range(BATCH_LIMIT):
        assert (await ask(tools, scope, f"Вопрос {n}")).question is not None
    sixth = await ask(tools, scope, "Вопрос 6")
    assert sixth.question is None and "block limit" in sixth.text
    await scope.service.reset_batch("default", scope.run_id)  # the block ended with a summary
    assert (await ask(tools, scope, "Вопрос 7")).question is not None


async def test_a_question_that_is_already_decided_is_not_asked_again(scope):
    tools, scope = scope
    result = await tools.run(
        ToolCall(
            "c",
            "record_decision",
            {"question": "Какой сайт нужен?", "decision": "Лендинг", "decided_by": "agent"},
        ),
        scope,
    )
    assert result.text == "recorded"
    again = await ask(tools, scope, "  какой сайт нужен?  ")
    assert again.question is None and "already decided: Лендинг" in again.text


async def test_the_skill_tools_exist_only_inside_a_skill(scope):
    tools, run_scope = scope
    assert {"record_decision", "propose_spec"} <= {f.name for f in tools.specs(run_scope)}
    assert {"record_decision", "propose_spec"}.isdisjoint(f.name for f in tools.specs(None))
    out = await tools.run(ToolCall("c", "propose_spec", SPEC), None)
    assert "unknown tool" in out.text  # no run: nothing to write into


async def test_i_dont_know_is_accepted_and_written_to_the_journal(
    make_runtime, session, skill_run_store
):
    model = StubModel(
        {"mentor": [call("ask_options", question()), say("Беру рекомендованный вариант")]}
    )
    runtime = make_runtime(model)
    await runtime.feed("default", command_update(ANNA, "/start"))
    await start_skill(runtime, session)
    asked = last_message(session)
    unknown = next(b for b in keyboard_of(asked) if b.text == "🤷 Не знаю")
    await runtime.feed("default", callback_update(ANNA, unknown.callback_data, update_id=80))

    anna = await runtime.repo.get_user("default", 7)
    (entry,) = skill_run_store.active("default", anna.id).decisions
    assert entry["by"] == "agent" and entry["decision"] == "Вариант 2"  # the starred one
    assert entry["question"] == "Какой сайт нужен?" and "не знаю" in entry["why"]
    # the next turn shows the journal to the model, so it is not asked again
    assert "[agent] Какой сайт нужен? -> Вариант 2" in model.requests[-1].instructions


async def test_a_decision_the_model_records_for_the_person_goes_to_the_journal(
    make_runtime, session, skill_run_store
):
    model = StubModel(
        {
            "mentor": [
                call(
                    "record_decision",
                    {"question": "Домен", "decision": "уже куплен", "decided_by": "person"},
                ),
                say("Записал"),
            ]
        }
    )
    runtime = make_runtime(model)
    await runtime.feed("default", command_update(ANNA, "/start"))
    await start_skill(runtime, session)
    anna = await runtime.repo.get_user("default", 7)
    (entry,) = skill_run_store.active("default", anna.id).decisions
    assert (entry["by"], entry["decision"]) == ("person", "уже куплен")


# the spec ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"criteria": []}, "at least one"),
        ({"criteria": ["Короткий"]}, "too short"),
        (
            {"criteria": ["Реализован личный кабинет клиента со всеми функциями"]},
            "says what was done",
        ),
        ({"criteria": [SPEC["criteria"][0], SPEC["criteria"][0]]}, "repeats"),
        ({"out_of_scope": []}, "out_of_scope"),
        ({"how_it_looks": "коротко"}, "how_it_looks"),
    ],
)
async def test_a_bad_spec_goes_back_to_the_model_and_nothing_is_shown(scope, change, reason):
    tools, run_scope = scope
    out = await tools.run(ToolCall("c", "propose_spec", {**SPEC, **change}), run_scope)
    assert out.spec_text is None and "spec rejected" in out.text and reason in out.text


async def test_the_spec_is_shown_first_and_saved_only_after_agree(
    make_runtime, session, skill_run_store
):
    model = StubModel(
        {
            "mentor": [
                call("ask_options", question()),
                call("propose_spec", SPEC),
                say("Идём дальше к задачам"),
            ]
        }
    )
    runtime = make_runtime(model)
    await runtime.feed("default", command_update(ANNA, "/start"))
    await start_skill(runtime, session)
    unknown = next(b for b in keyboard_of(last_message(session)) if b.text == "🤷 Не знаю")
    await runtime.feed("default", callback_update(ANNA, unknown.callback_data, update_id=80))

    shown = last_message(session)
    assert "Спека навыка «Делаю сайт с ИИ»" in shown.text
    assert "К1. На главной странице есть форма записи" in shown.text and "К2." in shown.text
    assert "Вне рамок" in shown.text and "Онлайн-оплата" in shown.text
    assert "Что я решил за вас" in shown.text and "Вариант 2" in shown.text  # the journal
    assert "Что я додумал сам" in shown.text and "Домен уже куплен" in shown.text
    agree, fix = keyboard_of(shown)
    assert (agree.text, fix.text) == ("Согласен", "Поправить")

    anna = await runtime.repo.get_user("default", 7)
    run = skill_run_store.active("default", anna.id)
    assert run.spec_status == "proposed" and run.spec["criteria"]  # shown, not yet saved
    assert not any("Спека записана" in str(m) for m in session.of("answerCallbackQuery"))

    await runtime.feed("default", callback_update(ANNA, agree.callback_data, update_id=90))
    run = skill_run_store.active("default", anna.id)
    assert run.spec_status == "saved" and run.spec_text == shown.text.split("\n\nСогласны")[0]
    assert "Спека согласована и записана" in model.requests[-1].messages[-1].content
    await runtime.feed("default", callback_update(ANNA, agree.callback_data, update_id=91))
    assert session.of("answerCallbackQuery")[-1].show_alert is True  # a second press does nothing


async def test_fix_reopens_the_conversation_and_an_old_agree_button_does_nothing(
    make_runtime, session, skill_run_store
):
    model = StubModel(
        {
            "mentor": [
                call("propose_spec", SPEC),
                say("Что поправить?"),
                call("propose_spec", SPEC),
                say("Дальше"),
            ]
        }
    )
    runtime = make_runtime(model)
    await runtime.feed("default", command_update(ANNA, "/start"))
    await start_skill(runtime, session)
    anna = await runtime.repo.get_user("default", 7)
    first = last_message(session)
    old_agree, fix = keyboard_of(first)
    await runtime.feed("default", callback_update(ANNA, fix.callback_data, update_id=90))
    assert skill_run_store.active("default", anna.id).spec_status == "none"  # nothing is saved
    assert "Спеку нужно поправить" in model.requests[1].messages[-1].content

    topic = await runtime.repo.get_topic("default", anna.id, "dm_skills")
    await runtime.feed(
        "default", text_update(ANNA, "поменяй срок", update_id=91, thread_id=topic.thread_id)
    )
    second = last_message(session)
    assert second is not first and skill_run_store.active("default", anna.id).spec_rev == 2
    await runtime.feed("default", callback_update(ANNA, old_agree.callback_data, update_id=92))
    assert session.of("answerCallbackQuery")[-1].show_alert is True  # the old button is dead
    assert skill_run_store.active("default", anna.id).spec_status == "proposed"
    new_agree, _ = keyboard_of(second)
    await runtime.feed("default", callback_update(ANNA, new_agree.callback_data, update_id=93))
    assert skill_run_store.active("default", anna.id).spec_status == "saved"


async def test_a_spec_cannot_be_saved_without_a_proposal(runtime, anna, skill_run_store):
    run, _ = await runtime.runs("default").start("default", anna.id, "idea-card")
    assert skill_run_store.agree("default", run.id, 0) is None
    assert skill_run_store.get("default", run.id).spec_status == "none"


# the Mini App -----------------------------------------------------------------------------
@pytest.fixture
def api(settings, make_runtime, monkeypatch):
    monkeypatch.setenv("TG_TEST_BOT_TOKEN", TOKEN)

    def build():
        runtime = make_runtime(StubModel({}))
        return TestClient(create_app(settings, checks={}, runtime=runtime)), runtime

    return build


def auth() -> dict:
    return {"Authorization": f"tma {signed(auth_date=int(time.time()))}"}


async def test_the_skill_can_be_started_from_the_mini_app(api, session):
    client, runtime = api()
    url = "/api/miniapp/default/skills/idea-card/start"
    assert client.post(url).status_code == 401
    no_chat = client.post(url, headers=auth())
    assert (no_chat.status_code, no_chat.json()["error"]) == (409, "no_chat")
    await runtime.feed("default", command_update(ANNA, "/start"))
    ok = client.post(url, headers=auth())
    assert ok.status_code == 200 and ok.json() == {"started": True, "error": None}
    assert "Навык «Карточка идеи»" in last_message(session).text
    missing = client.post("/api/miniapp/default/skills/no-such/start", headers=auth())
    assert missing.status_code == 404
    assert (
        client.post("/api/miniapp/default/skills/BAD SLUG/start", headers=auth()).status_code == 404
    )
