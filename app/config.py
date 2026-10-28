"""Application settings. Everything comes from environment variables (see .env.example)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # an empty value in the env file (QWEN_BASE_URL=) means "not set": the default applies
    model_config = SettingsConfigDict(env_file=None, extra="ignore", env_ignore_empty=True)

    app_env: Literal["test", "prod"] = "test"
    tenants_dir: Path = Path("config/tenants")
    locales_dir: Path = Path("locales")
    prompts_dir: Path = Path("prompts")
    skills_dir: Path = Path("content/skills")
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
    qwen_base_url: str = (
        "https://dashscope-intl.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1"
    )
    qwen_model: str | None = None
    qwen_fast_model: str | None = None
    qwen_asr_model: str | None = None
    qwen_asr_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    spec_rules_path: Path = Path("config/spec_rules.yaml")
    privacy_patterns_path: Path = Path("config/privacy_patterns.yaml")
    model_catalog_path: Path = Path("config/model_catalog.yaml")
    context_budget_tokens: int = 60000
    context_keep_last: int = 30
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
