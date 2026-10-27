import os
from pathlib import Path

import pytest
import yaml
from aiogram import Bot
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.store import AgentStore
from app.bot.repo import BotRepo
from app.bot.runtime import BotRuntime
from app.config import Settings
from app.db.base import Base, Tenant
from app.db.session import enable_sqlite_foreign_keys
from app.i18n import Translator
from app.tenants import TenantRegistry
from tests.fake_telegram import GROUP_ID, FakeSession

ROOT = Path(__file__).resolve().parent.parent
OWNER_ID = 42
WEBHOOK_SECRET = "webhook-secret-for-tests"


@pytest.fixture
def tenants_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "tenants"
    directory.mkdir()
    (directory / "default.yaml").write_text(
        (ROOT / "config/tenants/default.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return directory


@pytest.fixture
def partner_tenant(tenants_dir: Path) -> Path:
    """A second brand: one YAML file, nothing else."""
    (tenants_dir / "acme.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "acme",
                "brand_name": "Acme Agent",
                "locale": "en",
                "bot_token_env": "ACME_BOT_TOKEN",
                "test_bot_token_env": "ACME_TEST_BOT_TOKEN",
                "webapp_url_env": "ACME_WEBAPP_URL",
                "strings": {"start_button": "Meet Acme"},
            }
        ),
        encoding="utf-8",
    )
    return tenants_dir


@pytest.fixture
def settings(tmp_path: Path, tenants_dir: Path) -> Settings:
    return Settings(
        app_env="test",
        tenants_dir=tenants_dir,
        locales_dir=ROOT / "locales",
        database_url=os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'bot.db'}",
        group_chat_id=GROUP_ID,
        owner_tg_id=OWNER_ID,
        tg_webhook_secret=WEBHOOK_SECRET,
    )


@pytest.fixture
def engine(settings: Settings):
    engine = enable_sqlite_foreign_keys(create_engine(settings.sqlalchemy_url))
    Base.metadata.drop_all(
        engine
    )  # clean slate (matters when TEST_DATABASE_URL points at Postgres)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id="default", brand_name="Googlagent", locale="ru"))
        session.commit()
    return engine


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def runtime(settings: Settings, engine, session: FakeSession) -> BotRuntime:
    tenants = TenantRegistry.load(settings.tenants_dir)
    bot = Bot(token="123456:TESTTOKEN", session=session)
    return BotRuntime(
        settings=settings,
        tenants=tenants,
        translator=Translator(settings.locales_dir, tenants),
        repo=BotRepo(engine),
        store=AgentStore(engine),
        bot_factory=lambda tenant_id: bot,
        model_factory=lambda tenant_id: None,
    )
