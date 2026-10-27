"""Conversation with the agent in Telegram: streamed answers, Standard A buttons, stop button."""

import asyncio
import logging
import secrets
import time
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageGenerationStopped,
)
from aiogram.types import User as TgUser

from app.agent.context import ContextInputs
from app.agent.model import ModelError
from app.agent.orchestrator import (
    Agent,
    Done,
    OptionsAsked,
    PackReady,
    SpecProposed,
    TasksProposed,
)
from app.agent.prompts import load_prompt
from app.agent.store import AgentStore
from app.agent.types import Message as AgentMessage
from app.agent.types import TextDelta
from app.bot import options_ui
from app.bot.repo import KeyedLock, UserRow
from app.bot.service import BLUE, CALLBACK_VERSION, OnboardingService
from app.skills.runs import RunScope, SkillRunService

log = logging.getLogger("app.bot")

DRAFT_INTERVAL_SECONDS = 0.6
TELEGRAM_TEXT_LIMIT = 4096
DEFAULT_CONTEXT = "dm_profile"


def _chunks(text: str) -> list[str]:
    return [text[i : i + TELEGRAM_TEXT_LIMIT] for i in range(0, len(text), TELEGRAM_TEXT_LIMIT)]


class AgentChat:
    def __init__(
        self,
        *,
        svc: OnboardingService,
        store: AgentStore,
        agent: Agent | None,
        prompts_dir: Path,
        methods_index: str,
        runs: SkillRunService | None = None,
    ):
        self.runs = runs
        self.svc = svc
        self.store = store
        self.agent = agent
        self.prompts_dir = prompts_dir
        self.methods_index = methods_index
        self._turn_lock = KeyedLock()
        self._active: dict[int, tuple[int, asyncio.Event]] = {}

    @property
    def tenant(self) -> str:
        return self.svc.tenant_id

    def _labels(self) -> dict[str, str]:
        t = self.svc.t
        return {
            "star": t("option_star"),
            "custom": t("option_custom"),
            "unknown": t("option_unknown"),
            "back": t("option_back"),
            "compare": t("option_compare"),
            "cost": t("option_cost_label"),
        }

    # entry points --------------------------------------------------------
    async def handle_text(self, user: TgUser, message: Message) -> None:
        row = await self.svc.upsert_user(user)
        thread_id = message.message_thread_id
        context = await self._context_key(row, thread_id)
        awaiting = await self.store.awaiting_custom(self.tenant, row.id)
        if awaiting is not None:
            await self.store.set_question(awaiting.id, "answered")
        await self._turn(row, user, message.chat.id, thread_id, context, message.text or "")

    async def handle_question_button(self, query: CallbackQuery) -> None:
        parsed = options_ui.parse_callback(query.data)
        stored = await self.store.get_question(self.tenant, parsed[0]) if parsed else None
        row = await self.svc.repo.get_user(self.tenant, query.from_user.id)
        if not parsed or stored is None or row is None or stored.user_id != row.id:
            await query.answer(self.svc.t("stale_button"), show_alert=True)
            return
        action = parsed[1]
        question = options_ui.from_payload(stored.payload)
        message = query.message if isinstance(query.message, Message) else None
        if stored.status != "open":
            await query.answer(self.svc.t("stale_button"), show_alert=True)
            return
        if action == "compare":
            await query.answer()
            if message:
                await message.edit_text(
                    options_ui.render_comparison(question, self._labels()),
                    reply_markup=options_ui.render_keyboard(question, self._labels()),
                )
            return
        if action == "custom":
            await self.store.set_question(stored.id, "awaiting_custom")
            await query.answer(self.svc.t("custom_prompt"))
            return
        await self.store.set_question(stored.id, "answered")
        await query.answer()
        if action == "unknown":
            await self._journal_unknown(row, stored.context_key, question)
        if message:
            await self._close_question(message, question, action)
        text = {
            "unknown": self.svc.t("option_unknown_text"),
            "back": self.svc.t("option_back_text"),
        }.get(action) or self.svc.t("option_chosen", title=question.options[int(action[1])].title)
        chat_id = message.chat.id if message else row.dm_chat_id or query.from_user.id
        thread_id = message.message_thread_id if message else None
        await self._turn(row, query.from_user, chat_id, thread_id, stored.context_key, text)

    async def _journal_unknown(self, row, context, question) -> None:
        """ "I don't know" inside a skill: the agent takes the recommended option, and it is
        written into the journal at once so that the question is not asked again."""
        run, _ = await self._skill_scope(row, context)
        if run is None or self.runs is None:
            return
        star = question.options[question.recommended_index]
        await self.runs.record_decision(
            self.tenant,
            run.id,
            question.text,
            star.title,
            "agent",
            self.svc.t("decision_unknown_why"),
        )

    async def _close_question(self, message: Message, question, action: str) -> None:
        """Remove the buttons and keep the question text, so the history stays readable."""
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass  # already changed or too old

    def stop(self, stopped: MessageGenerationStopped) -> None:
        active = self._active.get(stopped.chat.id)
        if active and active[0] == stopped.draft_id:
            active[1].set()

    # one turn ------------------------------------------------------------
    async def _context_key(self, row: UserRow, thread_id: int | None) -> str:
        if thread_id is not None:
            kind = await self.svc.repo.kind_by_thread(self.tenant, row.id, thread_id)
            if kind:
                return kind
        return row.active_context or DEFAULT_CONTEXT

    async def turn_for(self, row, user, chat_id, thread_id, context, text) -> None:
        """A turn started by the platform itself (a skill button), not by a typed message."""
        await self._turn(row, user, chat_id, thread_id, context, text)

    async def _skill_scope(self, row, context):
        """The skill the person is going through, once the road is chosen."""
        if self.runs is None or context != "dm_skills":
            return None, None
        run = await self.runs.active(self.tenant, row.id)
        if run is None or run.road is None:
            return None, None
        return run, RunScope(self.runs, self.tenant, run.id)

    async def _turn(self, row, user, chat_id, thread_id, context, text) -> None:
        bot = self.svc.bot
        if self.agent is None:
            await bot.send_message(
                chat_id=chat_id, message_thread_id=thread_id, text=self.svc.t("agent_unavailable")
            )
            return
        async with self._turn_lock((self.tenant, user.id)):
            summary_row = await self.store.get_summary(self.tenant, row.id, context)
            summary, upto = summary_row or (None, 0)
            stored = await self.store.history(self.tenant, row.id, context, after_id=upto)
            await self.store.add_message(self.tenant, row.id, context, "user", text)
            name = self.svc.display_name(user)
            run, scope = await self._skill_scope(row, context)
            inputs = ContextInputs(
                constitution=load_prompt(
                    self.prompts_dir,
                    "constitution.md",
                    name=name,
                    tech_depth="unknown",
                    country="RU",
                    tone="partner",
                    ai_level="unknown",
                    methods_index=self.methods_index,
                ),
                methods_index=self.methods_index,
                passport={"name": name, "country": "RU", "tone": "partner"},
                summary=summary,
                history=[AgentMessage(m.role, m.content) for m in stored],  # type: ignore[arg-type]
                current=text,
                skill_context=self.runs.context(self.tenant, run) if run and self.runs else None,
                tool_scope=scope,
            )
            await self._stream(inputs, row, chat_id, thread_id, context, stored, run)

    async def _stream(self, inputs, row, chat_id, thread_id, context, stored, run=None) -> None:
        bot = self.svc.bot
        draft_id = secrets.randbelow(2**31 - 1) + 1
        cancel = asyncio.Event()
        self._active[chat_id] = (draft_id, cancel)
        parts: list[str] = []
        question = None
        spec_text: str | None = None
        tasks_text: str | None = None
        pack_text: str | None = None
        done: Done | None = None
        drafts_ok = True
        last_push = 0.0
        try:
            async for event in self.agent.respond(inputs, cancel=cancel):  # type: ignore[union-attr]
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                    now = time.monotonic()
                    if drafts_ok and now - last_push >= DRAFT_INTERVAL_SECONDS:
                        last_push = now
                        drafts_ok = await self._push_draft(chat_id, thread_id, draft_id, parts)
                elif isinstance(event, OptionsAsked):
                    question = event.question
                elif isinstance(event, SpecProposed):
                    spec_text = event.text
                elif isinstance(event, TasksProposed):
                    tasks_text = event.text
                elif isinstance(event, PackReady):
                    pack_text = event.text
                elif isinstance(event, Done):
                    done = event
        except ModelError as exc:
            log.warning("model failed: %s", exc)
            await bot.send_message(
                chat_id=chat_id, message_thread_id=thread_id, text=self.svc.t("agent_error")
            )
            return
        finally:
            self._active.pop(chat_id, None)

        text = (done.text if done else "".join(parts)).strip()
        if text:
            for chunk in _chunks(text):
                await bot.send_message(chat_id=chat_id, message_thread_id=thread_id, text=chunk)
            await self.store.add_message(self.tenant, row.id, context, "assistant", text)
        if done and done.summarized_count and done.summary:
            await self.store.save_summary(
                self.tenant, row.id, context, done.summary, stored[done.summarized_count - 1].id
            )
        if question is not None:
            await self._send_question(row, chat_id, thread_id, context, question)
        if spec_text is not None and run is not None:
            await self._send_spec(row, chat_id, thread_id, context, run.id, spec_text)
        if tasks_text is not None and run is not None:
            await self._send_tasks(row, chat_id, thread_id, context, run.id, tasks_text)
        if pack_text is not None and run is not None:
            await self._send_pack(row, chat_id, thread_id, context, run, pack_text)
        if run is not None and question is None and self.runs is not None:
            await self.runs.reset_batch(self.tenant, run.id)  # a block of questions ended

    async def _push_draft(self, chat_id, thread_id, draft_id, parts) -> bool:
        try:
            await self.svc.bot.send_message_draft(
                chat_id=chat_id,
                draft_id=draft_id,
                message_thread_id=thread_id,
                text="".join(parts)[:TELEGRAM_TEXT_LIMIT],
                can_stop=True,
                keep_on_stop=True,
            )
            return True
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            log.info("streaming drafts unavailable: %s", type(exc).__name__)
            return False  # the final message is still sent

    async def _send_spec(self, row, chat_id, thread_id, context, run_id, spec_text) -> None:
        """The spec goes to the person with "Agree" and "Fix"; nothing is saved before that."""
        t = self.svc.t
        current = await self.runs.get(self.tenant, run_id) if self.runs else None
        rev = current.spec_rev if current else 0
        full = spec_text + "\n\n" + t("spec_ask")
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("spec_agree"),
                        callback_data=f"{CALLBACK_VERSION}:spec:ok:{run_id}:{rev}",
                        style=BLUE,
                    ),
                    InlineKeyboardButton(
                        text=t("spec_fix"),
                        callback_data=f"{CALLBACK_VERSION}:spec:fix:{run_id}:{rev}",
                    ),
                ]
            ]
        )
        chunks = _chunks(full)
        for index, chunk in enumerate(chunks):
            last = index == len(chunks) - 1
            await self.svc.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=chunk,
                reply_markup=keyboard if last else None,
            )
        await self.store.add_message(self.tenant, row.id, context, "assistant", full)

    async def _send_tasks(self, row, chat_id, thread_id, context, run_id, tasks_text) -> None:
        """The breakdown goes to the person; criteria that nothing closes are asked about."""
        t = self.svc.t
        current = await self.runs.get(self.tenant, run_id) if self.runs else None
        rev = current.tasks_rev if current else 0
        uncovered = bool(current and current.tasks and current.tasks.get("uncovered"))
        base = f"{CALLBACK_VERSION}:tasks"
        if uncovered:
            first = ("tasks_aware", f"{base}:aware:{run_id}:{rev}")
            second = ("tasks_add", f"{base}:add:{run_id}:{rev}")
        else:
            first = ("tasks_agree", f"{base}:ok:{run_id}:{rev}")
            second = ("tasks_fix", f"{base}:fix:{run_id}:{rev}")
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=t(first[0]), callback_data=first[1], style=BLUE),
                    InlineKeyboardButton(text=t(second[0]), callback_data=second[1]),
                ]
            ]
        )
        full = tasks_text + "\n\n" + t("tasks_ask")
        chunks = _chunks(full)
        for index, chunk in enumerate(chunks):
            last = index == len(chunks) - 1
            await self.svc.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=chunk,
                reply_markup=keyboard if last else None,
            )
        await self.store.add_message(self.tenant, row.id, context, "assistant", full)

    async def _send_pack(self, row, chat_id, thread_id, context, run, pack_text) -> None:
        """The "do it yourself" pack goes out as a file the person keeps."""
        t = self.svc.t
        title = t("pack_caption", title=run.slug)
        doc = await self.runs.skills_doc(self.tenant, run.slug, run.version) if self.runs else None
        if doc is not None:
            title = t("pack_caption", title=doc.title)
        await self.svc.bot.send_document(
            chat_id=chat_id,
            message_thread_id=thread_id,
            document=BufferedInputFile(pack_text.encode("utf-8"), filename=f"{run.slug}-pack.md"),
            caption=title[:1000],
        )
        await self.svc.bot.send_message(
            chat_id=chat_id, message_thread_id=thread_id, text=t("pack_done")
        )
        await self.store.add_message(self.tenant, row.id, context, "assistant", pack_text)

    async def _send_question(self, row, chat_id, thread_id, context, question) -> None:
        text = options_ui.render_text(question, self.svc.t("option_star"))
        # the row exists before the buttons do, so an instant tap always finds it
        await self.store.create_question(
            self.tenant, row.id, context, options_ui.to_payload(question), question.id
        )
        sent = await self.svc.bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=text,
            reply_markup=options_ui.render_keyboard(question, self._labels()),
        )
        await self.store.set_question(question.id, "open", sent.message_id)
        await self.store.add_message(self.tenant, row.id, context, "assistant", text)
