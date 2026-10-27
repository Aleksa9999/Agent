"""Builds one Bot and one Dispatcher per tenant and feeds webhook updates into them."""

import logging
from collections.abc import Callable

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.types import Update

from app.bot.handlers import build_router
from app.bot.repo import BotRepo
from app.bot.roles import RoleRegistry
from app.bot.service import OnboardingService
from app.config import Settings
from app.i18n import Translator
from app.tenants import TenantRegistry

log = logging.getLogger("app.bot")

ALLOWED_UPDATES = ["message", "callback_query", "chat_member", "my_chat_member"]


class BotRuntime:
    def __init__(
        self,
        *,
        settings: Settings,
        tenants: TenantRegistry,
        translator: Translator,
        repo: BotRepo,
        bot_factory: Callable[[str], Bot] | None = None,
    ):
        self.settings = settings
        self.tenants = tenants
        self.translator = translator
        self.repo = repo
        self._bot_factory = bot_factory or self._default_bot_factory
        self._services: dict[str, OnboardingService] = {}
        self._dispatchers: dict[str, Dispatcher] = {}

    def _default_bot_factory(self, tenant_id: str, session: BaseSession | None = None) -> Bot:
        token = self.tenants.bot_token(tenant_id, test=self.settings.app_env == "test")
        if not token:
            raise RuntimeError(f"bot token is not configured for tenant {tenant_id}")
        return Bot(token=token, session=session)

    def service(self, tenant_id: str) -> OnboardingService:
        if tenant_id not in self._services:
            self.tenants.get(tenant_id)
            self._services[tenant_id] = OnboardingService(
                bot=self._bot_factory(tenant_id),
                repo=self.repo,
                translator=self.translator,
                roles=RoleRegistry(self.settings.owner_tg_id),
                settings=self.settings,
                tenant_id=tenant_id,
            )
        return self._services[tenant_id]

    def dispatcher(self, tenant_id: str) -> Dispatcher:
        if tenant_id not in self._dispatchers:
            dp = Dispatcher()
            dp.include_router(build_router())
            dp["svc"] = self.service(tenant_id)
            self._dispatchers[tenant_id] = dp
        return self._dispatchers[tenant_id]

    async def feed(self, tenant_id: str, payload: dict) -> None:
        svc = self.service(tenant_id)
        update = Update.model_validate(payload, context={"bot": svc.bot})
        await self.dispatcher(tenant_id).feed_update(svc.bot, update)

    async def setup(self, tenant_id: str, base_url: str) -> None:
        """Register menus and the webhook (run once per environment after a deploy)."""
        svc = self.service(tenant_id)
        secret = self.settings.tg_webhook_secret
        if secret is None:
            raise RuntimeError("TG_WEBHOOK_SECRET is not configured")
        await svc.sync_commands()
        await svc.bot.set_webhook(
            url=f"{base_url.rstrip('/')}/telegram/webhook/{tenant_id}",
            secret_token=secret.get_secret_value(),
            allowed_updates=ALLOWED_UPDATES,
        )
