"""FastAPI entry point: webhook and Mini App API will hang off this app. Slice 01: /health."""

import hmac
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.agent.store import AgentStore
from app.bot.repo import BotRepo
from app.bot.roles import RoleRegistry
from app.bot.runtime import BotRuntime
from app.config import Settings, get_settings
from app.db.session import make_engine
from app.db.tenants_sync import sync_tenants
from app.i18n import Translator
from app.logging_setup import setup_logging
from app.miniapp_api.auth import InvalidInitDataError, TelegramUser, verify_init_data
from app.miniapp_api.profile import register_profile_routes
from app.profile.passport import PassportStore
from app.profile.store import ProfileStore
from app.skills.catalog import catalog_view
from app.skills.store import SkillStore
from app.tenants import TenantRegistry

log = logging.getLogger("app")
Check = Callable[[], None]


def default_checks(settings: Settings) -> dict[str, Check]:
    engine = make_engine(settings)

    def check_db() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    checks: dict[str, Check] = {"db": check_db}
    if settings.redis_url:
        client = redis.Redis.from_url(
            settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        )

        def check_redis() -> None:
            client.ping()

        checks["redis"] = check_redis
    return checks


def create_app(
    settings: Settings | None = None,
    checks: dict[str, Check] | None = None,
    runtime: BotRuntime | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    setup_logging()
    tenants = TenantRegistry.load(settings.tenants_dir)  # a broken tenant file stops startup
    tenants.get(settings.default_tenant)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            sync_tenants(make_engine(settings), tenants)
        except Exception as exc:  # the app must still start: /health will show a broken database
            log.error("tenants were not synced: %s", type(exc).__name__)
        try:
            count = skill_store().sync_repo(settings.skills_dir, tenants.ids())
            log.info("skills loaded from the repository: %d", count)
        except Exception as exc:  # the catalog is empty until the next start, the app still works
            log.error("skills were not loaded: %s", type(exc).__name__)
        yield

    stores: list[SkillStore] = []

    def skill_store() -> SkillStore:
        if not stores:
            stores.append(SkillStore(make_engine(settings)))
        return stores[0]

    app = FastAPI(
        title="Googlagent", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    health_checks = checks if checks is not None else default_checks(settings)
    runtimes: list[BotRuntime] = [runtime] if runtime else []

    def get_runtime() -> BotRuntime:
        if not runtimes:
            engine = make_engine(settings)
            runtimes.append(
                BotRuntime(
                    settings=settings,
                    tenants=tenants,
                    translator=Translator(settings.locales_dir, tenants),
                    repo=BotRepo(engine),
                    store=AgentStore(engine),
                    skills=skill_store(),
                    profiles=ProfileStore(engine),
                    passports=PassportStore(engine),
                )
            )
        return runtimes[0]

    @app.get("/health")
    def health() -> JSONResponse:
        results: dict[str, str] = {}
        for name, check in health_checks.items():
            try:
                check()
                results[name] = "ok"
            except Exception as exc:  # health must report, never raise
                log.warning("health check failed: %s (%s)", name, type(exc).__name__)
                results[name] = "fail"
        ok = all(v == "ok" for v in results.values())
        body = {
            "status": "ok" if ok else "degraded",
            "env": settings.app_env,
            "tenants": tenants.ids(),
            "checks": results,
        }
        return JSONResponse(body, status_code=200 if ok else 503)

    def authenticate(tenant_id: str, request: Request) -> TelegramUser | JSONResponse:
        """Only launch data signed by Telegram is accepted; returns the person or the error."""
        if tenant_id not in tenants.ids():
            return JSONResponse({"error": "unknown_tenant"}, status_code=404)
        token = tenants.bot_token(tenant_id, test=settings.app_env == "test")
        if not token:
            return JSONResponse({"error": "not_configured"}, status_code=503)
        scheme, _, init_data = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "tma":
            return JSONResponse({"error": "missing"}, status_code=401)
        try:
            return verify_init_data(
                init_data, token, max_age_seconds=settings.miniapp_initdata_max_age
            )
        except InvalidInitDataError as exc:
            return JSONResponse({"error": exc.reason}, status_code=401)

    @app.post("/api/miniapp/{tenant_id}/session")
    def miniapp_session(tenant_id: str, request: Request) -> JSONResponse:
        """Opens a Mini App session."""
        user = authenticate(tenant_id, request)
        if isinstance(user, JSONResponse):
            return user
        tenant = tenants.get(tenant_id)
        role = RoleRegistry(settings.owner_tg_id).role_of(user.id)
        return JSONResponse(
            {
                "user": {"id": user.id, "first_name": user.first_name, "role": role},
                "brand": tenant.brand_name,
                "locale": tenant.locale,
            }
        )

    register_profile_routes(
        app, authenticate=authenticate, get_runtime=get_runtime, settings=settings
    )

    @app.get("/api/miniapp/{tenant_id}/catalog")
    def miniapp_catalog(tenant_id: str, request: Request) -> JSONResponse:
        """The skill catalog: studio directions as cards and the branches of the tree."""
        user = authenticate(tenant_id, request)
        if isinstance(user, JSONResponse):
            return user
        try:
            docs = skill_store().catalog(tenant_id)
        except Exception as exc:  # a broken database must not look like an empty catalog
            log.error("catalog was not read: %s", type(exc).__name__)
            return JSONResponse({"error": "unavailable"}, status_code=503)
        return JSONResponse(catalog_view(docs), headers={"Cache-Control": "no-store"})

    @app.post("/telegram/webhook/{tenant_id}")
    async def telegram_webhook(tenant_id: str, request: Request) -> JSONResponse:
        secret = settings.tg_webhook_secret
        if secret is None:
            return JSONResponse({"ok": False}, status_code=503)  # fail closed until configured
        given = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(given.encode(), secret.get_secret_value().encode()):
            return JSONResponse({"ok": False}, status_code=403)
        if tenant_id not in tenants.ids():
            return JSONResponse({"ok": False}, status_code=404)
        try:
            await get_runtime().feed(tenant_id, await request.json())
        except Exception as exc:  # Telegram retries non-200 forever; log and acknowledge
            log.error("update was not processed: %s", type(exc).__name__)
        return JSONResponse({"ok": True})

    return app


def app_factory() -> FastAPI:
    return create_app()
