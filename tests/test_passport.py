"""Slice 07: the profile card, the agent passport (versions) and the public card in the group."""

import asyncio
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from app.bot.publisher import GroupPublisher
from app.main import create_app
from app.profile.card import LINE_IDS, LINES, card_lines
from app.profile.fields import ENUM_CODES, Answer
from app.profile.privacy import is_clean, violations
from app.profile.service import InvalidAnswerError, NotReadyError, ProfileService
from tests.conftest import GROUP_ID, ROOT
from tests.fake_telegram import join_update, person
from tests.test_miniapp import TOKEN, signed

ANNA = person(7, "Anna", "Ivanova")
PATTERNS = ROOT / "config" / "privacy_patterns.yaml"


@pytest.fixture
async def user_id(runtime) -> int:
    row = await runtime.repo.upsert_user(
        "default", 7, role="member", first_name="Anna", last_name=None, username=None, lang="ru"
    )
    return row.id


async def fill(svc: ProfileService, uid: int, role: str = "business", own: dict | None = None):
    """Answer every question: the first option, the role as asked, own words where given."""
    own = own or {}
    view = await svc.view("default", uid)
    while view["question"] is not None:
        field = view["question"]["field"]
        if field in own:
            view = await svc.answer("default", uid, field, "custom", text=own[field])
        else:
            code = role if field == "role" else view["question"]["options"][0]["code"]
            view = await svc.answer("default", uid, field, "option", code)
    return view


def group_texts(session) -> list[str]:
    """Everything the bot wrote into the shared group, new posts and edits."""
    posts = [m.text for m in session.of("sendMessage") if m.chat_id == GROUP_ID]
    edits = [m.text for m in session.of("editMessageText") if m.chat_id == GROUP_ID]
    return posts + edits


# the privacy gate ----------
@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("+7 (999) 123-45-67", "contact"),
        ("звоните 89991234567", "contact"),
        ("pochta@mail.ru", "contact"),
        ("@arsen_ai", "contact"),
        ("t.me/abc", "contact"),
        ("мой сайт example.com", "contact"),
        ("мне 15 лет", "age"),
        ("мне пятнадцать лет", "age"),
        ("15-летний школьник", "age"),
        ("возраст 30", "age"),
        ("I am fifteen years old", "age"),
        ("бюджет 5000", "money"),
        ("50 000 рублей", "money"),
        ("$100", "money"),
        ("две тысячи долларов", "money"),
        ("зарплата около 100к", "money"),
    ],
)
def test_the_gate_stops_contacts_money_and_age(text, category):
    assert category in violations(text, PATTERNS)


def test_ordinary_words_pass_the_gate():
    for text in (
        "Свой бизнес или самозанятость",
        "Стабильный доход от своего дела",
        "Да, больше тысячи человек",
        "хочу сделать сайт для студии маникюра",
        "Мне нужен сайт",
        "сдать ОГЭ на 5",
        "Каждую неделю использую в работе",
    ):
        assert is_clean(text, PATTERNS), text


def test_every_option_of_a_public_line_passes_the_gate_in_both_languages():
    public_fields = [f for _, fields, public in LINES if public for f in fields]
    for lang in ("ru", "en"):
        texts = yaml.safe_load((ROOT / "locales" / f"{lang}.yaml").read_text(encoding="utf-8"))
        for field in public_fields:
            for i in range(1, 5):
                assert is_clean(texts[f"pq_{field}_o{i}"], PATTERNS), (lang, field, i)


# the card ----------
@pytest.mark.parametrize("role", ENUM_CODES["role"])
async def test_the_card_has_seven_or_eight_lines_for_every_role(runtime, user_id, role):
    view = await fill(runtime.profile("default"), user_id, role)
    lines = view["card"]["lines"]
    assert 6 <= len(lines) <= 8
    assert [line["id"] for line in lines] == [i for i in LINE_IDS if i in {x["id"] for x in lines}]
    assert all(line["label"] and line["text"] for line in lines)


async def test_the_card_appears_only_when_the_form_is_complete(runtime, user_id):
    svc = runtime.profile("default")
    assert (await svc.view("default", user_id))["card"] is None
    await svc.answer("default", user_id, "role", "option", "student")
    assert (await svc.view("default", user_id))["card"] is None
    assert (await fill(svc, user_id, "student"))["card"]["passport"] is None


async def test_unknown_answers_stay_on_the_card_as_dont_know(runtime, user_id):
    svc = runtime.profile("default")
    view = await svc.view("default", user_id)
    while view["question"] is not None:
        view = await svc.answer("default", user_id, view["question"]["field"], "unknown")
    lines = view["card"]["lines"]
    assert len(lines) >= 6 and all(line["text"] == "не знаю" for line in lines)


# the passport ----------
async def test_right_creates_passport_v1_once_and_posts_the_public_card(
    runtime, session, user_id, passport_store
):
    await runtime.feed("default", join_update(ANNA))  # the group topic
    svc = runtime.profile("default")
    await fill(svc, user_id, "business")
    result = await svc.confirm("default", user_id, "Anna")
    assert (result.version, result.created, result.published) == (1, True, True)
    assert result.view["card"]["passport"] == {"version": 1, "current": True, "published": True}

    again = await svc.confirm("default", user_id, "Anna")  # same profile: nothing new
    assert (again.version, again.created) == (1, False)
    assert len(passport_store.versions("default", user_id)) == 1

    (card,) = [m for m in session.of("sendMessage") if "Профиль участника" in m.text]
    assert card.chat_id == GROUP_ID and card.message_thread_id == 101  # the person's own topic
    assert "Профиль участника: Anna" in card.text and "• Кто:" in card.text
    snapshot = passport_store.latest("default", user_id).data
    assert (
        set(snapshot) == {"fields", "card", "public", "track", "skills"}
        and "role" in snapshot["fields"]
    )


async def test_two_simultaneous_confirmations_make_one_passport(runtime, user_id, passport_store):
    svc = runtime.profile("default")
    await fill(svc, user_id)
    results = await asyncio.gather(
        svc.confirm("default", user_id, "Anna"), svc.confirm("default", user_id, "Anna")
    )
    assert {r.version for r in results} == {1}
    assert len(passport_store.versions("default", user_id)) == 1


async def test_fix_reopens_one_line_and_a_new_confirmation_is_version_two(
    runtime, session, user_id, passport_store
):
    await runtime.feed("default", join_update(ANNA))
    svc = runtime.profile("default")
    await fill(svc, user_id, "business")
    await svc.confirm("default", user_id, "Anna")

    view = await svc.edit("default", user_id, "resources")
    assert view["card"] is None and view["question"]["field"] == "time_week"
    assert view["position"] == {"index": 1, "size": 2}  # only the two fields of that line
    view = await svc.answer("default", user_id, "time_week", "option", "o4")
    view = await svc.answer("default", user_id, "budget", "option", "o3")
    assert view["card"]["passport"]["current"] is False  # the card changed, not confirmed yet

    result = await svc.confirm("default", user_id, "Anna")
    assert (result.version, result.created) == (2, True)
    old, new = passport_store.versions("default", user_id)
    assert old.version == 1 and old.data["fields"]["time_week"]["code"] == "o1"  # v1 is kept
    assert new.version == 2 and new.data["fields"]["time_week"]["code"] == "o4"
    assert len([m for m in session.of("sendMessage") if "Профиль участника" in m.text]) == 1
    assert len(session.of("editMessageText")) == 1  # the same group message is updated


async def test_a_confirmation_needs_a_complete_profile_and_no_open_question(runtime, user_id):
    svc = runtime.profile("default")
    with pytest.raises(NotReadyError):
        await svc.confirm("default", user_id, "Anna")
    await fill(svc, user_id)
    await svc.edit("default", user_id, "role")
    with pytest.raises(NotReadyError):
        await svc.confirm("default", user_id, "Anna")
    with pytest.raises(InvalidAnswerError):
        await svc.edit("default", user_id, "nonsense")


async def test_without_a_group_topic_nothing_is_posted_and_it_is_retried_later(
    runtime, session, user_id
):
    svc = runtime.profile("default")
    await fill(svc, user_id)
    first = await svc.confirm("default", user_id, "Anna")
    assert (first.created, first.published) == (True, False) and not group_texts(session)
    await runtime.feed("default", join_update(ANNA))  # the person joins the group later
    second = await svc.confirm("default", user_id, "Anna")
    assert (second.version, second.created, second.published) == (1, False, True)
    assert any("Профиль участника" in t for t in group_texts(session))


# the leak test (K7) ----------
SECRETS = {
    "phone": "+7 999 123-45-67",
    "mail": "secret.person@mail.ru",
    "handle": "@secret_handle",
    "link": "https://secret-site.example.com",
    "money": "5 000 000 рублей",
    "age": "мне 15 лет",
}


async def test_money_contacts_and_age_never_reach_the_group(runtime, session, user_id):
    await runtime.feed("default", join_update(ANNA))
    svc = runtime.profile("default")
    own = {
        "role": f"фрилансер, пишите {SECRETS['mail']}",
        "goal_10w": f"заработать {SECRETS['money']}",
        "goal_year": f"{SECRETS['age']}, хочу вырасти",
        "idea": f"сайт, телефон {SECRETS['phone']}",
        "business": f"мой канал {SECRETS['handle']}",
        "audience": f"читают на {SECRETS['link']}",
        "experience": "опыт работы, мне пятнадцать лет",
        "time_week": SECRETS["age"],
        "budget": SECRETS["money"],
        "country": f"Москва, {SECRETS['phone']}",
    }
    await fill(svc, user_id, "business", own)
    result = await svc.confirm("default", user_id, "Anna")
    assert result.created

    posted = "\n".join(group_texts(session))
    assert posted  # something public was posted: the gate is not just silent
    for name, secret in SECRETS.items():
        assert secret not in posted, name
    for marker in ("999", "secret", "5 000", "15 лет", "пятнадцать", "Москва"):
        assert marker not in posted, marker
    assert violations(posted, PATTERNS) == []
    # the private lines (time, budget, country) are not in the group whatever they hold
    for label in ("Время и бюджет", "Страна и язык"):
        assert label not in posted
    # and the person's own private card still keeps what they said
    card = {line["id"]: line["text"] for line in result.view["card"]["lines"]}
    assert SECRETS["money"] in card["resources"] and "Москва" in card["country"]


async def test_option_answers_of_private_lines_are_not_published_either(runtime, session, user_id):
    await runtime.feed("default", join_update(ANNA))
    svc = runtime.profile("default")
    await fill(svc, user_id, "business")
    await svc.confirm("default", user_id, "Anna")
    posted = "\n".join(group_texts(session))
    for text in ("До 3 часов", "Почти нулевой", "Россия, по-русски", "Время и бюджет"):
        assert text not in posted


async def test_the_last_gate_holds_back_a_card_that_slipped_through(runtime, session, user_id):
    await runtime.feed("default", join_update(ANNA))
    publisher = GroupPublisher(runtime.service("default"), PATTERNS)
    before = len(session.of("sendMessage"))
    sent = await publisher.publish(
        "default", user_id, "Anna", [("Кто", f"звоните {SECRETS['phone']}")], None
    )
    assert sent is None and len(session.of("sendMessage")) == before


async def test_a_deleted_group_message_is_replaced_by_a_new_one(runtime, session, user_id):
    from aiogram.exceptions import TelegramBadRequest

    await runtime.feed("default", join_update(ANNA))
    svc = runtime.profile("default")
    await fill(svc, user_id)
    await svc.confirm("default", user_id, "Anna")
    original = session.make_request

    async def deleted(bot, method, timeout=None):
        if method.__api_method__ == "editMessageText":
            raise TelegramBadRequest(
                method=method, message="Bad Request: message to edit not found"
            )
        return await original(bot, method, timeout)

    session.make_request = deleted
    await svc.edit("default", user_id, "goal_year")
    await svc.answer("default", user_id, "goal_year", "option", "o2")
    result = await svc.confirm("default", user_id, "Anna")
    assert (result.version, result.published) == (2, True)
    assert len([m for m in session.of("sendMessage") if "Профиль участника" in m.text]) == 2


# the Mini App API ----------
def auth() -> dict:
    return {"Authorization": f"tma {signed(auth_date=int(time.time()))}"}


@pytest.fixture
def client(settings, runtime, monkeypatch):
    monkeypatch.setenv("TG_TEST_BOT_TOKEN", TOKEN)
    return TestClient(create_app(settings, checks={}, runtime=runtime))


def test_confirm_and_fix_work_through_the_api(client):
    base = "/api/miniapp/default/profile"
    assert client.post(f"{base}/confirm").status_code == 401
    assert client.post(f"{base}/confirm", headers=auth()).status_code == 409  # nothing to confirm

    view = client.get(base, headers=auth()).json()
    while view["question"] is not None:
        question = view["question"]
        code = "student" if question["field"] == "role" else question["options"][0]["code"]
        answer = {"field": question["field"], "kind": "option", "code": code}
        view = client.post(f"{base}/answer", json=answer, headers=auth()).json()
    assert view["card"]["passport"] is None and len(view["card"]["lines"]) >= 6

    done = client.post(f"{base}/confirm", headers=auth()).json()
    assert done["confirm"] == {"version": 1, "created": True, "published": False}
    assert done["profile"]["card"]["passport"]["version"] == 1

    fix = client.post(f"{base}/edit", json={"line": "goal_year"}, headers=auth()).json()
    assert fix["question"]["field"] == "goal_year" and fix["card"] is None
    bad = client.post(f"{base}/edit", json={"line": "zzz"}, headers=auth())
    assert bad.status_code == 422


def test_card_lines_follow_the_stored_order():
    answers = {"country": Answer("option", "x", "o1"), "role": Answer("option", "y", "student")}

    class Tr:
        def t(self, tenant, key, **values):
            return key

    assert [c.id for c in card_lines(Tr(), "default", answers)] == ["role", "country"]
