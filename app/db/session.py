from sqlalchemy import Engine, create_engine, event

from app.config import Settings


def enable_sqlite_foreign_keys(engine: Engine) -> Engine:
    """SQLite ignores foreign keys unless asked; PostgreSQL never does. Keep tests honest."""
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _pragma(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def make_engine(settings: Settings) -> Engine:
    url = settings.sqlalchemy_url
    options = {"connect_args": {"client_encoding": "utf8"}} if url.startswith("postgresql") else {}
    return enable_sqlite_foreign_keys(create_engine(url, pool_pre_ping=True, **options))
