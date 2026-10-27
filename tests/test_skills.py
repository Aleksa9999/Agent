"""Slice 05: the skill library, the catalog, and the owner's /skill_upload with "Publish"."""

import io
import re
import time
import zipfile

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import SkillVersion
from app.main import create_app
from app.skills.bundle import MAX_ARCHIVE_BYTES, read_bundle
from app.skills.catalog import BRANCH_ORDER, catalog_view
from skillkit.parse import check_bundle, parse_skill
from tests.conftest import OWNER_ID, ROOT
from tests.fake_telegram import callback_update, command_update, document_update, person
from tests.test_miniapp import TOKEN, signed

SKILLS = ROOT / "content" / "skills"
OWNER = person(OWNER_ID, "Arsen", None)
ANNA = person(7, "Anna", "Ivanova")


def library_text(slug: str) -> tuple[str, str]:
    folder = next(SKILLS.glob(f"*/{slug}"))
    return (
        (folder / "SKILL.md").read_text(encoding="utf-8"),
        (folder / "test.yaml").read_text(encoding="utf-8"),
    )


def make_zip(skill_md: str, test_yaml: str, folder: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{folder}SKILL.md", skill_md)
        archive.writestr(f"{folder}test.yaml", test_yaml)
    return buffer.getvalue()


def next_version(skill_md: str, version: str = "v2") -> str:
    return re.sub(r"^version: v\d", f"version: {version}", skill_md, count=1, flags=re.M)


def messages(session) -> list[str]:
    return [m.text for m in session.of("sendMessage")]


# the library and the catalog ---------------------------------------------------------------
def test_the_repository_library_is_loaded_and_loading_is_repeatable(skill_store, engine):
    assert skill_store.sync_repo(SKILLS, ["default"]) == 26  # second run changes nothing
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(SkillVersion)) == 26


def test_the_catalog_has_eight_directions_ten_branches_and_all_skills(skill_store):
    view = catalog_view(skill_store.catalog("default"))
    assert view["total"] == 26
    assert len(view["directions"]) == 8
    assert [b["id"] for b in view["branches"]] == list(BRANCH_ORDER)
    in_tree = [skill for branch in view["branches"] for skill in branch["skills"]]
    assert len(in_tree) == 26
    assert {b["id"] for b in view["branches"] if not b["skills"]} == {"design", "video-voice"}


def test_every_skill_shows_a_road_an_estimate_by_tier_and_how_it_unlocks(skill_store):
    view = catalog_view(skill_store.catalog("default"))
    for skill in [s for b in view["branches"] for s in b["skills"]]:
        assert skill["roads"] == ["agent", "self"], skill["slug"]
        assert [t["id"] for t in skill["estimate"]["tiers"]] == ["economy", "standard", "premium"]
        assert all(t["roles"] for t in skill["estimate"]["tiers"]), skill["slug"]
        assert skill["estimate"]["price_source"] == "model_catalog"
        assert 1 <= skill["unlock"]["min_level"] <= 6 and skill["unlock"]["proof"]


def test_the_catalog_endpoint_needs_signed_launch_data(settings, runtime, monkeypatch):
    monkeypatch.setenv("TG_TEST_BOT_TOKEN", TOKEN)
    with TestClient(create_app(settings, checks={}, runtime=runtime)) as client:
        url = "/api/miniapp/default/catalog"
        ok = client.get(url, headers={"Authorization": f"tma {signed(auth_date=int(time.time()))}"})
        assert ok.status_code == 200 and ok.json()["total"] == 26
        assert len(ok.json()["directions"]) == 8
        assert client.get(url).status_code == 401
        forged = signed("1:OTHER-TOKEN", auth_date=int(time.time()))
        assert client.get(url, headers={"Authorization": f"tma {forged}"}).status_code == 401
        other = client.get("/api/miniapp/nobody/catalog", headers={"Authorization": "tma x"})
        assert other.status_code == 404


# the shared validator ---------------------------------------------------------------------
def test_upload_uses_the_repository_validator_and_names_the_reason():
    text, tests = library_text("idea-card")
    assert check_bundle(text, tests)[0] == []
    broken = text.replace("## Отказы и границы", "## Что-то другое")
    errors, doc = check_bundle(broken, tests)
    assert doc and any("Отказы и границы" in e for e in errors)


def test_a_test_file_outside_the_bundle_cannot_be_named():
    text, tests = library_text("idea-card")
    sneaky = text.replace("autotest: test.yaml", "autotest: ../../etc/passwd")
    assert check_bundle(sneaky, tests)[0]


def test_a_slug_is_checked_before_it_becomes_a_directory_name():
    text, tests = library_text("idea-card")
    assert check_bundle(text.replace("name: idea-card", "name: ../evil", 1), tests)[0]
    assert check_bundle(text.replace("branch: strategy", "branch: ../x", 1), tests)[0]


# reading the archive ----------------------------------------------------------------------
def test_the_archive_is_read_from_the_root_or_one_folder():
    text, tests = library_text("idea-card")
    for folder in ("", "idea-card/"):
        result = read_bundle(make_zip(text, tests, folder))
        assert (result.error, result.skill_md, result.test_yaml) == (None, text, tests)


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"not a zip", "not_zip"),
        (make_zip("a", "b") + b"", None),
    ],
)
def test_broken_archives_are_named(data, code):
    assert read_bundle(data).error == code


def test_archive_problems_are_named():
    def pack(**files: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, content in files.items():
                archive.writestr(name.replace("__", "/"), content)
        return buffer.getvalue()

    assert read_bundle(pack(**{"SKILL.md": "x"})).error == "missing_test"
    assert read_bundle(pack(**{"test.yaml": "x"})).error == "missing_skill"
    assert read_bundle(pack(a__SKILL_md="x")).error == "missing_skill"  # wrong file name
    twice = pack(**{"SKILL.md": "x", "test.yaml": "y", "b__SKILL.md": "z"})
    assert read_bundle(twice).error == "ambiguous"
    assert read_bundle(pack(**{"SKILL.md": "x" * 300_000, "test.yaml": "y"})).error == "too_big"
    many = pack(**{f"f{i}.txt": "x" for i in range(60)})
    assert read_bundle(many).error == "too_many_files"


def test_path_tricks_inside_the_archive_do_not_matter_because_nothing_is_unpacked():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../../escape/SKILL.md", "skill")
        archive.writestr("/abs/test.yaml", "tests")
    result = read_bundle(buffer.getvalue())
    assert (result.skill_md, result.test_yaml) == ("skill", "tests")  # read in memory only


# the owner's flow ------------------------------------------------------------------------
async def upload(runtime, session, user, data: bytes, caption=None, update_id=10):
    session.upload = data
    await runtime.feed("default", document_update(user, len(data), caption, update_id=update_id))


async def test_owner_uploads_a_new_version_and_it_reaches_the_catalog_only_after_publish(
    runtime, session, skill_store
):
    text, tests = library_text("idea-card")
    await runtime.feed("default", command_update(OWNER, "/skill_upload"))
    assert "Пришли архив" in messages(session)[-1]

    await upload(runtime, session, OWNER, make_zip(next_version(text), tests))
    checked = session.of("sendMessage")[-1]
    assert "прошёл проверку" in checked.text and "idea-card" in checked.text
    publish, cancel = checked.reply_markup.inline_keyboard[0]
    assert (publish.text, publish.style) == ("Опубликовать", "primary")
    assert skill_store.versions("default", "idea-card") == ["v1"]  # not in the catalog yet

    await runtime.feed("default", callback_update(OWNER, publish.callback_data, message_id=9))
    (answer,) = session.of("answerCallbackQuery")
    assert "опубликован" in answer.text
    assert skill_store.versions("default", "idea-card") == ["v1", "v2"]
    assert skill_store.get("default", "idea-card").version == "v2"  # the catalog shows the new one
    assert skill_store.get("default", "idea-card", "v1").version == "v1"  # the old one stays
    assert next(s for s in skill_store.catalog("default") if s.slug == "idea-card").version == "v2"


async def test_a_new_skill_appears_in_its_branch_after_publish(runtime, session, skill_store):
    text, tests = library_text("idea-card")
    new_skill = text.replace("name: idea-card", "name: demo-poster").replace(
        "branch: strategy", "branch: design"
    )
    tests = tests.replace("skill: idea-card", "skill: demo-poster")
    await upload(runtime, session, OWNER, make_zip(new_skill, tests), caption="/skill_upload")
    publish = session.of("sendMessage")[-1].reply_markup.inline_keyboard[0][0]
    await runtime.feed("default", callback_update(OWNER, publish.callback_data))
    view = catalog_view(skill_store.catalog("default"))
    design = next(b for b in view["branches"] if b["id"] == "design")
    assert [s["slug"] for s in design["skills"]] == ["demo-poster"] and view["total"] == 27


async def test_a_skill_with_a_format_error_is_not_published_and_the_reason_is_named(
    runtime, session, skill_store, engine
):
    text, tests = library_text("idea-card")
    await runtime.feed("default", command_update(OWNER, "/skill_upload"))
    broken = next_version(text).replace("## Отказы и границы", "## Что-то другое")
    await upload(runtime, session, OWNER, make_zip(broken, tests))
    reply = session.of("sendMessage")[-1]
    assert "не прошёл проверку" in reply.text and "Отказы и границы" in reply.text
    assert reply.reply_markup is None  # nothing to publish
    assert skill_store.versions("default", "idea-card") == ["v1"]
    with Session(engine) as s:
        assert (
            s.scalars(select(SkillVersion.status).where(SkillVersion.version == "v2")).all() == []
        )


async def test_a_version_that_is_not_newer_is_refused(runtime, session):
    text, tests = library_text("idea-card")
    await runtime.feed("default", command_update(OWNER, "/skill_upload"))
    await upload(runtime, session, OWNER, make_zip(text, tests))  # v1 again
    reply = session.of("sendMessage")[-1]
    assert "не новее" in reply.text and reply.reply_markup is None


async def test_cancel_drops_the_upload(runtime, session, skill_store):
    text, tests = library_text("idea-card")
    await runtime.feed("default", command_update(OWNER, "/skill_upload"))
    await upload(runtime, session, OWNER, make_zip(next_version(text), tests))
    cancel = session.of("sendMessage")[-1].reply_markup.inline_keyboard[0][1]
    await runtime.feed("default", callback_update(OWNER, cancel.callback_data))
    assert "отменена" in session.of("answerCallbackQuery")[-1].text
    assert skill_store.versions("default", "idea-card") == ["v1"]
    await runtime.feed("default", callback_update(OWNER, cancel.callback_data, update_id=11))
    assert "уже обработана" in session.of("answerCallbackQuery")[-1].text  # a second press


async def test_a_stale_pending_upload_cannot_override_a_newer_version(
    runtime, session, skill_store
):
    text, tests = library_text("idea-card")
    await runtime.feed("default", command_update(OWNER, "/skill_upload"))
    await upload(runtime, session, OWNER, make_zip(next_version(text, "v2"), tests))
    first = session.of("sendMessage")[-1].reply_markup.inline_keyboard[0][0]
    await runtime.feed("default", command_update(OWNER, "/skill_upload", update_id=12))
    await upload(runtime, session, OWNER, make_zip(next_version(text, "v3"), tests), update_id=13)
    second = session.of("sendMessage")[-1].reply_markup.inline_keyboard[0][0]
    await runtime.feed("default", callback_update(OWNER, second.callback_data, update_id=14))
    await runtime.feed("default", callback_update(OWNER, first.callback_data, update_id=15))
    assert "вышла версия" in session.of("answerCallbackQuery")[-1].text
    assert skill_store.versions("default", "idea-card") == ["v1", "v3"]


async def test_members_cannot_upload_or_publish(runtime, session, skill_store):
    text, tests = library_text("idea-card")
    await runtime.feed("default", command_update(ANNA, "/skill_upload"))
    assert "только руководителю" in messages(session)[-1]

    before = len(session.of("sendMessage"))
    await upload(runtime, session, ANNA, make_zip(next_version(text), tests))
    assert len(session.of("sendMessage")) == before  # a member's file is not our business
    await upload(runtime, session, ANNA, make_zip(next_version(text), tests), "/skill_upload", 11)
    assert "только руководителю" in messages(session)[-1]

    await runtime.feed("default", command_update(OWNER, "/skill_upload", update_id=12))
    await upload(runtime, session, OWNER, make_zip(next_version(text), tests), update_id=13)
    publish = session.of("sendMessage")[-1].reply_markup.inline_keyboard[0][0]
    await runtime.feed("default", callback_update(ANNA, publish.callback_data, update_id=14))
    assert session.of("answerCallbackQuery")[-1].show_alert is True
    assert skill_store.versions("default", "idea-card") == ["v1"]


async def test_a_file_without_the_command_is_not_treated_as_a_skill(runtime, session):
    text, tests = library_text("idea-card")
    await upload(runtime, session, OWNER, make_zip(next_version(text), tests))
    assert "/skill_upload" in messages(session)[-1]


async def test_a_big_or_broken_archive_gets_a_plain_answer(runtime, session):
    await runtime.feed("default", command_update(OWNER, "/skill_upload"))
    session.upload = b"x"
    await runtime.feed("default", document_update(OWNER, MAX_ARCHIVE_BYTES + 1, update_id=20))
    assert "слишком большой" in messages(session)[-1]
    await upload(runtime, session, OWNER, b"not a zip", update_id=21)
    assert "не .zip" in messages(session)[-1]


def test_tests_of_the_uploaded_skill_are_stored_with_its_version(skill_store):
    text, tests = library_text("idea-card")
    result = skill_store.add_pending("default", next_version(text), tests, OWNER_ID)
    assert result.pending_id and not result.errors
    assert yaml.safe_load(tests)["skill"] == parse_skill(text).slug
