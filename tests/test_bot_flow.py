"""End-to-end flows through the real aiogram handlers against a recorded fake Telegram."""

import asyncio
import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import GROUP_ID, OWNER_ID, WEBHOOK_SECRET
from tests.fake_telegram import (
    BOT_USERNAME,
    callback_update,
    command_update,
    join_update,
    person,
    service_join_update,
)

ANNA = person(7, "Anna", "Ivanova")
BORIS = person(8, "Boris", None)
OWNER = person(OWNER_ID, "Arsen", None)


async def test_new_member_gets_a_topic_with_their_name_and_a_button(runtime, session):
    started = time.perf_counter()
    await runtime.feed("default", join_update(ANNA))
    assert time.perf_counter() - started < 5  # the criterion is five seconds end to end

    (topic,) = session.of("createForumTopic")
    assert topic.chat_id == GROUP_ID and topic.name == "Anna Ivanova"
    (welcome,) = session.of("sendMessage")
    assert welcome.chat_id == GROUP_ID and welcome.message_thread_id == 101
    (button,) = welcome.reply_markup.inline_keyboard[0]
    assert button.text == "Начать с моим агентом"
    assert button.url == f"https://t.me/{BOT_USERNAME}?start=welcome"


async def test_rejoin_and_duplicate_updates_do_not_create_a_second_topic(runtime, session):
    await runtime.feed("default", join_update(ANNA, update_id=1))
    await runtime.feed("default", service_join_update(ANNA, update_id=2))  # same join, other update
    await runtime.feed("default", join_update(ANNA, update_id=3))  # left and came back
    assert len(session.of("createForumTopic")) == 1
    assert len(session.of("sendMessage")) == 1


async def test_two_simultaneous_updates_for_one_person_create_one_topic(runtime, session):
    await asyncio.gather(
        runtime.feed("default", join_update(ANNA, update_id=1)),
        runtime.feed("default", service_join_update(ANNA, update_id=2)),
    )
    assert len(session.of("createForumTopic")) == 1


async def test_joins_in_other_chats_and_bots_are_ignored(runtime, session):
    await runtime.feed("default", join_update(ANNA, chat_id=-999))
    await runtime.feed(
        "default", join_update(person(9, "Robo", None, is_bot=True) | {"is_bot": True})
    )
    assert session.of("createForumTopic") == []


async def test_start_creates_four_private_topics_once(runtime, session):
    await runtime.feed("default", command_update(ANNA, "/start welcome"))
    names = [t.name for t in session.of("createForumTopic")]
    assert names == ["Профиль", "Навыки", "Проект", "Отчёты"]
    assert all(t.chat_id == ANNA["id"] for t in session.of("createForumTopic"))

    await runtime.feed("default", command_update(ANNA, "/start"))  # pressed the button again
    assert len(session.of("createForumTopic")) == 4
    assert "уже готово" in session.of("sendMessage")[-1].text


async def test_clients_without_private_topics_fall_back_to_the_project_command(runtime, session):
    session.private_topics_supported = False
    await runtime.feed("default", command_update(BORIS, "/start"))
    fallback = session.of("sendMessage")[-1]
    assert "/project" in fallback.text
    buttons = [b for row in fallback.reply_markup.inline_keyboard for b in row]
    assert [b.text for b in buttons] == ["Профиль", "Навыки", "Проект", "Отчёты"]

    await runtime.feed("default", callback_update(BORIS, buttons[2].callback_data))
    answer = session.of("answerCallbackQuery")[-1]
    assert answer.text == "Контекст: Проект" and not answer.show_alert
    user = await runtime.repo.get_user("default", BORIS["id"])
    assert user.active_context == "dm_project" and user.dm_topics_supported is False


async def test_topics_are_retried_after_the_owner_switches_threaded_mode_on(runtime, session):
    session.private_topics_supported = False
    await runtime.feed("default", command_update(BORIS, "/start"))
    assert session.of("createForumTopic") == [] or "/project" in session.of("sendMessage")[-1].text

    session.private_topics_supported = True  # threaded mode was enabled in BotFather
    await runtime.feed("default", command_update(BORIS, "/start"))
    assert [t.name for t in session.of("createForumTopic")][-4:] == [
        "Профиль",
        "Навыки",
        "Проект",
        "Отчёты",
    ]
    user = await runtime.repo.get_user("default", BORIS["id"])
    assert user.dm_topics_supported is True


async def test_old_or_unknown_buttons_explain_instead_of_failing(runtime, session):
    for data in ("v0:ctx:dm_profile", "garbage", "v1:ctx:dm_unknown", "v1:ctx:dm_profile"):
        await runtime.feed("default", callback_update(person(55, "Nobody", None), data))
    answers = session.of("answerCallbackQuery")
    assert len(answers) == 4
    assert all(
        "устарела" in a.text and a.show_alert for a in answers
    )  # last one: user never started


async def test_owner_commands_work_for_the_owner_only(runtime, session):
    await runtime.feed("default", command_update(ANNA, "/start"))
    session.calls.clear()

    await runtime.feed("default", command_update(OWNER, "/admin"))
    assert "Участников: 1" in session.of("sendMessage")[-1].text

    await runtime.feed("default", command_update(OWNER, "/members"))
    assert "Anna Ivanova (member)" in session.of("sendMessage")[-1].text

    for command in ("/admin", "/members"):
        session.calls.clear()
        await runtime.feed("default", command_update(ANNA, command))
        (reply,) = session.of("sendMessage")
        assert reply.text == "Эта команда доступна только руководителю студии."


async def test_the_role_comes_from_the_registry_not_from_the_name(runtime, session):
    impostor = person(900, "Arsen", None, username="owner")
    await runtime.feed("default", command_update(impostor, "/start"))
    await runtime.feed("default", command_update(impostor, "/admin"))
    assert "только руководителю" in session.of("sendMessage")[-1].text
    stored = await runtime.repo.get_user("default", 900)
    assert stored.role == "member"
    await runtime.feed("default", command_update(OWNER, "/start"))
    assert (await runtime.repo.get_user("default", OWNER_ID)).role == "owner"


async def test_menus_show_owner_commands_only_in_the_owner_chat(runtime, session):
    await runtime.service("default").sync_commands()
    default_menu, owner_menu = session.of("setMyCommands")
    assert [c.command for c in default_menu.commands] == ["start", "project", "help"]
    assert [c.command for c in owner_menu.commands] == [
        "start",
        "project",
        "help",
        "admin",
        "members",
    ]
    assert owner_menu.scope.chat_id == OWNER_ID


async def test_setup_registers_the_webhook_with_a_secret_and_the_needed_updates(runtime, session):
    await runtime.setup("default", "https://app.example.test/")
    (hook,) = session.of("setWebhook")
    assert hook.url == "https://app.example.test/telegram/webhook/default"
    assert hook.secret_token == WEBHOOK_SECRET
    assert "chat_member" in hook.allowed_updates


def _client(settings: Settings, runtime) -> TestClient:
    return TestClient(create_app(settings, checks={}, runtime=runtime))


def test_webhook_rejects_wrong_or_missing_secret(settings, runtime, session):
    client = _client(settings, runtime)
    body = command_update(ANNA, "/start")
    assert client.post("/telegram/webhook/default", json=body).status_code == 403
    wrong = {"X-Telegram-Bot-Api-Secret-Token": "nope"}
    assert client.post("/telegram/webhook/default", json=body, headers=wrong).status_code == 403
    assert session.calls == []


def test_webhook_fails_closed_without_a_configured_secret(settings, runtime):
    client = _client(settings.model_copy(update={"tg_webhook_secret": None}), runtime)
    assert client.post("/telegram/webhook/default", json={}).status_code == 503


def test_webhook_processes_an_update_and_rejects_unknown_tenants(settings, runtime, session):
    client = _client(settings, runtime)
    headers = {"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}
    ok = client.post(
        "/telegram/webhook/default", json=command_update(ANNA, "/start"), headers=headers
    )
    assert ok.status_code == 200 and len(session.of("createForumTopic")) == 4
    missing = client.post("/telegram/webhook/nobody", json={}, headers=headers)
    assert missing.status_code == 404


async def test_setup_survives_an_owner_who_has_not_written_to_the_bot_yet(runtime, session):
    session.known_chats = set()  # Telegram: "chat not found" for the owner's chat
    await runtime.setup("default", "https://app.example.test")
    assert len(session.of("setWebhook")) == 1  # the webhook is registered anyway
    menus = session.of("setMyCommands")
    assert len(menus) == 2 and menus[1].scope.chat_id == OWNER_ID  # tried, did not crash

    session.known_chats = {OWNER_ID}  # the owner presses /start
    session.calls.clear()
    await runtime.feed("default", command_update(OWNER, "/start"))
    (owner_menu,) = session.of("setMyCommands")
    assert [c.command for c in owner_menu.commands][-2:] == ["admin", "members"]
