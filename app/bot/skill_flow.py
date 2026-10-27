"""Starting a skill in the chat and the buttons of its flow: road, "Agree", "Fix".

The spec is saved by the "Agree" button handled here, never by the model."""

import logging

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.agent.catalog import ModelCatalog
from app.bot.chat import AgentChat
from app.bot.service import BLUE, CALLBACK_VERSION, OnboardingService
from app.skills.estimate import estimate_text
from app.skills.runs import ROADS, SkillRunService

log = logging.getLogger("app.bot")
SKILLS_CONTEXT = "dm_skills"
ACTIONS = ("road", "spec")


def flow_callback(kind: str, action: str, run_id: int, rev: int | None = None) -> str:
    base = f"{CALLBACK_VERSION}:{kind}:{action}:{run_id}"
    return base if rev is None else f"{base}:{rev}"


def parse_flow_callback(data: str | None) -> tuple[str, str, int, int] | None:
    """(kind, action, run id, proposal number). The number is 0 for the road buttons."""
    parts = (data or "").split(":")
    if len(parts) < 4 or parts[0] != CALLBACK_VERSION or parts[1] not in ACTIONS:
        return None
    kind, action = parts[1], parts[2]
    allowed = ROADS if kind == "road" else ("ok", "fix")
    wanted = 4 if kind == "road" else 5
    if action not in allowed or len(parts) != wanted or not all(p.isdigit() for p in parts[3:]):
        return None
    return kind, action, int(parts[3]), int(parts[4]) if kind == "spec" else 0


class SkillFlow:
    def __init__(
        self,
        *,
        svc: OnboardingService,
        chat: AgentChat,
        runs: SkillRunService,
        catalog: ModelCatalog,
    ):
        self.svc = svc
        self.chat = chat
        self.runs = runs
        self.catalog = catalog

    @property
    def tenant(self) -> str:
        return self.svc.tenant_id

    async def start(self, tg_id: int, slug: str) -> str:
        """Open a skill for a person: the intro with the estimate and the choice of the road.
        Returns "ok", "no_chat" (the person never pressed Start) or "unknown_skill"."""
        row = await self.svc.repo.get_user(self.tenant, tg_id)
        if row is None or row.dm_chat_id is None:
            return "no_chat"
        started = await self.runs.start(self.tenant, row.id, slug)
        if started is None:
            return "unknown_skill"
        run, doc = started
        topic = await self.svc.repo.get_topic(self.tenant, row.id, SKILLS_CONTEXT)
        chat_id = topic.chat_id if topic else row.dm_chat_id
        thread_id = topic.thread_id if topic else None
        if topic is None:
            await self.svc.repo.update_user(row.id, active_context=SKILLS_CONTEXT)
        t = self.svc.t
        parts = [t("run_intro", title=doc.title), t("run_roads")]
        if doc.kind == "build":
            parts.append(t("run_code_note"))
        parts.append(estimate_text(self.svc.tr, self.tenant, doc, self.catalog))
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("run_road_agent"),
                        callback_data=flow_callback("road", "agent", run.id),
                        style=BLUE,
                    ),
                    InlineKeyboardButton(
                        text=t("run_road_self"),
                        callback_data=flow_callback("road", "self", run.id),
                    ),
                ]
            ]
        )
        try:
            await self.svc.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text="\n\n".join(parts),
                reply_markup=keyboard,
            )
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            log.warning("skill intro was not sent: %s", type(exc).__name__)
            return "no_chat"
        return "ok"

    async def on_button(self, query: CallbackQuery) -> None:
        parsed = parse_flow_callback(query.data)
        row = await self.svc.repo.get_user(self.tenant, query.from_user.id)
        run = await self.runs.get(self.tenant, parsed[2]) if parsed else None
        if parsed is None or row is None or run is None or run.user_id != row.id:
            await query.answer(self.svc.t("run_stale"), show_alert=True)
            return
        kind, action, run_id, rev = parsed
        message = query.message if isinstance(query.message, Message) else None
        chat_id = message.chat.id if message else row.dm_chat_id or query.from_user.id
        thread_id = message.message_thread_id if message else None
        if kind == "road":
            updated = await self.runs.choose_road(self.tenant, run_id, action)
            doc = await self.runs.skills_doc(self.tenant, run.slug, run.version)
            if updated is None or doc is None:
                await query.answer(self.svc.t("run_stale"), show_alert=True)
                return
            text = self.svc.t(f"run_road_{action}_text", title=doc.title)
        elif action == "ok":
            saved = await self.runs.agree(self.tenant, run_id, rev)
            if saved is None:
                await query.answer(self.svc.t("run_stale"), show_alert=True)
                return
            text = self.svc.t("spec_agreed_text")
        else:
            revised = await self.runs.revise(self.tenant, run_id, rev)
            if revised is None:
                await query.answer(self.svc.t("run_stale"), show_alert=True)
                return
            text = self.svc.t("spec_fix_text")
        await query.answer(self.svc.t("spec_saved") if kind == "spec" and action == "ok" else None)
        if message:
            try:
                await message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest:
                pass  # too old to edit: the answer above is enough
        await self.chat.turn_for(row, query.from_user, chat_id, thread_id, SKILLS_CONTEXT, text)
