"""FastAPI entry point: webhook and Mini App API will hang off this app. Slice 01: /health."""

import hmac
import logging
from collections.abc import Callable

import redis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.bot.repo import BotRepo
from app.bot.runtime import BotRuntime
from app.config import Settings, get_settings
from app.db.session import make_engine
from app.i18n import Translator
from app.logging_setup import setup_logging
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
    app = FastAPI(title="Googlagent", docs_url=None, redoc_url=None, openapi_url=None)
    health_checks = checks if checks is not None else default_checks(settings)
    tenants = TenantRegistry.load(settings.tenants_dir)  # a broken tenant file stops startup
    tenants.get(settings.default_tenant)
    runtimes: list[BotRuntime] = [runtime] if runtime else []

    def get_runtime() -> BotRuntime:
        if not runtimes:
            runtimes.append(
                BotRuntime(
                    settings=settings,
                    tenants=tenants,
                    translator=Translator(settings.locales_dir, tenants),
                    repo=BotRepo(make_engine(settings)),
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
