import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import Base, Tenant
from app.db.models import User
from app.db.session import enable_sqlite_foreign_keys
from app.db.tenants_sync import sync_tenants
from app.main import create_app
from app.tenants import TenantRegistry


@pytest.fixture
def empty_db(tmp_path):
    engine = enable_sqlite_foreign_keys(create_engine(f"sqlite:///{tmp_path / 'sync.db'}"))
    Base.metadata.create_all(engine)
    return engine


def test_a_user_without_a_tenant_row_is_rejected_like_on_postgres(empty_db):
    with pytest.raises(IntegrityError), Session(empty_db) as session, session.begin():
        session.add(User(tenant_id="default", tg_id=1, first_name="A"))


def test_sync_creates_updates_and_is_repeatable(empty_db, partner_tenant):
    registry = TenantRegistry.load(partner_tenant)
    sync_tenants(empty_db, registry)
    sync_tenants(empty_db, registry)
    with Session(empty_db) as session:
        rows = {t.id: (t.brand_name, t.locale) for t in session.query(Tenant)}
    assert rows == {"default": ("Googlagent", "ru"), "acme": ("Acme Agent", "en")}
    with Session(empty_db) as session, session.begin():
        session.add(User(tenant_id="acme", tg_id=1, first_name="A"))  # now it is accepted


def test_the_app_registers_its_tenants_when_it_starts(tmp_path, tenants_dir):
    settings = Settings(
        tenants_dir=tenants_dir,
        database_url=f"sqlite:///{tmp_path / 'boot.db'}",
    )
    engine = enable_sqlite_foreign_keys(create_engine(settings.sqlalchemy_url))
    Base.metadata.create_all(engine)
    with TestClient(create_app(settings, checks={})):  # entering the context runs startup
        pass
    with Session(engine) as session:
        assert [t.id for t in session.query(Tenant)] == ["default"]


def test_the_app_still_starts_when_the_database_is_not_ready(tmp_path, tenants_dir):
    settings = Settings(
        tenants_dir=tenants_dir,
        database_url=f"sqlite:///{tmp_path / 'empty.db'}",
    )  # no tables at all
    with TestClient(create_app(settings, checks={})) as client:
        assert client.get("/health").status_code == 200
