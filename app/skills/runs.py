"""Going through a skill: the road, the interrogation journal and the spec.

The spec is shown to the person first and saved only when they press "Agree": the button is
handled in code (`agree`), the model cannot save it. Decisions the agent took for the person are
kept in a journal that is shown back to the model and to the person."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app.agent.prompts import load_prompt
from app.db.base import utcnow
from app.db.models import SkillRun
from app.i18n import Translator
from app.skills.store import SkillStore
from app.skills.tasks import (
    TaskError,
    render_pack,
    render_tasks,
    validate_pack,
    validate_tasks,
)
from skillkit.parse import PIPELINE_SECTION, RUN_SECTIONS, SkillDoc, section_texts

log = logging.getLogger("app.skills")

ACTIVE, PAUSED = "active", "paused"
ROADS = ("agent", "self")
BATCH_LIMIT = 5
PHASE_ROAD, PHASE_GRILL, PHASE_SPEC = "road", "grill", "spec"
PHASE_TASKS, PHASE_PACK = "tasks", "pack"
TASKS_NONE, TASKS_PROPOSED, TASKS_SAVED = "none", "proposed", "saved"
SPEC_NONE, SPEC_PROPOSED, SPEC_SAVED = "none", "proposed", "saved"
DECIDERS = ("person", "agent")
FIELD_LIMIT = 600


class SpecError(ValueError):
    """The proposal does not meet the rules. The text goes back to the model so that it fixes it."""


@dataclass(frozen=True)
class RunRow:
    id: int
    user_id: int
    slug: str
    version: str
    road: str | None
    phase: str
    status: str
    decisions: list[dict]
    spec: dict | None
    spec_text: str | None
    spec_status: str
    spec_rev: int
    tasks: dict | None
    tasks_text: str | None
    tasks_status: str
    tasks_rev: int
    pack_text: str | None
    batch_asked: int


def _row(r: SkillRun) -> RunRow:
    return RunRow(
        r.id,
        r.user_id,
        r.slug,
        r.version,
        r.road,
        r.phase,
        r.status,
        list(r.decisions or []),
        r.spec,
        r.spec_text,
        r.spec_status,
        r.spec_rev,
        r.tasks,
        r.tasks_text,
        r.tasks_status,
        r.tasks_rev,
        r.pack_text,
        r.batch_asked,
    )


def _clip(value: object, limit: int = FIELD_LIMIT) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


class SkillRunStore:
    def __init__(self, engine: Engine):
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def start(self, tenant_id: str, user_id: int, slug: str, version: str) -> RunRow:
        """The new current skill; a skill that was current before is paused, not lost."""
        with self._sessions.begin() as s:
            for old in s.scalars(
                select(SkillRun).where(
                    SkillRun.tenant_id == tenant_id,
                    SkillRun.user_id == user_id,
                    SkillRun.status == ACTIVE,
                )
            ):
                old.status = PAUSED
            run = SkillRun(
                tenant_id=tenant_id,
                user_id=user_id,
                slug=slug,
                version=version,
                phase=PHASE_ROAD,
                status=ACTIVE,
                decisions=[],
                spec_status=SPEC_NONE,
                spec_rev=0,
                tasks_status=TASKS_NONE,
                tasks_rev=0,
                batch_asked=0,
            )
            s.add(run)
            s.flush()
            return _row(run)

    def get(self, tenant_id: str, run_id: int) -> RunRow | None:
        with self._sessions() as s:
            run = s.get(SkillRun, run_id)
            return _row(run) if run and run.tenant_id == tenant_id else None

    def active(self, tenant_id: str, user_id: int) -> RunRow | None:
        with self._sessions() as s:
            run = s.scalar(
                select(SkillRun)
                .where(
                    SkillRun.tenant_id == tenant_id,
                    SkillRun.user_id == user_id,
                    SkillRun.status == ACTIVE,
                )
                .order_by(SkillRun.id.desc())
            )
            return _row(run) if run else None

    def _edit(self, tenant_id: str, run_id: int, change) -> RunRow | None:
        with self._sessions.begin() as s:
            run = s.get(SkillRun, run_id)
            if run is None or run.tenant_id != tenant_id:
                return None
            if change(run) is False:  # a refused change touches nothing
                return None
            run.updated_at = utcnow()
            s.flush()
            return _row(run)

    def set_road(self, tenant_id: str, run_id: int, road: str) -> RunRow | None:
        def change(run: SkillRun):
            if run.road is not None:
                return False  # the road is chosen once
            run.road, run.phase = road, PHASE_GRILL

        return self._edit(tenant_id, run_id, change)

    def add_decision(self, tenant_id: str, run_id: int, entry: dict) -> RunRow | None:
        def change(run: SkillRun):
            run.decisions = [*(run.decisions or []), entry]

        return self._edit(tenant_id, run_id, change)

    def count_question(self, tenant_id: str, run_id: int) -> int | None:
        """One more question in the current block; returns the new count."""
        counted: list[int] = []

        def change(run: SkillRun):
            run.batch_asked += 1
            counted.append(run.batch_asked)

        row = self._edit(tenant_id, run_id, change)
        return counted[0] if row else None

    def reset_batch(self, tenant_id: str, run_id: int) -> None:
        def change(run: SkillRun):
            run.batch_asked = 0

        self._edit(tenant_id, run_id, change)

    def propose(self, tenant_id: str, run_id: int, spec: dict, text: str) -> RunRow | None:
        def change(run: SkillRun):
            run.spec, run.spec_text = spec, text
            run.spec_status, run.phase = SPEC_PROPOSED, PHASE_SPEC
            run.spec_rev += 1  # a button of an earlier proposal no longer fits

        return self._edit(tenant_id, run_id, change)

    def agree(self, tenant_id: str, run_id: int, rev: int) -> RunRow | None:
        """Save the proposed spec the person is looking at (`rev`). Only a proposed spec can be
        saved, and only once."""

        def change(run: SkillRun):
            if run.spec_status != SPEC_PROPOSED or run.spec_rev != rev:
                return False
            run.spec_status = SPEC_SAVED

        return self._edit(tenant_id, run_id, change)

    def propose_tasks(self, tenant_id: str, run_id: int, plan: dict, text: str) -> RunRow | None:
        def change(run: SkillRun):
            if run.spec_status != SPEC_SAVED:
                return False  # no tasks before the spec is agreed
            run.tasks, run.tasks_text = plan, text
            run.tasks_status, run.phase = TASKS_PROPOSED, PHASE_TASKS
            run.tasks_rev += 1

        return self._edit(tenant_id, run_id, change)

    def agree_tasks(self, tenant_id: str, run_id: int, rev: int) -> RunRow | None:
        def change(run: SkillRun):
            if run.tasks_status != TASKS_PROPOSED or run.tasks_rev != rev:
                return False
            run.tasks_status = TASKS_SAVED

        return self._edit(tenant_id, run_id, change)

    def revise_tasks(self, tenant_id: str, run_id: int, rev: int) -> RunRow | None:
        def change(run: SkillRun):
            if run.tasks_status != TASKS_PROPOSED or run.tasks_rev != rev:
                return False
            run.tasks_status, run.batch_asked = TASKS_NONE, 0

        return self._edit(tenant_id, run_id, change)

    def save_pack(self, tenant_id: str, run_id: int, text: str) -> RunRow | None:
        def change(run: SkillRun):
            if run.tasks_status != TASKS_SAVED:
                return False  # no pack before the breakdown is agreed
            run.pack_text, run.phase = text, PHASE_PACK

        return self._edit(tenant_id, run_id, change)

    def revise(self, tenant_id: str, run_id: int, rev: int) -> RunRow | None:
        def change(run: SkillRun):
            if run.spec_status != SPEC_PROPOSED or run.spec_rev != rev:
                return False
            run.spec_status, run.phase, run.batch_asked = SPEC_NONE, PHASE_GRILL, 0

        return self._edit(tenant_id, run_id, change)


class SkillRunService:
    def __init__(
        self,
        *,
        store: SkillRunStore,
        skills: SkillStore,
        translator: Translator,
        prompts_dir: Path,
        rules_path: Path = Path("config/spec_rules.yaml"),
    ):
        self.store = store
        self.skills = skills
        self.tr = translator
        self.prompts_dir = prompts_dir
        self._rules = yaml.safe_load(Path(rules_path).read_text(encoding="utf-8"))

    def t(self, tenant: str, key: str, **values: object) -> str:
        return self.tr.t(tenant, key, **values)

    # starting ----------------------------------------------------------
    async def start(self, tenant: str, user_id: int, slug: str) -> tuple[RunRow, SkillDoc] | None:
        doc = await asyncio.to_thread(self.skills.get, tenant, slug)
        if doc is None:
            return None
        run = await asyncio.to_thread(self.store.start, tenant, user_id, doc.slug, doc.version)
        return run, doc

    async def choose_road(self, tenant: str, run_id: int, road: str) -> RunRow | None:
        if road not in ROADS:
            return None
        return await asyncio.to_thread(self.store.set_road, tenant, run_id, road)

    async def active(self, tenant: str, user_id: int) -> RunRow | None:
        return await asyncio.to_thread(self.store.active, tenant, user_id)

    async def skills_doc(self, tenant: str, slug: str, version: str) -> SkillDoc | None:
        return await asyncio.to_thread(self.skills.get, tenant, slug, version)

    async def get(self, tenant: str, run_id: int) -> RunRow | None:
        return await asyncio.to_thread(self.store.get, tenant, run_id)

    # what the model sees ----------------------------------------------------
    def context(self, tenant: str, run: RunRow) -> str:
        """The "current skill" layer of the agent's context."""
        text = self.skills.text(tenant, run.slug, run.version)
        doc = self.skills.get(tenant, run.slug, run.version)
        if text is None or doc is None:
            return ""
        sections = section_texts(text, (*RUN_SECTIONS, PIPELINE_SECTION))
        wave_note = ""
        if doc.kind == "build":
            wave_note = load_prompt(self.prompts_dir, "skill_run_code_note.md").strip()
        decisions = (
            "\n".join(f"- [{d['by']}] {d['question']} -> {d['decision']}" for d in run.decisions)
            or "(empty)"
        )
        head = load_prompt(
            self.prompts_dir,
            "skill_run.md",
            title=doc.title,
            slug=doc.slug,
            version=doc.version,
            road=run.road or "not chosen",
            phase=run.phase,
            wave_note=wave_note,
            decisions=decisions,
            spec_status=run.spec_status,
            tasks_status=run.tasks_status,
            saved_documents=self._saved_documents(run),
        )
        body = "\n\n".join(f"### {name}\n{content}" for name, content in sections.items())
        return head + "\n\n" + body

    @staticmethod
    def _saved_documents(run: RunRow) -> str:
        parts = []
        if run.spec_status == SPEC_SAVED and run.spec_text:
            parts.append("Agreed spec:\n" + run.spec_text)
        if run.tasks_status == TASKS_SAVED and run.tasks_text:
            parts.append("Agreed tasks:\n" + run.tasks_text)
        return "\n\n".join(parts) or "(none yet)"

    # decisions -------------------------------------------------------------------
    @staticmethod
    def find_decision(run: RunRow, question: str) -> dict | None:
        needle = question.strip().casefold()
        return next((d for d in run.decisions if d["question"].strip().casefold() == needle), None)

    async def record_decision(
        self, tenant: str, run_id: int, question: str, decision: str, by: str, why: str = ""
    ) -> bool:
        entry = {
            "question": _clip(question),
            "decision": _clip(decision),
            "by": by if by in DECIDERS else "agent",
            "why": _clip(why),
        }
        if not entry["question"] or not entry["decision"]:
            return False
        return await asyncio.to_thread(self.store.add_decision, tenant, run_id, entry) is not None

    async def count_question(self, tenant: str, run_id: int) -> int | None:
        return await asyncio.to_thread(self.store.count_question, tenant, run_id)

    async def reset_batch(self, tenant: str, run_id: int) -> None:
        await asyncio.to_thread(self.store.reset_batch, tenant, run_id)

    # the spec ------------------------------------------------------------------
    def validate_spec(self, arguments: dict) -> dict:
        rules = self._rules
        how = _clip(arguments.get("how_it_looks"), 2000)
        if len(how) < rules["min_how_chars"]:
            raise SpecError("how_it_looks: describe the finished result end to end")
        raw = arguments.get("criteria")
        if not isinstance(raw, list) or not raw:
            raise SpecError("criteria: at least one acceptance criterion is required")
        criteria = [_clip(c, 400) for c in raw]
        if len(criteria) > rules["max_criteria"]:
            raise SpecError(f"criteria: at most {rules['max_criteria']}")
        seen = set()
        for number, criterion in enumerate(criteria, start=1):
            if len(criterion) < rules["min_criterion_chars"]:
                raise SpecError(f"criterion {number} is too short to be checked")
            if criterion.casefold() in seen:
                raise SpecError(f"criterion {number} repeats an earlier one")
            seen.add(criterion.casefold())
            if criterion.casefold().startswith(tuple(rules["work_done_prefixes"])):
                raise SpecError(
                    f"criterion {number} says what was done; say what the person will see or check"
                )
        out = [_clip(x, 300) for x in arguments.get("out_of_scope") or [] if _clip(x, 300)]
        if not out:
            raise SpecError("out_of_scope: name at least one thing that is not included")
        return {
            "how_it_looks": how,
            "criteria": criteria,
            "out_of_scope": out,
            "seams": [_clip(x, 300) for x in arguments.get("seams") or [] if _clip(x, 300)],
            "assumptions": [
                _clip(x, 300) for x in arguments.get("assumptions") or [] if _clip(x, 300)
            ],
        }

    def render_spec(self, tenant: str, doc: SkillDoc, spec: dict, run: RunRow) -> str:
        t = lambda key, **v: self.t(tenant, key, **v)  # noqa: E731
        lines = [t("spec_title", title=doc.title), "", t("spec_h_how"), spec["how_it_looks"], ""]
        lines.append(t("spec_h_criteria"))
        lines += [t("spec_criterion", n=i, text=c) for i, c in enumerate(spec["criteria"], 1)]
        lines += ["", t("spec_h_out")] + [t("spec_bullet", text=x) for x in spec["out_of_scope"]]
        for key, items in (
            ("spec_h_seams", spec["seams"]),
            ("spec_h_assumptions", spec["assumptions"]),
        ):
            if items:
                lines += ["", t(key)] + [t("spec_bullet", text=x) for x in items]
        by_agent = [d for d in run.decisions if d["by"] == "agent"]
        if by_agent:
            lines += ["", t("spec_h_decided")]
            lines += [
                t("spec_decided_line", question=d["question"], decision=d["decision"])
                for d in by_agent
            ]
        return "\n".join(lines)

    async def propose_spec(self, tenant: str, run: RunRow, arguments: dict) -> str:
        """Validates and stores the proposal; returns the text to show. Nothing is saved yet."""
        doc = await asyncio.to_thread(self.skills.get, tenant, run.slug, run.version)
        if doc is None:
            raise SpecError("the skill is no longer in the catalog")
        spec = self.validate_spec(arguments)
        fresh = await asyncio.to_thread(self.store.get, tenant, run.id)
        if fresh is not None and fresh.spec_status == SPEC_SAVED:
            raise SpecError("the spec is already agreed and saved; go on to the tasks")
        text = self.render_spec(tenant, doc, spec, fresh or run)
        await asyncio.to_thread(self.store.propose, tenant, run.id, spec, text)
        return text

    async def propose_tasks(self, tenant: str, run: RunRow, arguments: dict) -> str:
        """Validates the breakdown against the saved spec; returns the text to show."""
        fresh = await asyncio.to_thread(self.store.get, tenant, run.id)
        doc = await asyncio.to_thread(self.skills.get, tenant, run.slug, run.version)
        if fresh is None or doc is None or fresh.spec is None or fresh.spec_status != SPEC_SAVED:
            raise TaskError("the spec is not agreed yet; tasks come after it")
        plan = validate_tasks(arguments, fresh.spec, self._rules)
        text = render_tasks(lambda key, **v: self.t(tenant, key, **v), doc, fresh.spec, plan)
        if await asyncio.to_thread(self.store.propose_tasks, tenant, run.id, plan, text) is None:
            raise TaskError("the breakdown could not be saved now")
        return text

    async def agree_tasks(self, tenant: str, run_id: int, rev: int) -> RunRow | None:
        return await asyncio.to_thread(self.store.agree_tasks, tenant, run_id, rev)

    async def revise_tasks(self, tenant: str, run_id: int, rev: int) -> RunRow | None:
        return await asyncio.to_thread(self.store.revise_tasks, tenant, run_id, rev)

    async def build_pack(self, tenant: str, run: RunRow, arguments: dict) -> str:
        """The "do it yourself" pack for the agreed tasks. It holds prompts, never project code."""
        fresh = await asyncio.to_thread(self.store.get, tenant, run.id)
        doc = await asyncio.to_thread(self.skills.get, tenant, run.slug, run.version)
        ready = (
            fresh is not None and fresh.tasks_status == TASKS_SAVED and fresh.spec and fresh.tasks
        )
        if not ready or doc is None:
            raise TaskError("the breakdown is not agreed yet; the pack comes after it")
        pack = validate_pack(arguments, fresh.tasks, self._rules)
        text = render_pack(
            lambda key, **v: self.t(tenant, key, **v), doc, fresh.spec, fresh.tasks, pack
        )
        if await asyncio.to_thread(self.store.save_pack, tenant, run.id, text) is None:
            raise TaskError("the pack could not be saved now")
        return text

    async def agree(self, tenant: str, run_id: int, rev: int) -> RunRow | None:
        return await asyncio.to_thread(self.store.agree, tenant, run_id, rev)

    async def revise(self, tenant: str, run_id: int, rev: int) -> RunRow | None:
        return await asyncio.to_thread(self.store.revise, tenant, run_id, rev)


@dataclass(frozen=True)
class RunScope:
    """What a tool call may touch: the skill run of the person the turn belongs to."""

    service: SkillRunService
    tenant: str
    run_id: int
