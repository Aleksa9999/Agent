"""Onboarding logic: group topic for a new member, private-chat topics, roles and owner commands.

Every Telegram call goes through the aiogram Bot, so tests can run the real handlers against a
recorded fake session. Every human-readable text comes from the translator.
"""

import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    MenuButtonWebApp,
    ReplyKeyboardMarkup,
    User,
    WebAppInfo,
)

from app.bot.repo import BotRepo, KeyedLock, UserRow
from app.bot.roles import RoleRegistry
from app.config import Settings
from app.i18n import Translator

log = logging.getLogger("app.bot")

GROUP_KIND = "group_member"
DM_KINDS = ("dm_profile", "dm_skills", "dm_project", "dm_reports")
CALLBACK_VERSION = "v1"
TOPIC_NAME_LIMIT = 128
PUBLIC_COMMANDS = ("start", "project", "help")
OWNER_COMMANDS = ("admin", "members")


def context_callback(kind: str) -> str:
    return f"{CALLBACK_VERSION}:ctx:{kind}"


MINIAPP_LATER = f"{CALLBACK_VERSION}:miniapp:later"
BLUE = "primary"  # button style that Telegram draws in blue


def parse_context_callback(data: str | None) -> str | None:
    parts = (data or "").split(":")
    if (
        len(parts) == 3
        and parts[0] == CALLBACK_VERSION
        and parts[1] == "ctx"
        and parts[2] in DM_KINDS
    ):
        return parts[2]
    return None


class OnboardingService:
    def __init__(
        self,
        *,
        bot: Bot,
        repo: BotRepo,
        translator: Translator,
        roles: RoleRegistry,
        settings: Settings,
        tenant_id: str,
    ):
        self.bot = bot
        self.repo = repo
        self.tr = translator
        self.roles = roles
        self.settings = settings
        self.tenant_id = tenant_id
        self._lock = KeyedLock()
        self._username: str | None = None

    def t(self, key: str, **values: object) -> str:
        return self.tr.t(self.tenant_id, key, **values)

    def is_owner(self, tg_id: int) -> bool:
        return self.roles.role_of(tg_id) == "owner"

    async def bot_username(self) -> str:
        if self._username is None:
            self._username = (await self.bot.me()).username or ""
        return self._username

    def display_name(self, user: User | UserRow) -> str:
        first = (user.first_name or "").strip()
        last = (getattr(user, "last_name", None) or "").strip()
        name = f"{first} {last}".strip() or (user.username or "") or self.t("member_fallback_name")
        return name[:TOPIC_NAME_LIMIT]

    async def _upsert(self, user: User) -> UserRow:
        return await self.repo.upsert_user(
            self.tenant_id,
            user.id,
            role=self.roles.role_of(user.id),
            first_name=user.first_name or "",
            last_name=user.last_name,
            username=user.username,
            lang=user.language_code,
        )

    # group ---------------------------------------------------------------
    async def handle_group_join(self, user: User, chat_id: int) -> None:
        """A person entered the group: give them a public topic and a button to the private chat."""
        if user.is_bot or chat_id != self.settings.group_chat_id:
            return
        async with self._lock((self.tenant_id, user.id)):
            row = await self._upsert(user)
            if await self.repo.get_topic(self.tenant_id, row.id, GROUP_KIND):
                return  # a rejoin or a duplicate update: nothing to create
            started = time.monotonic()
            try:
                topic = await self.bot.create_forum_topic(
                    chat_id=chat_id, name=self.display_name(user)
                )
            except (TelegramBadRequest, TelegramForbiddenError) as exc:
                log.error("group topic was not created: %s", type(exc).__name__)
                return
            stored = await self.repo.add_topic(
                self.tenant_id, row.id, GROUP_KIND, chat_id, topic.message_thread_id
            )
            if not stored:
                return
            await self.bot.send_message(
                chat_id=chat_id,
                message_thread_id=topic.message_thread_id,
                text=self.t("group_welcome", name=self.display_name(user)),
                reply_markup=await self._start_button(),
            )
            log.info("group topic ready in %.2fs", time.monotonic() - started)

    async def _start_button(self) -> InlineKeyboardMarkup:
        link = f"https://t.me/{await self.bot_username()}?start=welcome"
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=self.t("start_button"), url=link)]]
        )

    # Mini App entry ------------------------------------------------------
    def miniapp_url(self) -> str | None:
        """The Mini App address for this tenant. Telegram only accepts https."""
        base = (self.settings.webapp_url or "").rstrip("/")
        if not base.startswith("https://"):
            return None
        return f"{base}/?tenant={self.tenant_id}"

    def miniapp_keyboard(self) -> ReplyKeyboardMarkup | None:
        """The always-visible blue button above the keyboard."""
        url = self.miniapp_url()
        if url is None:
            return None
        button = KeyboardButton(
            text=self.t("open_miniapp"), web_app=WebAppInfo(url=url), style=BLUE
        )
        return ReplyKeyboardMarkup(keyboard=[[button]], is_persistent=True, resize_keyboard=True)

    async def offer_miniapp(self, chat_id: int, thread_id: int | None = None) -> None:
        """Ask before opening: the app opens only after the person presses Open."""
        url = self.miniapp_url()
        if url is None:
            log.warning("WEBAPP_URL is not an https address: the Mini App offer is skipped")
            return
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=self.t("miniapp_open"), web_app=WebAppInfo(url=url), style=BLUE
                    ),
                    InlineKeyboardButton(text=self.t("miniapp_later"), callback_data=MINIAPP_LATER),
                ]
            ]
        )
        await self.bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=self.t("miniapp_offer"),
            reply_markup=keyboard,
        )

    async def sync_menu_button(self) -> None:
        """The permanent menu button next to the input field opens the Mini App."""
        url = self.miniapp_url()
        if url is None:
            return
        await self.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text=self.t("open_miniapp"), web_app=WebAppInfo(url=url))
        )

    # private chat --------------------------------------------------------
    async def handle_start(self, user: User, chat_id: int) -> None:
        async with self._lock((self.tenant_id, user.id)):
            row = await self._upsert(user)
            await self.repo.update_user(row.id, dm_chat_id=chat_id)
            if row.dm_topics_supported is False:
                await self._send_project_picker(chat_id, "dm_topics_unavailable")
                return
            created: dict[str, int] = {}
            for kind in DM_KINDS:
                if await self.repo.get_topic(self.tenant_id, row.id, kind):
                    continue
                try:
                    topic = await self.bot.create_forum_topic(
                        chat_id=chat_id, name=self.t(f"topic_{kind}")
                    )
                except (TelegramBadRequest, TelegramForbiddenError) as exc:
                    log.info("private topics unavailable: %s", type(exc).__name__)
                    await self.repo.update_user(row.id, dm_topics_supported=False)
                    await self._send_project_picker(chat_id, "dm_topics_unavailable")
                    return
                if await self.repo.add_topic(
                    self.tenant_id, row.id, kind, chat_id, topic.message_thread_id
                ):
                    created[kind] = topic.message_thread_id
            await self.repo.update_user(row.id, dm_topics_supported=True)
            if created:
                intro_thread = created.get("dm_profile") or next(iter(created.values()))
                await self.bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=intro_thread,
                    text=self.t("dm_ready", name=self.display_name(user)),
                    reply_markup=self.miniapp_keyboard(),
                )
                await self.offer_miniapp(chat_id, intro_thread)
            else:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=self.t("dm_already_ready"),
                    reply_markup=self.miniapp_keyboard(),
                )

    async def _send_project_picker(self, chat_id: int, intro_key: str) -> None:
        rows = [
            [InlineKeyboardButton(text=self.t(f"topic_{k}"), callback_data=context_callback(k))]
            for k in DM_KINDS
        ]
        await self.bot.send_message(
            chat_id=chat_id,
            text=self.t(intro_key),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    async def handle_project(self, user: User, chat_id: int) -> None:
        await self._upsert(user)
        await self._send_project_picker(chat_id, "project_pick")

    async def set_context(self, tg_id: int, kind: str) -> bool:
        row = await self.repo.get_user(self.tenant_id, tg_id)
        if row is None:
            return False
        await self.repo.update_user(row.id, active_context=kind)
        return True

    # owner ---------------------------------------------------------------
    async def handle_help(self, user: User, chat_id: int) -> None:
        text = self.t("help_text")
        if self.is_owner(user.id):
            text += "\n" + self.t("help_owner")
        await self.bot.send_message(chat_id=chat_id, text=text)

    async def handle_owner_command(self, user: User, chat_id: int, command: str) -> None:
        if not self.is_owner(user.id):
            await self.bot.send_message(chat_id=chat_id, text=self.t("owner_only"))
            return
        total, rows = await self.repo.members(self.tenant_id)
        if command == "admin":
            await self.bot.send_message(chat_id=chat_id, text=self.t("admin_summary", total=total))
            return
        lines = [self.t("members_item", name=self.display_name(r), role=r.role) for r in rows]
        await self.bot.send_message(
            chat_id=chat_id, text="\n".join([self.t("members_header", total=total), *lines])
        )

    # menus ---------------------------------------------------------------
    async def sync_commands(self) -> None:
        """Everyone sees the public commands; only the owner's chat also gets the owner commands."""
        public = [BotCommand(command=c, description=self.t(f"cmd_{c}")) for c in PUBLIC_COMMANDS]
        owner = [BotCommand(command=c, description=self.t(f"cmd_{c}")) for c in OWNER_COMMANDS]
        await self.bot.set_my_commands(public, scope=BotCommandScopeDefault())
        await self.sync_menu_button()
        if self.settings.owner_tg_id is not None:
            await self.bot.set_my_commands(
                public + owner, scope=BotCommandScopeChat(chat_id=self.settings.owner_tg_id)
            )
