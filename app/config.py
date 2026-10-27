"""Application settings. Everything comes from environment variables (see .env.example)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: Literal["test", "prod"] = "test"
    tenants_dir: Path = Path("config/tenants")
    locales_dir: Path = Path("locales")
    default_tenant: str = "default"

    database_url: str = "sqlite:///./local.db"
    redis_url: str | None = None

    owner_tg_id: int | None = None
    group_chat_id: int | None = None
    webapp_url: str | None = None
    miniapp_initdata_max_age: int = 3600

    tg_bot_token: SecretStr | None = None
    tg_test_bot_token: SecretStr | None = None
    tg_webhook_secret: SecretStr | None = None
    fernet_key: SecretStr | None = None
    qwen_api_key: SecretStr | None = None
    dashscope_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    github_token: SecretStr | None = None

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url.removeprefix("postgres://")
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url.removeprefix("postgresql://")
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
