"""The agent in Telegram: streamed answers, Standard A buttons, memory, stop, failures."""

import asyncio

import pytest
from aiogram import Bot
from aiogram.types import MessageGenerationStopped

from app.agent.model import ModelError
from app.agent.store import AgentStore
from app.bot import chat as chat_module
from app.bot.repo import BotRepo
from app.bot.runtime import BotRuntime
from app.i18n import Translator
from app.tenants import TenantRegistry
from tests.fake_telegram import callback_update, person, text_update
from tests.stubs import StubModel, call, say
from tests.test_agent_tools import option

ANNA = person(7, "Anna", "Ivanova")


@pytest.fixture(autouse=True)
def instant_drafts(monkeypatch):
    monkeypatch.setattr(chat_module, "DRAFT_INTERVAL_SECONDS", 0.0)


@pytest.fixture
def make_runtime(settings, engine, session):
    def build(model) -> BotRuntime:
        tenants = TenantRegistry.load(settings.tenants_dir)
        bot = Bot(token="123456:TESTTOKEN", session=session)
        return BotRuntime(
            settings=settings,
            tenants=tenants,
            translator=Translator(settings.locales_dir, tenants),
            repo=BotRepo(engine),
            store=AgentStore(engine),
            bot_factory=lambda tenant_id: bot,
            model_factory=lambda tenant_id: model,
        )

    return build


def sent_texts(session):
    return [m.text for m in session.of("sendMessage")]


async def test_the_answer_streams_as_a_draft_with_a_stop_button_then_is_sent_for_good(
    make_runtime, session
):
    runtime = make_runtime(StubModel({"mentor": [say("Давай начнём с карточки идеи")]}))
    await runtime.feed("default", text_update(ANNA, "Хочу сделать приложение"))
    drafts = session.of("sendMessageDraft")
    assert drafts and all(d.can_stop is True and d.draft_id > 0 for d in drafts)
    assert drafts[-1].text.startswith("Давай начнём")
    assert sent_texts(session)[-1] == "Давай начнём с карточки идеи"


async def test_when_drafts_are_unavailable_the_final_message_still_arrives(make_runtime, session):
    session.drafts_supported = False
    runtime = make_runtime(StubModel({"mentor": [say("Ответ без черновика")]}))
    await runtime.feed("default", text_update(ANNA, "привет"))
    assert sent_texts(session) == ["Ответ без черновика"]
    assert len(session.of("sendMessageDraft")) == 1  # tried once, then stopped trying


async def test_the_second_turn_remembers_the_first(make_runtime, session):
    model = StubModel({"mentor": [say("Первый ответ"), say("Второй ответ")]})
    runtime = make_runtime(model)
    await runtime.feed("default", text_update(ANNA, "Первый вопрос"))
    await runtime.feed("default", text_update(ANNA, "Второй вопрос", update_id=6))
    second = model.of("mentor")[1].messages
    assert [(m.role, m.content) for m in second] == [
        ("user", "Первый вопрос"),
        ("assistant", "Первый ответ"),
        ("user", "Второй вопрос"),
    ]
    assert (
        "Anna Ivanova" in model.of("mentor")[0].instructions
    )  # the person is in the passport layer


async def test_no_model_configured_says_so_politely(make_runtime, session):
    runtime = make_runtime(None)
    await runtime.feed("default", text_update(ANNA, "привет"))
    assert sent_texts(session) == ["Агент сейчас недоступен. Попробуй через минуту."]


async def test_a_model_failure_is_reported_without_details(make_runtime, session):
    class Broken(StubModel):
        def stream(self, request):
            raise ModelError("HTTP 500 sk-secret")

    runtime = make_runtime(Broken({}))
    await runtime.feed("default", text_update(ANNA, "привет"))
    assert sent_texts(session) == ["Не получилось ответить. Повтори сообщение чуть позже."]


def ask(options=None):
    return call(
        "ask_options",
        {
            "question": "Какой путь выбрать?",
            "options": options
            or [option("Лендинг", True), option("Бот"), option("Таблица"), option("Звонки")],
        },
    )


async def test_a_question_arrives_as_four_options_with_a_star_and_four_controls(
    make_runtime, session
):
    runtime = make_runtime(StubModel({"mentor": [ask()]}))
    await runtime.feed("default", text_update(ANNA, "С чего начать?"))
    question = session.of("sendMessage")[-1]
    rows = question.reply_markup.inline_keyboard
    assert [r[0].text for r in rows[:4]] == ["⭐ Лендинг", "Бот", "Таблица", "Звонки"]
    assert [b.text for r in rows[4:] for b in r] == [
        "✍️ Свой ответ",
        "🤷 Не знаю",
        "← Назад",
        "🔍 Сравнить",
    ]
    assert "Какой путь выбрать?" in question.text and "⭐ Лендинг" in question.text
    assert all(len(b.callback_data.encode()) <= 64 for r in rows for b in r)


async def test_choosing_an_option_closes_the_buttons_and_the_agent_continues(make_runtime, session):
    model = StubModel({"mentor": [ask(), say("Отлично, берём бота")]})
    runtime = make_runtime(model)
    await runtime.feed("default", text_update(ANNA, "С чего начать?"))
    chosen = session.of("sendMessage")[-1].reply_markup.inline_keyboard[1][0]
    await runtime.feed("default", callback_update(ANNA, chosen.callback_data, message_id=9))
    assert session.of("editMessageReplyMarkup")[-1].reply_markup is None
    assert model.of("mentor")[1].messages[-1].content == "Выбираю вариант «Бот»."
    assert sent_texts(session)[-1] == "Отлично, берём бота"
    # the same button again is stale: the question is closed
    await runtime.feed(
        "default", callback_update(ANNA, chosen.callback_data, message_id=9, update_id=8)
    )
    assert "устарела" in session.of("answerCallbackQuery")[-1].text


async def test_compare_shows_prices_pros_and_cons_and_keeps_the_question_open(
    make_runtime, session
):
    runtime = make_runtime(StubModel({"mentor": [ask()]}))
    await runtime.feed("default", text_update(ANNA, "С чего начать?"))
    compare = session.of("sendMessage")[-1].reply_markup.inline_keyboard[5][1]
    assert compare.text == "🔍 Сравнить"
    await runtime.feed("default", callback_update(ANNA, compare.callback_data, message_id=9))
    edited = session.of("editMessageText")[-1]
    assert (
        "Цена и срок: 500 RUB, 2 h" in edited.text
        and "+ fast" in edited.text
        and "- pricey" in edited.text
    )
    assert edited.reply_markup is not None  # still answerable


async def test_unknown_and_back_become_clear_instructions_for_the_agent(make_runtime, session):
    model = StubModel({"mentor": [ask(), say("беру рекомендованный"), ask(), say("вернулся")]})
    runtime = make_runtime(model)
    await runtime.feed("default", text_update(ANNA, "вопрос"))
    unknown = session.of("sendMessage")[-1].reply_markup.inline_keyboard[4][1]
    await runtime.feed("default", callback_update(ANNA, unknown.callback_data, message_id=9))
    assert "возьми рекомендованный вариант" in model.of("mentor")[1].messages[-1].content
    await runtime.feed("default", text_update(ANNA, "ещё", update_id=10))
    back = session.of("sendMessage")[-1].reply_markup.inline_keyboard[5][0]
    await runtime.feed(
        "default", callback_update(ANNA, back.callback_data, message_id=10, update_id=11)
    )
    assert "на шаг назад" in model.of("mentor")[3].messages[-1].content


async def test_my_own_answer_takes_the_next_message_as_the_answer(make_runtime, session):
    model = StubModel({"mentor": [ask(), say("принято: свой вариант")]})
    runtime = make_runtime(model)
    await runtime.feed("default", text_update(ANNA, "вопрос"))
    custom = session.of("sendMessage")[-1].reply_markup.inline_keyboard[4][0]
    await runtime.feed("default", callback_update(ANNA, custom.callback_data, message_id=9))
    assert "своим сообщением" not in session.of("answerCallbackQuery")[-1].text  # plain prompt
    assert session.of("answerCallbackQuery")[-1].text == "Напиши свой вариант одним сообщением."
    await runtime.feed("default", text_update(ANNA, "Сделаю рассылку", update_id=12))
    assert model.of("mentor")[1].messages[-1].content == "Сделаю рассылку"
    stored = await runtime.store.awaiting_custom(
        "default", (await runtime.repo.get_user("default", 7)).id
    )
    assert stored is None


async def test_someone_elses_or_unknown_question_buttons_are_stale(make_runtime, session):
    runtime = make_runtime(StubModel({"mentor": [ask(), say("привет, Борис")]}))
    await runtime.feed("default", text_update(ANNA, "вопрос"))
    button = session.of("sendMessage")[-1].reply_markup.inline_keyboard[0][0]
    intruder = person(99, "Boris", None)
    await runtime.feed(
        "default", text_update(intruder, "привет")
    )  # creates the user, no model script left
    await runtime.feed("default", callback_update(intruder, button.callback_data, message_id=9))
    await runtime.feed("default", callback_update(ANNA, "v1:q:nope:o0", message_id=9, update_id=13))
    answers = session.of("answerCallbackQuery")
    assert all("устарела" in a.text and a.show_alert for a in answers[-2:])


async def test_the_stop_button_stops_only_the_matching_generation(make_runtime):
    runtime = make_runtime(StubModel({}))
    chat = runtime.chat("default")
    event = asyncio.Event()
    chat._active[7] = (55, event)
    other = MessageGenerationStopped.model_validate(
        {"chat": {"id": 7, "type": "private"}, "draft_id": 56}
    )
    chat.stop(other)
    assert not event.is_set()
    chat.stop(
        MessageGenerationStopped.model_validate(
            {"chat": {"id": 7, "type": "private"}, "draft_id": 55}
        )
    )
    assert event.is_set()


async def test_a_long_conversation_is_folded_and_the_summary_is_remembered(
    make_runtime, session, settings
):
    settings.context_budget_tokens = 1500
    settings.context_keep_last = 5
    model = StubModel({"mentor": [say("ок")], "summary": [say("раньше выбрали идею")]})
    runtime = make_runtime(model)
    await runtime.feed("default", text_update(ANNA, "начало"))  # creates the user
    model.script["mentor"].append(say("ок 2"))
    row = await runtime.repo.get_user("default", 7)
    last_id = 0
    for i in range(40):
        last_id = await runtime.store.add_message(
            "default",
            row.id,
            "dm_profile",
            "user" if i % 2 == 0 else "assistant",
            f"старое {i} " + "x" * 200,
        )
    await runtime.feed("default", text_update(ANNA, "продолжим", update_id=20))
    summary, upto = await runtime.store.get_summary("default", row.id, "dm_profile")
    assert summary == "раньше выбрали идею" and 0 < upto < last_id
    kept = await runtime.store.history("default", row.id, "dm_profile", after_id=upto)
    assert len(kept) >= 5  # the recent tail stays verbatim outside the summary


async def test_each_topic_keeps_its_own_conversation(make_runtime, session):
    model = StubModel({"mentor": [say("профиль"), say("навыки")]})
    runtime = make_runtime(model)
    from tests.fake_telegram import command_update

    await runtime.feed("default", command_update(ANNA, "/start"))
    topics = {t.name: 100 + i + 1 for i, t in enumerate(session.of("createForumTopic"))}
    await runtime.feed(
        "default", text_update(ANNA, "про профиль", thread_id=topics["Профиль"], update_id=30)
    )
    await runtime.feed(
        "default", text_update(ANNA, "про навыки", thread_id=topics["Навыки"], update_id=31)
    )
    second = model.of("mentor")[1].messages
    assert [m.content for m in second] == ["про навыки"]  # the profile talk is not mixed in
