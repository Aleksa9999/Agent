"""The entrance test as one service: voice story, questionnaire, follow-up questions.

Every entry (Mini App voice, a voice message in the chat, the questionnaire buttons) changes the
same stored profile, so one can finish what another began. Texts come from the translator."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from app.agent.model import ModelError, ModelPort
from app.i18n import Translator
from app.profile import flow
from app.profile.asr import AsrError, AsrPort
from app.profile.card import card_lines, line_fields, public_lines
from app.profile.extract import clean_text, extract_profile
from app.profile.fields import (
    CUSTOM_LIMIT,
    ENUM_CODES,
    FIELDS,
    OPTION_COUNT,
    Answer,
    Answers,
    codes,
    missing,
    relevant_total,
    star_index,
)
from app.profile.passport import PassportRow, PassportStore, Publisher, fingerprint
from app.profile.store import ProfileStore

log = logging.getLogger("app.profile")
SAVE_ATTEMPTS = 4

KINDS = ("option", "custom", "unknown")
OK, NO_ASR, ASR_ERROR, EMPTY, NOTHING, NO_MODEL = (
    "ok",
    "no_asr",
    "asr_error",
    "empty",
    "nothing",
    "no_model",
)


class InvalidAnswerError(ValueError):
    """The answer does not match the question that is open. `reason` is a short code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class NotReadyError(Exception):
    """The profile is not complete (or a question is open): there is nothing to confirm yet."""


@dataclass(frozen=True)
class ConfirmResult:
    view: dict
    version: int
    created: bool  # False when the same profile was already confirmed
    published: bool  # the public card is in the group topic


@dataclass(frozen=True)
class HearResult:
    outcome: str
    view: dict | None = None
    new_fields: int = 0


class ProfileService:
    def __init__(
        self,
        *,
        store: ProfileStore,
        translator: Translator,
        prompts_dir: Path,
        model: ModelPort | None = None,
        asr: AsrPort | None = None,
        passports: PassportStore | None = None,
        publisher: Publisher | None = None,
        privacy_path: Path = Path("config/privacy_patterns.yaml"),
    ):
        self.passports = passports
        self.publisher = publisher
        self.privacy_path = privacy_path
        self.store = store
        self.tr = translator
        self.prompts_dir = prompts_dir
        self.model = model
        self.asr = asr

    @property
    def voice_available(self) -> bool:
        return self.asr is not None and self.model is not None

    def t(self, tenant: str, key: str, **values: object) -> str:
        return self.tr.t(tenant, key, **values)

    # reading -------------------------------------------------------------
    async def view(self, tenant: str, user_id: int) -> dict:
        data = await asyncio.to_thread(self.store.load, tenant, user_id)
        state = flow.ensure(data.state, data.answers)
        return await self._present(tenant, user_id, data.answers, state)

    async def _present(self, tenant: str, user_id: int, answers: Answers, state: dict) -> dict:
        passport = None
        if self.passports is not None and not missing(answers) and answers:
            passport = await asyncio.to_thread(self.passports.latest, tenant, user_id)
        return self._view(tenant, answers, state, passport)

    def _view(
        self, tenant: str, answers: Answers, state: dict, passport: PassportRow | None = None
    ) -> dict:
        todo = missing(answers)
        question = None
        position = None
        field = flow.current(state)
        if field is not None:
            question = self._question(tenant, field, answers)
            position = {"index": flow.index(state), "size": state["size"]}
        total = relevant_total(answers)
        done = total - len(todo)
        status = "new" if not answers else "complete" if not todo else "collecting"
        card = None
        if status == "complete" and question is None:
            card = {
                "lines": [
                    {"id": c.id, "label": c.label, "text": c.text}
                    for c in card_lines(self.tr, tenant, answers)
                ],
                "passport": None
                if passport is None
                else {
                    "version": passport.version,
                    "current": passport.content_hash == fingerprint(answers),
                    "published": passport.group_message_id is not None,
                },
            }
        return {
            "card": card,
            "status": status,
            "answers": [
                {"field": f, "kind": answers[f].kind, "text": answers[f].text}
                for f in FIELDS
                if f in answers
            ],
            "progress": {"answered": done, "total": total},
            "question": question,
            "position": position,
            "can_go_back": bool(state.get("history")),
            "voice_available": self.voice_available,
        }

    def _question(self, tenant: str, field: str, answers: Answers) -> dict:
        star = star_index(field, answers)
        chosen = answers.get(field)
        options = [
            {
                "code": code,
                "title": self.t(tenant, f"pq_{field}_o{i + 1}"),
                "recommended": i == star,
            }
            for i, code in enumerate(codes(field))
        ]
        return {
            "field": field,
            "text": self.t(tenant, f"pq_{field}"),
            "why": self.t(tenant, f"pq_{field}_why"),
            "star_hint": self.t(tenant, "pf_star_hint"),
            "options": options,
            "selected": None
            if chosen is None
            else {"kind": chosen.kind, "code": chosen.code, "text": chosen.text},
        }

    def compare_text(self, tenant: str, field: str, answers: Answers) -> str:
        """The "Compare" view: why the question is asked and the options with the starred one."""
        star = star_index(field, answers)
        lines = [self.t(tenant, "pf_compare_head", why=self.t(tenant, f"pq_{field}_why"))]
        for i in range(OPTION_COUNT):
            lines.append(
                self.t(
                    tenant,
                    "pf_compare_line",
                    n=i + 1,
                    title=self.t(tenant, f"pq_{field}_o{i + 1}"),
                    star=" ⭐" if i == star else "",
                )
            )
        return "\n".join(lines)

    # changing ------------------------------------------------------------
    async def _change(self, tenant: str, user_id: int, apply) -> dict:
        """Load, change, save with the version check; try again if somebody saved in between."""
        for _ in range(SAVE_ATTEMPTS):
            data = await asyncio.to_thread(self.store.load, tenant, user_id)
            answers = dict(data.answers)
            state = flow.ensure(data.state, answers)
            answers, state = apply(answers, state)
            saved = await asyncio.to_thread(
                self.store.save, tenant, user_id, answers, state, data.version
            )
            if saved:
                return await self._present(tenant, user_id, answers, state)
        raise RuntimeError("profile was changed too often at once")

    async def answer(
        self,
        tenant: str,
        user_id: int,
        field: str,
        kind: str,
        code: str | None = None,
        text: str | None = None,
    ) -> dict:
        if kind not in KINDS:
            raise InvalidAnswerError("bad_kind")

        def apply(answers: Answers, state: dict):
            if flow.current(state) != field:
                raise InvalidAnswerError("not_current")  # an old screen: the question moved on
            if kind == "option":
                if code not in codes(field):
                    raise InvalidAnswerError("bad_option")
                number = codes(field).index(code) + 1
                answers[field] = Answer("option", self.t(tenant, f"pq_{field}_o{number}"), code)
            elif kind == "custom":
                own = clean_text(text, CUSTOM_LIMIT)
                if not own:
                    raise InvalidAnswerError("empty_text")
                answers[field] = Answer("custom", own)
            else:
                answers[field] = Answer("unknown")
            return answers, flow.after_answer(state, answers)

        return await self._change(tenant, user_id, apply)

    async def back(self, tenant: str, user_id: int) -> dict:
        return await self._change(
            tenant, user_id, lambda answers, state: (answers, flow.after_back(state))
        )

    # voice ---------------------------------------------------------------
    async def hear(self, tenant: str, user_id: int, audio: bytes, mime: str) -> HearResult:
        """Recognise a recorded story and merge what it says into the profile."""
        if not self.voice_available:
            return HearResult(NO_ASR)
        assert self.asr is not None and self.model is not None
        try:
            story = await self.asr.transcribe(audio, mime)
        except AsrError:
            return HearResult(ASR_ERROR)
        if not story.strip():
            return HearResult(EMPTY)
        try:
            found = await extract_profile(self.model, self.prompts_dir, story)
        except ModelError:
            return HearResult(ASR_ERROR)
        if not found:
            return HearResult(NOTHING)
        merged = 0

        def apply(answers: Answers, state: dict):
            nonlocal merged
            merged = 0
            for field, value in found.items():
                answers[field] = self._voice_answer(tenant, field, value)
                merged += 1
            return answers, flow.after_merge(answers, list(state.get("history", [])))

        view = await self._change(tenant, user_id, apply)
        return HearResult(OK, view, merged)

    def _voice_answer(self, tenant: str, field: str, value: str) -> Answer:
        if field in ENUM_CODES:
            number = ENUM_CODES[field].index(value) + 1
            return Answer("voice", self.t(tenant, f"pq_{field}_o{number}"), value)
        return Answer("voice", value)

    # card, passport, edit -------------------------------------------------
    async def edit(self, tenant: str, user_id: int, line_id: str) -> dict:
        """ "Fix": reopen the questions of one card line; the old answers stay until replaced."""

        def apply(answers: Answers, state: dict):
            fields = line_fields(line_id, answers)
            if not fields:
                raise InvalidAnswerError("bad_line")
            return answers, {
                "batch": fields,
                "size": len(fields),
                "history": list(state.get("history", [])),
            }

        return await self._change(tenant, user_id, apply)

    async def confirm(self, tenant: str, user_id: int, name: str) -> ConfirmResult:
        """ "Right": write passport version n+1 (only if the profile changed) and post the public
        card into the group topic."""
        if self.passports is None:
            raise NotReadyError("passports are not configured")
        data = await asyncio.to_thread(self.store.load, tenant, user_id)
        state = flow.ensure(data.state, data.answers)
        if not data.answers or missing(data.answers) or flow.current(state) is not None:
            raise NotReadyError("profile is not complete")
        answers = data.answers
        digest = fingerprint(answers)
        public = public_lines(self.tr, tenant, answers, self.privacy_path)
        snapshot = {
            "fields": {f: a.to_json() for f, a in answers.items()},
            "card": [
                {"id": c.id, "text": c.text, "public": c.public}
                for c in card_lines(self.tr, tenant, answers)
            ],
            "public": [{"label": label, "text": text} for label, text in public],
        }
        before = await asyncio.to_thread(self.passports.latest, tenant, user_id)
        passport = await asyncio.to_thread(self.passports.create, tenant, user_id, snapshot, digest)
        created = before is None or before.version != passport.version
        published = passport.group_message_id is not None
        if self.publisher is not None and (created or not published):
            previous = await asyncio.to_thread(self.passports.last_message_id, tenant, user_id)
            message_id = await self.publisher.publish(tenant, user_id, name, public, previous)
            if message_id is not None:
                await asyncio.to_thread(
                    self.passports.set_message, tenant, user_id, passport.version, message_id
                )
                published = True
        view = await self._present(tenant, user_id, answers, state)
        return ConfirmResult(view, passport.version, created, published)
