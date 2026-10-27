"""aiogram routers. Handlers only translate updates into service calls.

A Router can be attached to one Dispatcher only, so every tenant gets its own router.
"""

from aiogram import F, Router
from aiogram.filters import JOIN_TRANSITION, ChatMemberUpdatedFilter, Command, CommandStart
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from app.bot.service import OnboardingService, parse_context_callback


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

    @router.callback_query(F.data.func(lambda data: parse_context_callback(data) is not None))
    async def on_context_button(query: CallbackQuery, svc: OnboardingService) -> None:
        kind = parse_context_callback(query.data)
        if kind and await svc.set_context(query.from_user.id, kind):
            await query.answer(svc.t("project_set", name=svc.t(f"topic_{kind}")))
            return
        await query.answer(svc.t("stale_button"), show_alert=True)

    @router.callback_query()
    async def on_stale_button(query: CallbackQuery, svc: OnboardingService) -> None:
        """Any button this version does not know: explain, never fail."""
        await query.answer(svc.t("stale_button"), show_alert=True)

    return router
