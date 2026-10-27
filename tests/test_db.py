import os
import subprocess
import sys

import sqlalchemy as sa
from sqlalchemy import Column, MetaData, String, Table

from app.db.base import Base, tables_without_tenant
from tests.conftest import ROOT


def test_every_table_is_tenant_scoped():
    assert tables_without_tenant(Base.metadata) == []


def test_rule_catches_a_table_without_tenant_id():
    metadata = MetaData()
    Table("tenants", metadata, Column("id", String, primary_key=True))
    Table("notes", metadata, Column("id", String, primary_key=True))
    Table(
        "ok",
        metadata,
        Column("id", String, primary_key=True),
        Column("tenant_id", String, nullable=False),
    )
    assert tables_without_tenant(metadata) == ["notes"]


def _alembic(url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )


def _empty_database(url: str) -> None:
    """A shared Postgres may hold tables left by other tests; migrations need an empty one."""
    if url.startswith("sqlite"):
        return
    engine = sa.create_engine(url.replace("postgresql://", "postgresql+psycopg2://"))
    with engine.begin() as connection:
        connection.execute(sa.text("DROP SCHEMA public CASCADE"))
        connection.execute(sa.text("CREATE SCHEMA public"))
    engine.dispose()


def test_migrations_go_up_and_down(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'm.db'}"
    _empty_database(url)
    _alembic(url, "upgrade", "head")
    engine = sa.create_engine(
        url if url.startswith("sqlite") else url.replace("postgresql://", "postgresql+psycopg2://")
    )
    assert "tenants" in sa.inspect(engine).get_table_names()
    _alembic(url, "downgrade", "base")
    assert "tenants" not in sa.inspect(engine).get_table_names()
