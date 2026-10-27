from sqlalchemy import Engine, create_engine

from app.config import Settings


def make_engine(settings: Settings) -> Engine:
    url = settings.sqlalchemy_url
    options = {"connect_args": {"client_encoding": "utf8"}} if url.startswith("postgresql") else {}
    return create_engine(url, pool_pre_ping=True, **options)
