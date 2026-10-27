"""Track and skills after the passport, the "My Googlagent" view, and the first result."""

import asyncio
import logging
import time
from pathlib import Path

from app.agent.model import ModelError, ModelPort
from app.agent.prompts import load_prompt
from app.agent.tools import SANDBOX_TOOLS
from app.agent.types import Message, ModelRequest
from app.db.base import utcnow
from app.i18n import Translator
from app.profile.card import card_lines
from app.profile.extract import clean_text
from app.profile.fields import Answer, Answers
from app.profile.passport import PassportRow, PassportStore
from app.skills.catalog import BRANCH_ORDER
from app.skills.store import SkillStore
from app.track.store import (
    VERIFIED,
    FirstResultStore,
    ResultRow,
    UserSkillStore,
)
from app.track.tracks import RESULT_KIND, TrackPlan, level_for, plan_for

log = logging.getLogger("app.track")
ROUTINES_MIN, ROUTINES_MAX = 30, 4000
MODEL_TIMEOUT_SECONDS = 150  # one call, far inside the five-minute promise


class FirstResultError(Exception):
    """`reason`: not_ready, need_text, unavailable, failed."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class TrackService:
    """Turns the confirmed profile into three suggested skills in the person's tree."""

    def __init__(self, *, skills: SkillStore, user_skills: UserSkillStore):
        self.skills = skills
        self.user_skills = user_skills

    @staticmethod
    def plan(answers: Answers) -> TrackPlan:
        return plan_for(answers)

    async def assign(self, tenant: str, user_id: int, plan: TrackPlan) -> list[str]:
        """Skills that are in the library get a row with status "not verified"."""
        items, slugs = [], [*plan.skills, *([plan.extra] if plan.extra else [])]
        for slug in slugs:
            doc = await asyncio.to_thread(self.skills.get, tenant, slug)
            if doc is None:
                log.warning("track skill %s is not in the catalog", slug)
                continue
            items.append((slug, doc.version))
        await asyncio.to_thread(self.user_skills.assign, tenant, user_id, items)
        return [slug for slug, _ in items]


def _answers(passport: PassportRow) -> Answers:
    return {f: Answer.from_json(a) for f, a in passport.data["fields"].items()}


class HomeService:
    """The "My Googlagent" screen: level, ten branches, the three skills, the first result."""

    def __init__(
        self,
        *,
        passports: PassportStore,
        user_skills: UserSkillStore,
        skills: SkillStore,
        results: FirstResultStore,
        voice_available: bool = False,
    ):
        self.passports = passports
        self.user_skills = user_skills
        self.skills = skills
        self.results = results
        self.voice_available = voice_available

    async def view(self, tenant: str, user_id: int) -> dict:
        return await asyncio.to_thread(self._view, tenant, user_id)

    def _view(self, tenant: str, user_id: int) -> dict:
        passport = self.passports.latest(tenant, user_id)
        rows = self.user_skills.rows(tenant, user_id)
        counter = self.user_skills.counter(tenant, user_id)
        known = {}
        for row in rows:
            doc = self.skills.get(tenant, row.slug, row.version)
            if doc is not None:
                known[row.slug] = (row, doc)
        in_plan = (passport.data.get("skills") if passport else None) or []
        skills = [
            {
                "slug": slug,
                "title": doc.title,
                "branch": doc.branch,
                "version": row.version,
                "status": row.status,
                "extra": slug not in in_plan[:3],
            }
            for slug, (row, doc) in known.items()
        ]
        branches = [
            {
                "id": branch,
                "assigned": sum(1 for s in skills if s["branch"] == branch),
                "verified": sum(
                    1 for s in skills if s["branch"] == branch and s["status"] == VERIFIED
                ),
            }
            for branch in BRANCH_ORDER
        ]
        track = passport.data.get("track") if passport else None
        result = self.results.get(tenant, user_id, passport.version) if passport else None
        return {
            "track": track,
            "level": level_for(counter),
            "counter": counter,
            "branches": branches,
            "skills": skills,
            "first_result": _result_view(result),
            "first_result_input": "text" if track and RESULT_KIND[track] == "routines" else "none",
            "voice_available": self.voice_available,
        }


def _result_view(result: ResultRow | None) -> dict | None:
    if result is None:
        return None
    return {
        "kind": result.kind,
        "track": result.track,
        "text": result.content,
        "code": result.code,
        "seconds": round(result.seconds, 1),
    }


class FirstResultService:
    """One model call that produces the first useful result for the person's track."""

    def __init__(
        self,
        *,
        passports: PassportStore,
        results: FirstResultStore,
        translator: Translator,
        prompts_dir: Path,
        model: ModelPort | None,
    ):
        self.passports = passports
        self.results = results
        self.tr = translator
        self.prompts_dir = prompts_dir
        self.model = model

    async def run(self, tenant: str, user_id: int, routines: str | None = None) -> dict:
        passport = await asyncio.to_thread(self.passports.latest, tenant, user_id)
        if passport is None:
            raise FirstResultError("not_ready")
        if self.model is None:
            raise FirstResultError("unavailable")
        answers = _answers(passport)
        plan = plan_for(answers)
        kind = RESULT_KIND[plan.track]
        facts = "\n".join(f"{c.label}: {c.text}" for c in card_lines(self.tr, tenant, answers))
        if kind == "routines":
            story = clean_text(routines, ROUTINES_MAX) if routines else ""
            if len(story) < ROUTINES_MIN:
                raise FirstResultError("need_text")
            request = ModelRequest(
                mode="sandbox",
                instructions=load_prompt(self.prompts_dir, "first_result_routines.md"),
                messages=[Message("user", f"{facts}\n\n<routines>\n{story}\n</routines>")],
                builtin_tools=SANDBOX_TOOLS,
            )
        else:
            prompt = "first_result_idea.md" if kind == "idea" else "first_result_plan.md"
            request = ModelRequest(
                mode="mentor",
                instructions=load_prompt(self.prompts_dir, prompt, track=plan.track),
                messages=[Message("user", facts)],
            )
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self.model.complete(request), timeout=MODEL_TIMEOUT_SECONDS
            )
        except (ModelError, TimeoutError) as exc:
            log.warning("first result failed: %s", type(exc).__name__)
            raise FirstResultError("failed") from None
        seconds = time.monotonic() - started
        text = result.text.strip()
        if not text:
            raise FirstResultError("failed")
        code = "\n\n".join(result.code_blocks) if result.code_blocks else None
        if kind == "routines" and code is None:  # numbers without a run are not confirmed
            text += "\n\n" + self.tr.t(tenant, "sandbox_no_code")
        await asyncio.to_thread(
            self.results.save,
            tenant,
            user_id,
            passport.version,
            plan.track,
            kind,
            text,
            code,
            seconds,
        )
        row = ResultRow(passport.version, plan.track, kind, text, code, seconds, utcnow())
        return _result_view(row)
