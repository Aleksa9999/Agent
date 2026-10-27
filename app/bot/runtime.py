"""Builds one Bot and one Dispatcher per tenant and feeds webhook updates into them."""

import logging
from collections.abc import Callable

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.types import Update

from app.agent.catalog import ModelCatalog
from app.agent.context import ContextBuilder
from app.agent.model import ModelPort, QwenResponsesClient
from app.agent.orchestrator import Agent
from app.agent.skills_index import skill_names
from app.agent.store import AgentStore
from app.agent.tools import ToolRegistry
from app.bot.chat import AgentChat
from app.bot.handlers import build_router
from app.bot.repo import BotRepo
from app.bot.roles import RoleRegistry
from app.bot.service import OnboardingService
from app.config import Settings
from app.i18n import Translator
from app.skills.store import SkillStore
from app.tenants import TenantRegistry

log = logging.getLogger("app.bot")


class BotRuntime:
    def __init__(
        self,
        *,
        settings: Settings,
        tenants: TenantRegistry,
        translator: Translator,
        repo: BotRepo,
        store: AgentStore,
        skills: SkillStore | None = None,
        bot_factory: Callable[[str], Bot] | None = None,
        model_factory: Callable[[str], ModelPort | None] | None = None,
    ):
        self.settings = settings
        self.tenants = tenants
        self.translator = translator
        self.repo = repo
        self.store = store
        self.skills = skills
        self._model_factory = model_factory or self._default_model_factory
        self._chats: dict[str, AgentChat] = {}
        self._bot_factory = bot_factory or self._default_bot_factory
        self._services: dict[str, OnboardingService] = {}
        self._dispatchers: dict[str, Dispatcher] = {}

    def _default_bot_factory(self, tenant_id: str, session: BaseSession | None = None) -> Bot:
        token = self.tenants.bot_token(tenant_id, test=self.settings.app_env == "test")
        if not token:
            raise RuntimeError(f"bot token is not configured for tenant {tenant_id}")
        return Bot(token=token, session=session)

    def _default_model_factory(self, tenant_id: str) -> ModelPort | None:
        key = self.settings.qwen_api_key or self.settings.dashscope_api_key
        if key is None or not self.settings.qwen_model:
            return None  # the agent answers "unavailable" until a key and a model id are configured
        return QwenResponsesClient(
            base_url=self.settings.qwen_base_url,
            api_key=key.get_secret_value(),
            model=self.settings.qwen_model,
            fast_model=self.settings.qwen_fast_model,
        )

    def chat(self, tenant_id: str) -> AgentChat:
        if tenant_id not in self._chats:
            svc = self.service(tenant_id)
            model = self._model_factory(tenant_id)
            agent = None
            if model is not None:
                tools = ToolRegistry(
                    model=model,
                    catalog=ModelCatalog.load(self.settings.model_catalog_path),
                    translator=self.translator,
                    tenant_id=tenant_id,
                    prompts_dir=self.settings.prompts_dir,
                )
                agent = Agent(
                    model=model,
                    tools=tools,
                    context=ContextBuilder(
                        budget_tokens=self.settings.context_budget_tokens,
                        keep_last=self.settings.context_keep_last,
                    ),
                    translator=self.translator,
                    tenant_id=tenant_id,
                    prompts_dir=self.settings.prompts_dir,
                )
            self._chats[tenant_id] = AgentChat(
                svc=svc,
                store=self.store,
                agent=agent,
                prompts_dir=self.settings.prompts_dir,
                methods_index=skill_names(self.settings.skills_dir),
            )
        return self._chats[tenant_id]

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
                skills=self.skills,
            )
        return self._services[tenant_id]

    def dispatcher(self, tenant_id: str) -> Dispatcher:
        if tenant_id not in self._dispatchers:
            dp = Dispatcher()
            dp.include_router(build_router())
            dp["svc"] = self.service(tenant_id)
            dp["chat"] = self.chat(tenant_id)
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
            allowed_updates=self.dispatcher(tenant_id).resolve_used_update_types(),
        )
