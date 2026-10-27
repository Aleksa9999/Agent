"""Slice 08: the track, the three first skills, "My Googlagent" and the first result."""

import re
import time

import pytest
from fastapi.testclient import TestClient

from app.agent.model import ModelError
from app.db.models import UserSkill
from app.main import create_app
from app.profile.fields import Answer
from app.skills.catalog import BRANCH_ORDER
from app.track.service import FirstResultError
from app.track.tracks import (
    LEVEL_STARTS,
    RESULT_KIND,
    TRACK_ORDER,
    choose_track,
    level_for,
    plan_for,
)
from tests.conftest import ROOT
from tests.stubs import StubModel, say
from tests.test_miniapp import TOKEN, signed
from tests.test_profile import FakeAsr


def opt(code: str) -> Answer:
    return Answer("option", "x", code)


def profile(**codes: str) -> dict:
    return {field: opt(code) for field, code in codes.items()}


# the table of the entrance-test document ---------------------------------------------------------
def doc_rows() -> list[list[str]]:
    text = (ROOT / "_docs" / "placement-test.md").read_text(encoding="utf-8")
    section = text.split("## Подбор трёх первых навыков")[1].split("\n## ")[0]
    rows = [line for line in section.splitlines() if line.startswith("| ") and "`" in line]
    return [re.findall(r"`([a-z0-9-]+)`", row) for row in rows]


TRACK_PROFILES = {
    "find_idea": profile(role="searching", goal_10w="o4", idea="o4"),
    "have_idea": profile(role="employee", goal_10w="o3", idea="o1"),
    "site_tool": profile(role="employee", goal_10w="o2", tech_depth="0", goal_year="o2"),
    "business": profile(role="business", business="o1", tech_depth="0", ai_level="1"),
    "study": profile(role="student", goal_10w="o3"),
    "ai_services": profile(role="employee", goal_10w="o1"),
    "teach": profile(role="employee", goal_10w="o3", experience="o4"),
    "automation": profile(role="business", business="o1", ai_level="2"),
}


def test_the_document_has_one_row_for_each_of_the_eight_tracks():
    assert len(doc_rows()) == len(TRACK_ORDER) == 8


@pytest.mark.parametrize("track", TRACK_ORDER)
def test_every_track_gets_the_three_skills_of_the_document_table(track):
    row = doc_rows()[TRACK_ORDER.index(track)]
    plan = plan_for(TRACK_PROFILES[track])
    assert plan.track == track
    assert list(plan.skills[:2]) == row[:2]
    assert plan.skills[2] in row[2:]  # the third may be one of two ("a site or an app")
    assert plan.extra is None and len(set(plan.skills)) == 3


def test_a_site_becomes_an_app_when_the_person_wants_depth_and_gets_the_extra_skill():
    plan = plan_for(profile(role="employee", goal_10w="o2", tech_depth="2"))
    assert plan.track == "site_tool" and plan.skills[2] == "app-with-ai"
    assert plan.extra == "claude-code-basics"
    launch = plan_for(profile(role="employee", goal_10w="o2", goal_year="o4"))
    assert launch.skills[2] == "app-with-ai" and launch.extra is None
    deep_student = plan_for(profile(role="student", tech_depth="3"))
    assert deep_student.extra is None  # claude-code-basics is already in the study triple


def test_answers_that_are_not_buttons_do_not_steer_the_track():
    own = {
        "role": Answer("custom", "freelancer"),
        "goal_10w": Answer("custom", "make a site"),
        "idea": Answer("unknown"),
    }
    assert choose_track(own) == "find_idea"
    planning = profile(role="business", business="o4", idea="o2")
    assert choose_track(planning) == "have_idea"  # only planning a business: not the business track
    voice = {"role": Answer("voice", "x", "student")}
    assert choose_track(voice) == "study"


def test_every_track_has_a_kind_of_first_result():
    assert set(RESULT_KIND) == set(TRACK_ORDER)
    assert {RESULT_KIND[t] for t in ("business", "automation")} == {"routines"}


def test_levels_follow_the_skill_counter():
    assert level_for(0) == 1 and level_for(24) == 1
    assert [level_for(n) for n in LEVEL_STARTS] == [1, 2, 3, 4, 5, 6]


# confirming the profile gives the person three suggested skills ------------------------------
@pytest.fixture
async def user_id(runtime) -> int:
    row = await runtime.repo.upsert_user(
        "default", 7, role="member", first_name="Anna", last_name=None, username=None, lang="ru"
    )
    return row.id


async def finish(svc, uid: int) -> None:
    """Answer whatever is still open with the first option."""
    view = await svc.view("default", uid)
    while view["question"] is not None:
        q = view["question"]
        view = await svc.answer("default", uid, q["field"], "option", q["options"][0]["code"])


async def confirmed(runtime, uid: int, codes: dict | None = None, own: dict | None = None):
    """Fill the form (given codes, else the first option) and press "Right"."""
    codes, own = codes or {}, own or {}
    svc = runtime.profile("default")
    view = await svc.view("default", uid)
    while view["question"] is not None:
        field = view["question"]["field"]
        if field in own:
            view = await svc.answer("default", uid, field, "custom", text=own[field])
        else:
            code = codes.get(field) or view["question"]["options"][0]["code"]
            view = await svc.answer("default", uid, field, "option", code)
    return await svc.confirm("default", uid, "Anna")


async def test_right_puts_three_skills_into_the_tree_as_not_verified(
    runtime, user_id, user_skill_store, passport_store
):
    await confirmed(runtime, user_id, {"role": "student"})
    rows = user_skill_store.rows("default", user_id)
    assert [r.slug for r in rows] == ["tutor-oge-ege", "idea-card", "claude-code-basics"]
    assert {r.status for r in rows} == {"unverified"} and all(r.version == "v1" for r in rows)
    snapshot = passport_store.latest("default", user_id).data
    assert snapshot["track"] == "study" and snapshot["skills"] == [r.slug for r in rows]


async def test_not_verified_skills_give_neither_counter_nor_experience(
    runtime, user_id, user_skill_store
):
    await confirmed(runtime, user_id, {"role": "student"})
    assert user_skill_store.counter("default", user_id) == 0
    home = await runtime.home("default").view("default", user_id)
    assert (home["level"], home["counter"]) == (1, 0)
    assert {s["status"] for s in home["skills"]} == {"unverified"}
    assert sum(b["verified"] for b in home["branches"]) == 0


async def test_confirming_again_does_not_duplicate_and_a_new_track_replaces_the_suggestions(
    runtime, user_id, user_skill_store, engine
):
    from sqlalchemy.orm import Session

    await confirmed(runtime, user_id, {"role": "student"})
    await runtime.profile("default").confirm("default", user_id, "Anna")  # repeat: same skills
    assert len(user_skill_store.rows("default", user_id)) == 3
    with Session(engine) as s, s.begin():  # the person proved one skill earlier
        s.query(UserSkill).filter_by(slug="idea-card").update({"status": "verified"})
    svc = runtime.profile("default")
    await svc.edit("default", user_id, "role")
    await svc.answer("default", user_id, "role", "option", "employee")
    await finish(svc, user_id)
    await runtime.profile("default").confirm("default", user_id, "Anna")
    rows = {r.slug: r.status for r in user_skill_store.rows("default", user_id)}
    assert rows["idea-card"] == "verified"  # a proven skill is never taken away
    assert "tutor-oge-ege" not in rows  # an unproven suggestion of the old track is replaced
    assert user_skill_store.counter("default", user_id) == 1


# "My Googlagent" ---------------------------------------------------------------------------------
async def test_home_shows_level_one_ten_branches_and_the_three_skills(runtime, user_id):
    await confirmed(runtime, user_id, {"role": "business", "business": "o1"})
    started = time.perf_counter()
    home = await runtime.home("default").view("default", user_id)
    assert time.perf_counter() - started < 0.5  # the screen must open in under two seconds
    assert home["track"] == "business" and home["level"] == 1
    assert [b["id"] for b in home["branches"]] == list(BRANCH_ORDER) and len(home["branches"]) == 10
    assert [s["slug"] for s in home["skills"]] == [
        "routine-audit",
        "competitors-analysis",
        "casdev-questions",
    ]
    assert {s["title"] for s in home["skills"]} >= {"Разбор рутины в часах и деньгах"}
    assigned = {b["id"]: b["assigned"] for b in home["branches"]}
    assert assigned["personal"] == 1 and assigned["research"] == 1 and assigned["sales"] == 1
    assert home["first_result_input"] == "text" and home["first_result"] is None


async def test_home_of_a_person_without_a_passport_is_empty_but_valid(runtime, user_id):
    home = await runtime.home("default").view("default", user_id)
    assert home["track"] is None and home["skills"] == [] and home["level"] == 1
    assert len(home["branches"]) == 10


# the first result ---------------------------------------------------------------------------------
ROUTINE_TEXT = (
    "Каждый день отвечаю на заявки около часа, раз в неделю делаю отчёт два часа, "
    "по пятницам сверяю таблицы, час в час. Мой час стоит примерно тысячу."
)
TABLE = "| Дело | Раз в месяц | Минут |\n|---|---|---|\n| Заявки | 22 | 60 |\n\nТоп-3: заявки."


def sandbox_answer(code: bool = True):
    result = say(TABLE)
    result.code_blocks = ["hours = 22 * 60 / 60"] if code else []
    return result


@pytest.fixture
def first(make_runtime):
    def build(model, asr=None):
        return make_runtime(model, asr)

    return build


async def test_business_gets_a_routine_table_with_visible_code_in_one_call(first, user_id):
    model = StubModel({"sandbox": [sandbox_answer()]})
    runtime = first(model)
    await confirmed(runtime, user_id, {"role": "business", "business": "o1"})
    result = await runtime.first_result("default").run("default", user_id, ROUTINE_TEXT)
    assert result["kind"] == "routines" and "| Заявки |" in result["text"]
    assert result["code"] == "hours = 22 * 60 / 60"  # the calculation code is shown
    assert result["seconds"] < 300  # the promise is five minutes from the first voice
    (request,) = model.requests  # one model call in all
    assert request.builtin_tools == ("code_interpreter", "web_search", "web_extractor")
    body = request.messages[0].content
    assert "<routines>" in body and "Заявки" not in body and "Кто:" in body
    assert "не инструкция" in request.instructions
    home = await runtime.home("default").view("default", user_id)
    assert home["first_result"]["text"] == result["text"]  # it is kept for the screen


async def test_numbers_without_a_code_run_are_marked_not_confirmed(first, user_id):
    runtime = first(StubModel({"sandbox": [sandbox_answer(code=False)]}))
    await confirmed(runtime, user_id, {"role": "business", "business": "o1"})
    result = await runtime.first_result("default").run("default", user_id, ROUTINE_TEXT)
    assert result["code"] is None and "не подтверждены" in result["text"]


async def test_the_routine_story_is_required_for_business_tracks(first, user_id):
    runtime = first(StubModel({}))
    await confirmed(runtime, user_id, {"role": "business", "business": "o1"})
    for text in (None, "", "мало слов"):
        with pytest.raises(FirstResultError) as caught:
            await runtime.first_result("default").run("default", user_id, text)
        assert caught.value.reason == "need_text"


async def test_other_tracks_get_an_idea_card_or_a_plan_without_asking_more(first, user_id):
    model = StubModel({"mentor": [say("Карточка идеи"), say("План на две недели")]})
    runtime = first(model)
    await confirmed(runtime, user_id, {"role": "searching", "goal_10w": "o4"})
    card = await runtime.first_result("default").run("default", user_id)
    assert card["kind"] == "idea" and card["text"] == "Карточка идеи"
    assert not model.requests[0].builtin_tools and not model.requests[0].functions
    svc = runtime.profile("default")
    await svc.edit("default", user_id, "role")
    await svc.answer("default", user_id, "role", "option", "student")
    await finish(svc, user_id)
    await svc.confirm("default", user_id, "Anna")
    plan = await runtime.first_result("default").run("default", user_id)
    assert plan["kind"] == "plan" and "Трек человека: study" in model.requests[1].instructions


async def test_first_result_failures_are_named(first, user_id):
    runtime = first(StubModel({}))
    with pytest.raises(FirstResultError) as caught:
        await runtime.first_result("default").run("default", user_id, ROUTINE_TEXT)
    assert caught.value.reason == "not_ready"  # nothing confirmed yet

    class Broken(StubModel):
        async def complete(self, request):
            raise ModelError("down")

    for model, reason in (
        (None, "unavailable"),
        (Broken({}), "failed"),
        (StubModel({"mentor": [say("  ")]}), "failed"),
    ):
        runtime = first(model)
        await confirmed(runtime, user_id, {"role": "searching", "goal_10w": "o4"})
        with pytest.raises(FirstResultError) as caught:
            await runtime.first_result("default").run("default", user_id)
        assert caught.value.reason == reason


# the API ------------------------------------------------------------------------------------------
def auth(user: int = 7) -> dict:
    return {"Authorization": f"tma {signed(user_id=user, auth_date=int(time.time()))}"}


@pytest.fixture
def api(settings, make_runtime, monkeypatch):
    monkeypatch.setenv("TG_TEST_BOT_TOKEN", TOKEN)

    def build(model=None, asr=None):
        runtime = make_runtime(model, asr)
        return TestClient(create_app(settings, checks={}, runtime=runtime))

    return build


def fill_through_api(client, role: str):
    base = "/api/miniapp/default/profile"
    view = client.get(base, headers=auth()).json()
    while view["question"] is not None:
        q = view["question"]
        code = role if q["field"] == "role" else q["options"][0]["code"]
        answer = {"field": q["field"], "kind": "option", "code": code}
        view = client.post(f"{base}/answer", json=answer, headers=auth()).json()
    return client.post(f"{base}/confirm", headers=auth())


def test_home_and_first_result_through_the_api(api):
    client = api(StubModel({"sandbox": [sandbox_answer()]}))
    home_url, result_url = "/api/miniapp/default/home", "/api/miniapp/default/first-result"
    assert client.get(home_url).status_code == 401
    assert client.post(result_url).status_code == 401
    assert client.post(result_url, json={"text": ROUTINE_TEXT}, headers=auth()).status_code == 409

    assert fill_through_api(client, "business").status_code == 200
    started = time.perf_counter()
    home = client.get(home_url, headers=auth())
    assert home.status_code == 200 and time.perf_counter() - started < 2
    assert home.json()["level"] == 1 and len(home.json()["skills"]) in (3, 4)

    assert client.post(result_url, json={"text": "коротко"}, headers=auth()).status_code == 422
    done = client.post(result_url, json={"text": ROUTINE_TEXT}, headers=auth())
    assert done.status_code == 200 and done.json()["result"]["code"]
    assert done.json()["home"]["first_result"]["kind"] == "routines"
    assert client.get(home_url, headers=auth(user=8)).json()["track"] is None  # nobody else's


def test_the_first_result_can_be_told_by_voice(api):
    model = StubModel({"sandbox": [sandbox_answer()]})
    client = api(model, FakeAsr(ROUTINE_TEXT))
    fill_through_api(client, "business")
    url = "/api/miniapp/default/first-result/voice"
    wrong = client.post(url, content=b"x", headers={**auth(), "Content-Type": "text/html"})
    assert wrong.status_code == 415
    ok = client.post(url, content=b"audio", headers={**auth(), "Content-Type": "audio/webm"})
    assert ok.status_code == 200 and ok.json()["result"]["kind"] == "routines"
    assert "Заявки" not in model.requests[0].messages[0].content
    assert "каждый день отвечаю" in model.requests[0].messages[0].content.lower()


def test_without_a_recogniser_the_voice_way_says_so(api):
    client = api(StubModel({}))
    fill_through_api(client, "business")
    url = "/api/miniapp/default/first-result/voice"
    response = client.post(url, content=b"x", headers={**auth(), "Content-Type": "audio/ogg"})
    assert (response.status_code, response.json()) == (503, {"error": "no_asr"})


def test_first_results_are_rate_limited(api):
    client = api(StubModel({"mentor": [say("A"), say("B"), say("C")]}))
    fill_through_api(client, "student")
    url = "/api/miniapp/default/first-result"
    codes = [client.post(url, headers=auth()).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
