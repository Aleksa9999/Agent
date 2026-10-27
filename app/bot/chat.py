"""Conversation with the agent in Telegram: streamed answers, Standard A buttons, stop button."""

import asyncio
import logging
import secrets
import time
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message, MessageGenerationStopped
from aiogram.types import User as TgUser

from app.agent.context import ContextInputs
from app.agent.model import ModelError
from app.agent.orchestrator import Agent, Done, OptionsAsked
from app.agent.prompts import load_prompt
from app.agent.store import AgentStore
from app.agent.types import Message as AgentMessage
from app.agent.types import TextDelta
from app.bot import options_ui
from app.bot.repo import KeyedLock, UserRow
from app.bot.service import OnboardingService

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
    ):
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
        if message:
            await self._close_question(message, question, action)
        text = {
            "unknown": self.svc.t("option_unknown_text"),
            "back": self.svc.t("option_back_text"),
        }.get(action) or self.svc.t("option_chosen", title=question.options[int(action[1])].title)
        chat_id = message.chat.id if message else row.dm_chat_id or query.from_user.id
        thread_id = message.message_thread_id if message else None
        await self._turn(row, query.from_user, chat_id, thread_id, stored.context_key, text)

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
            )
            await self._stream(inputs, row, chat_id, thread_id, context, stored)

    async def _stream(self, inputs, row, chat_id, thread_id, context, stored) -> None:
        bot = self.svc.bot
        draft_id = secrets.randbelow(2**31 - 1) + 1
        cancel = asyncio.Event()
        self._active[chat_id] = (draft_id, cancel)
        parts: list[str] = []
        question = None
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
