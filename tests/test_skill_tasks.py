"""Slice 10: tasks with a coverage map, the estimate from the catalog, the prompt pack."""

import pytest
import yaml

from app.agent.catalog import ModelCatalog
from app.agent.tools import ToolRegistry
from app.agent.types import ToolCall
from app.skills.runs import RunScope
from app.skills.tasks import TaskError, validate_pack, validate_tasks
from tests.conftest import ROOT
from tests.fake_telegram import callback_update, command_update
from tests.stubs import StubModel, call, say
from tests.test_skill_run import ANNA, SPEC, keyboard_of, last_message, start_skill

RULES = yaml.safe_load((ROOT / "config" / "spec_rules.yaml").read_text(encoding="utf-8"))

TASKS = {
    "tasks": [
        {
            "title": "Каркас и вход",
            "what": "Человек открывает сайт студии и видит главную страницу",
            "blocked_by": [],
            "criteria": [],
        },
        {
            "title": "Форма записи",
            "what": "Человек отправляет заявку, владелец получает её в Telegram",
            "blocked_by": [1],
            "criteria": [1],
        },
        {
            "title": "Мобильная вёрстка",
            "what": "Страница на телефоне открывается без горизонтальной прокрутки",
            "blocked_by": [1],
            "criteria": [2],
        },
    ]
}
GAP = {"tasks": [{**TASKS["tasks"][1], "blocked_by": []}]}  # К2 is closed by nothing


def pack(**change) -> dict:
    base = {
        "steps": ["Откройте проект в Claude Code", "Идите по срезам по порядку"],
        "rules": ["Отвечай по-русски и коротко"],
        "prompts": [
            {
                "task": task["n"] if "n" in task else i,
                "goal": "Сделать так, чтобы человек видел результат среза",
                "context": "Прочитай CLAUDE.md и описание среза выше",
                "constraints": "Не трогай чужие файлы и не меняй зависимости",
                "checks": "Запусти тесты и открой страницу на телефоне",
            }
            for i, task in enumerate(TASKS["tasks"], start=1)
        ],
    }
    return {**base, **change}


PLAN_SPEC = {"criteria": SPEC["criteria"]}


# validation -------------------------------------------------------------------------------
def test_a_good_breakdown_gets_a_coverage_map_and_no_gaps():
    plan = validate_tasks(TASKS, PLAN_SPEC, RULES)
    assert plan["coverage"] == {"1": [2], "2": [3]} and plan["uncovered"] == []
    assert [t["n"] for t in plan["tasks"]] == [1, 2, 3]


def test_a_criterion_that_nothing_closes_is_reported_not_hidden():
    plan = validate_tasks(GAP, PLAN_SPEC, RULES)
    assert plan["uncovered"] == [2] and plan["coverage"]["2"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"tasks": []},
        {"tasks": "text"},
        {"tasks": [{**TASKS["tasks"][0], "title": "Да"}]},
        {"tasks": [{**TASKS["tasks"][0], "what": "коротко"}]},
        {"tasks": [{**TASKS["tasks"][0], "blocked_by": [1]}]},  # waits for itself
        {"tasks": [{**TASKS["tasks"][0], "blocked_by": [2]}, TASKS["tasks"][1]]},  # a later task
        {"tasks": [{**TASKS["tasks"][0], "criteria": [5]}]},  # no such criterion
        {"tasks": [{**TASKS["tasks"][0], "criteria": ["1"]}]},
        {"tasks": [TASKS["tasks"][0]] * 13},
    ],
)
def test_a_broken_breakdown_goes_back_to_the_model(change):
    with pytest.raises(TaskError):
        validate_tasks(change, PLAN_SPEC, RULES)


def test_the_pack_needs_a_prompt_for_every_task_and_holds_no_code():
    plan = validate_tasks(TASKS, PLAN_SPEC, RULES)
    assert [p["task"] for p in validate_pack(pack(), plan, RULES)["prompts"]] == [1, 2, 3]
    one_missing = pack()["prompts"][:2]
    code = pack()
    code["prompts"][0]["checks"] = "Запусти\n```python\nprint(1)\n```"
    short = pack()
    short["prompts"][1]["goal"] = "коротко"
    unknown = pack()
    unknown["prompts"][2]["task"] = 9
    repeated = pack()
    repeated["prompts"][2]["task"] = 1
    for bad in (
        pack(prompts=one_missing),
        code,
        short,
        unknown,
        repeated,
        pack(steps=[]),
        pack(rules=[]),
    ):
        with pytest.raises(TaskError):
            validate_pack(bad, plan, RULES)


# order of the phases -------------------------------------------------------------------------
@pytest.fixture
async def scope(runtime):
    await runtime.feed("default", command_update(ANNA, "/start"))
    anna = await runtime.repo.get_user("default", 7)
    run, _ = await runtime.runs("default").start("default", anna.id, "site-with-ai")
    await runtime.runs("default").choose_road("default", run.id, "agent")
    tools = ToolRegistry(
        model=StubModel({}),
        catalog=ModelCatalog([]),
        translator=runtime.translator,
        tenant_id="default",
        prompts_dir=ROOT / "prompts",
    )
    return tools, RunScope(runtime.runs("default"), "default", run.id), run


async def test_tasks_wait_for_the_spec_and_the_pack_waits_for_the_tasks(scope):
    tools, run_scope, _ = scope
    early = await tools.run(ToolCall("c", "propose_tasks", TASKS), run_scope)
    assert early.tasks_text is None and "spec is not agreed" in early.text
    early_pack = await tools.run(ToolCall("c", "propose_pack", pack()), run_scope)
    assert early_pack.pack_text is None and "not agreed yet" in early_pack.text


async def test_the_tools_of_a_skill_cannot_write_or_run_project_code(scope):
    tools, run_scope, _ = scope
    assert {f.name for f in tools.specs(run_scope)} == {
        "ask_options",
        "run_research",
        "run_sandbox",  # calculations of the provider, not the project of the person
        "lookup_model_price",
        "record_decision",
        "propose_spec",
        "propose_tasks",
        "propose_pack",
    }


# the whole path in the chat ---------------------------------------------------------------------
async def run_to_tasks(make_runtime, session, tasks=TASKS, extra=()):
    model = StubModel(
        {"mentor": [call("propose_spec", SPEC), call("propose_tasks", tasks), *extra]}
    )
    runtime = make_runtime(model)
    await runtime.feed("default", command_update(ANNA, "/start"))
    await start_skill(runtime, session)
    spec_agree, _ = keyboard_of(last_message(session))
    await runtime.feed("default", callback_update(ANNA, spec_agree.callback_data, update_id=90))
    return runtime, model


async def test_the_breakdown_shows_the_coverage_map_and_is_saved_only_by_the_button(
    make_runtime, session, skill_run_store
):
    runtime, model = await run_to_tasks(make_runtime, session)
    shown = last_message(session)
    assert "Задачи навыка «Делаю сайт с ИИ»" in shown.text
    assert "2. Форма записи" in shown.text and "Блокируется: 1" in shown.text
    assert "Блокируется: ничем, можно брать сразу" in shown.text
    assert "Карта покрытия критериев" in shown.text and "К1 → 2" in shown.text
    assert "К2 → 3" in shown.text and "Не закрыто ничем" not in shown.text
    agree, fix = keyboard_of(shown)
    assert (agree.text, fix.text) == ("Согласен", "Поправить")
    anna = await runtime.repo.get_user("default", 7)
    run = skill_run_store.active("default", anna.id)
    assert run.tasks_status == "proposed" and run.spec_status == "saved"  # not saved yet
    assert "Agreed spec:" in model.requests[-1].instructions  # the agreed spec is in context


async def test_after_agree_the_estimate_comes_from_the_catalog_and_the_pack_arrives_as_a_file(
    make_runtime, session, skill_run_store
):
    runtime, model = await run_to_tasks(make_runtime, session, extra=[call("propose_pack", pack())])
    agree, _ = keyboard_of(last_message(session))
    await runtime.feed("default", callback_update(ANNA, agree.callback_data, update_id=91))

    messages = [m.text for m in session.of("sendMessage")]
    estimate = next(t for t in messages if "Смета для этой нарезки" in t)
    assert "Эконом:" in estimate and "Премиум:" in estimate and "не найдено" in estimate
    assert "Нарезка согласована и записана" in model.requests[-1].messages[-1].content

    (sent,) = session.of("sendDocument")
    assert sent.document.filename == "site-with-ai-pack.md"
    text = sent.document.data.decode("utf-8")
    for part in (
        "Пакет «пройти самому»: Делаю сайт с ИИ",
        "Порядок работы",
        "Правила для вашего Claude Code",
        "[ ] К1. На главной странице есть форма записи",
        "[ ] К2.",
        "Срез 1: Каркас и вход",
        "Срез 3: Мобильная вёрстка",
        "Цель:",
        "Контекст:",
        "Ограничения:",
        "Проверки:",
        "Ключи и пароли не вставляй",
    ):
        assert part in text, part
    assert "```" not in text  # no project code in the pack
    anna = await runtime.repo.get_user("default", 7)
    run = skill_run_store.active("default", anna.id)
    assert run.tasks_status == "saved" and run.phase == "pack" and run.pack_text == text
    assert "Пакет готов" in session.of("sendMessage")[-1].text


async def test_a_gap_is_shown_apart_and_needs_a_conscious_answer(
    make_runtime, session, skill_run_store
):
    runtime, _ = await run_to_tasks(make_runtime, session, GAP, extra=[say("Дальше")])
    shown = last_message(session)
    assert "Не закрыто ничем" in shown.text and "К2:" in shown.text
    assert "Это осознанное решение или пропуск?" in shown.text
    aware, add = keyboard_of(shown)
    assert (aware.text, add.text) == ("Осознанно, согласен", "Добавить срез")
    forged = aware.callback_data.replace(":aware:", ":ok:")  # "Agree" without answering the gap
    await runtime.feed("default", callback_update(ANNA, forged, update_id=92))
    assert session.of("answerCallbackQuery")[-1].show_alert is True
    anna = await runtime.repo.get_user("default", 7)
    assert skill_run_store.active("default", anna.id).tasks_status == "proposed"

    await runtime.feed("default", callback_update(ANNA, aware.callback_data, update_id=93))
    run = skill_run_store.active("default", anna.id)
    assert run.tasks_status == "saved"
    (decision,) = [d for d in run.decisions if d["by"] == "person"]
    assert decision["question"] == "Критерии К2 не закрыты ни одним срезом"
    assert decision["decision"] == "осознанно оставлено без среза"


async def test_add_a_slice_reopens_the_breakdown_and_an_old_button_is_dead(
    make_runtime, session, skill_run_store
):
    runtime, model = await run_to_tasks(
        make_runtime, session, GAP, extra=[call("propose_tasks", TASKS), say("Дальше")]
    )
    first = last_message(session)
    old_aware, add = keyboard_of(first)
    await runtime.feed("default", callback_update(ANNA, add.callback_data, update_id=92))
    assert "Нужно добавить срез" in model.requests[-1].messages[-1].content
    anna = await runtime.repo.get_user("default", 7)
    run = skill_run_store.active("default", anna.id)
    assert run.tasks_status == "proposed" and run.tasks_rev == 2  # a new proposal came
    await runtime.feed("default", callback_update(ANNA, old_aware.callback_data, update_id=93))
    assert session.of("answerCallbackQuery")[-1].show_alert is True
    assert skill_run_store.active("default", anna.id).tasks_status == "proposed"


async def test_a_pack_with_code_is_rejected_and_the_model_gets_to_fix_it(
    make_runtime, session, skill_run_store
):
    bad = pack()
    bad["prompts"][0]["checks"] = "Запусти\n```sh\nrm -rf /\n```"
    runtime, model = await run_to_tasks(
        make_runtime, session, extra=[call("propose_pack", bad), call("propose_pack", pack())]
    )
    agree, _ = keyboard_of(last_message(session))
    await runtime.feed("default", callback_update(ANNA, agree.callback_data, update_id=91))
    assert len(session.of("sendDocument")) == 1  # only the clean pack was sent
    rejected = [m.content for m in model.requests[-1].messages if m.role == "tool"]
    assert any("pack rejected" in text and "no code blocks" in text for text in rejected)
