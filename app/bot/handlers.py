"""aiogram routers. Handlers only translate updates into service calls.

A Router can be attached to one Dispatcher only, so every tenant gets its own router.
"""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import JOIN_TRANSITION, ChatMemberUpdatedFilter, Command, CommandStart
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message, MessageGenerationStopped

from app.bot import options_ui
from app.bot.chat import AgentChat
from app.bot.service import (
    MINIAPP_LATER,
    OnboardingService,
    parse_context_callback,
    parse_skill_callback,
)
from app.bot.voice import VoiceIntake


def build_router() -> Router:
    router = Router(name="onboarding")
    private = F.chat.type == "private"

    @router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
    async def on_member_joined(event: ChatMemberUpdated, svc: OnboardingService) -> None:
        await svc.handle_group_join(event.new_chat_member.user, event.chat.id)

    @router.message(F.new_chat_members)
    async def on_new_members(message: Message, svc: OnboardingService) -> None:
        for member in message.new_chat_members or []:
            await svc.handle_group_join(member, message.chat.id)

    @router.message(CommandStart(), private)
    async def on_start(message: Message, svc: OnboardingService) -> None:
        if message.from_user:
            await svc.handle_start(message.from_user, message.chat.id)

    @router.message(Command("project"), private)
    async def on_project(message: Message, svc: OnboardingService) -> None:
        if message.from_user:
            await svc.handle_project(message.from_user, message.chat.id)

    @router.message(Command("help"), private)
    async def on_help(message: Message, svc: OnboardingService) -> None:
        if message.from_user:
            await svc.handle_help(message.from_user, message.chat.id)

    @router.message(Command("admin", "members"), private)
    async def on_owner_command(message: Message, svc: OnboardingService) -> None:
        if message.from_user and message.text:
            command = message.text.split()[0].lstrip("/").split("@")[0].lower()
            await svc.handle_owner_command(message.from_user, message.chat.id, command)

    @router.message(Command("skill_upload"), private, ~F.document)
    async def on_skill_upload(message: Message, svc: OnboardingService) -> None:
        if message.from_user:
            await svc.handle_skill_upload(message.from_user, message.chat.id)

    @router.message(F.voice | F.audio, private)
    async def on_voice(message: Message, voice: VoiceIntake | None) -> None:
        media = message.voice or message.audio
        if voice is not None and message.from_user and media:
            await voice.handle(message.from_user, message.chat.id, message.message_thread_id, media)

    @router.message(F.document, private)
    async def on_document(message: Message, svc: OnboardingService) -> None:
        if message.from_user and message.document:
            await svc.handle_document(
                message.from_user, message.chat.id, message.document, message.caption
            )

    @router.callback_query(F.data.func(lambda data: parse_skill_callback(data) is not None))
    async def on_skill_button(query: CallbackQuery, svc: OnboardingService) -> None:
        await svc.handle_skill_button(query)

    @router.callback_query(F.data.func(lambda data: parse_context_callback(data) is not None))
    async def on_context_button(query: CallbackQuery, svc: OnboardingService) -> None:
        kind = parse_context_callback(query.data)
        if kind and await svc.set_context(query.from_user.id, kind):
            await query.answer(svc.t("project_set", name=svc.t(f"topic_{kind}")))
            return
        await query.answer(svc.t("stale_button"), show_alert=True)

    @router.message(F.text, ~F.text.startswith("/"), private)
    async def on_text(message: Message, chat: AgentChat) -> None:
        if message.from_user:
            await chat.handle_text(message.from_user, message)

    @router.callback_query(F.data.startswith(options_ui.PREFIX + ":"))
    async def on_question_button(query: CallbackQuery, chat: AgentChat) -> None:
        await chat.handle_question_button(query)

    @router.stopped_message_generation()
    async def on_generation_stopped(event: MessageGenerationStopped, chat: AgentChat) -> None:
        chat.stop(event)

    @router.callback_query(F.data == MINIAPP_LATER)
    async def on_miniapp_later(query: CallbackQuery, svc: OnboardingService) -> None:
        await query.answer(svc.t("miniapp_later_ack"))
        if isinstance(query.message, Message):
            try:
                await query.message.delete()
            except TelegramBadRequest:
                pass  # too old to delete: the answer above is enough

    @router.callback_query()
    async def on_stale_button(query: CallbackQuery, svc: OnboardingService) -> None:
        """Any button this version does not know: explain, never fail."""
        await query.answer(svc.t("stale_button"), show_alert=True)

    return router
