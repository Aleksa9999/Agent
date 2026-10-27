from alembic import context
from sqlalchemy import create_engine

from app.config import Settings
import app.db.models  # noqa: F401  (registers tables on the metadata)
from app.db.base import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    url = context.config.attributes.get("url") or Settings().sqlalchemy_url
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
