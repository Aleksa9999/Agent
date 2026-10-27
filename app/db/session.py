from sqlalchemy import Engine, create_engine

from app.config import Settings


def make_engine(settings: Settings) -> Engine:
    return create_engine(settings.sqlalchemy_url, pool_pre_ping=True, future=True)
