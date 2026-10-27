"""One-off command after a deploy: python -m app.bot.setup [tenant_id]"""

import asyncio
import sys

from app.agent.store import AgentStore
from app.bot.repo import BotRepo
from app.bot.runtime import BotRuntime
from app.config import get_settings
from app.db.session import make_engine
from app.i18n import Translator
from app.tenants import TenantRegistry


async def _main(tenant_id: str | None) -> None:
    settings = get_settings()
    tenants = TenantRegistry.load(settings.tenants_dir)
    engine = make_engine(settings)
    runtime = BotRuntime(
        settings=settings,
        tenants=tenants,
        translator=Translator(settings.locales_dir, tenants),
        repo=BotRepo(engine),
        store=AgentStore(engine),
    )
    if not settings.webapp_url:
        raise SystemExit("WEBAPP_URL is not set")
    target = tenant_id or settings.default_tenant
    await runtime.setup(target, settings.webapp_url)
    print(f"webhook and menus configured for tenant {target}")
    await runtime.service(target).bot.session.close()


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1] if len(sys.argv) > 1 else None))
