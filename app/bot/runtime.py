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
from app.bot.publisher import GroupPublisher
from app.bot.repo import BotRepo
from app.bot.roles import RoleRegistry
from app.bot.service import OnboardingService
from app.bot.voice import VoiceIntake
from app.config import Settings
from app.i18n import Translator
from app.profile.asr import AsrPort, QwenAsrClient
from app.profile.passport import PassportStore
from app.profile.service import ProfileService
from app.profile.store import ProfileStore
from app.ratelimit import RateLimiter
from app.skills.store import SkillStore
from app.tenants import TenantRegistry
from app.track.service import FirstResultService, HomeService, TrackService
from app.track.store import FirstResultStore, UserSkillStore

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
        profiles: ProfileStore | None = None,
        passports: PassportStore | None = None,
        user_skills: UserSkillStore | None = None,
        first_results: FirstResultStore | None = None,
        asr_factory: Callable[[str], AsrPort | None] | None = None,
        bot_factory: Callable[[str], Bot] | None = None,
        model_factory: Callable[[str], ModelPort | None] | None = None,
    ):
        self.settings = settings
        self.tenants = tenants
        self.translator = translator
        self.repo = repo
        self.store = store
        self.skills = skills
        self.profiles = profiles
        self.passports = passports
        self.user_skills = user_skills
        self.first_results = first_results
        self.first_result_limiter = RateLimiter(limit=3, window_seconds=600)
        self._homes: dict[str, HomeService] = {}
        self._first: dict[str, FirstResultService] = {}
        self._asr_factory = asr_factory or self._default_asr_factory
        self._profile_services: dict[str, ProfileService] = {}
        self._voice: dict[str, VoiceIntake] = {}
        self.voice_limiter = RateLimiter(limit=6, window_seconds=600)
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

    def _default_asr_factory(self, tenant_id: str) -> AsrPort | None:
        key = self.settings.qwen_api_key or self.settings.dashscope_api_key
        if key is None or not self.settings.qwen_asr_model:
            return None  # voice is off until a key and an ASR model id are configured
        return QwenAsrClient(
            base_url=self.settings.qwen_asr_base_url,
            api_key=key.get_secret_value(),
            model=self.settings.qwen_asr_model,
        )

    def profile(self, tenant_id: str) -> ProfileService | None:
        """The entrance test service; None when the database layer was not given."""
        if self.profiles is None:
            return None
        if tenant_id not in self._profile_services:
            self.tenants.get(tenant_id)
            self._profile_services[tenant_id] = ProfileService(
                store=self.profiles,
                translator=self.translator,
                prompts_dir=self.settings.prompts_dir,
                model=self._model_factory(tenant_id),
                asr=self._asr_factory(tenant_id),
                passports=self.passports,
                publisher=GroupPublisher(
                    self.service(tenant_id), self.settings.privacy_patterns_path
                )
                if self.passports is not None
                else None,
                privacy_path=self.settings.privacy_patterns_path,
                tracks=self._tracks(),
            )
        return self._profile_services[tenant_id]

    def _tracks(self) -> TrackService | None:
        if self.skills is None or self.user_skills is None:
            return None
        return TrackService(skills=self.skills, user_skills=self.user_skills)

    def _track_stores_ready(self) -> bool:
        return all(
            x is not None
            for x in (self.passports, self.user_skills, self.first_results, self.skills)
        )

    def home(self, tenant_id: str) -> HomeService | None:
        """The "My Googlagent" screen; None when the stores were not given."""
        if not self._track_stores_ready():
            return None
        if tenant_id not in self._homes:
            profile = self.profile(tenant_id)
            self._homes[tenant_id] = HomeService(
                passports=self.passports,  # type: ignore[arg-type]
                user_skills=self.user_skills,  # type: ignore[arg-type]
                skills=self.skills,  # type: ignore[arg-type]
                results=self.first_results,  # type: ignore[arg-type]
                voice_available=bool(profile and profile.voice_available),
            )
        return self._homes[tenant_id]

    def first_result(self, tenant_id: str) -> FirstResultService | None:
        if not self._track_stores_ready():
            return None
        if tenant_id not in self._first:
            self._first[tenant_id] = FirstResultService(
                passports=self.passports,  # type: ignore[arg-type]
                results=self.first_results,  # type: ignore[arg-type]
                translator=self.translator,
                prompts_dir=self.settings.prompts_dir,
                model=self._model_factory(tenant_id),
            )
        return self._first[tenant_id]

    def voice(self, tenant_id: str) -> VoiceIntake | None:
        profile = self.profile(tenant_id)
        if profile is None:
            return None
        if tenant_id not in self._voice:
            self._voice[tenant_id] = VoiceIntake(
                svc=self.service(tenant_id), profile=profile, limiter=self.voice_limiter
            )
        return self._voice[tenant_id]

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
            dp["voice"] = self.voice(tenant_id)
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
