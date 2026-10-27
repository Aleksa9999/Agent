"""Tenants: brand, language and bot-token variable names live in config/tenants/*.yaml.

A second brand is a new YAML file plus an environment variable. No code changes.
"""

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class Tenant(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    brand_name: str = Field(min_length=1)
    locale: str = "ru"
    bot_token_env: str
    test_bot_token_env: str
    webapp_url_env: str
    strings: dict[str, str] = {}

    @field_validator("bot_token_env", "test_bot_token_env", "webapp_url_env")
    @classmethod
    def _env_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", value):
            raise ValueError("environment variable name must be UPPER_SNAKE_CASE")
        return value


class TenantRegistry:
    def __init__(self, tenants: dict[str, Tenant]):
        if not tenants:
            raise ValueError("no tenants configured")
        self._tenants = tenants

    @classmethod
    def load(cls, directory: Path) -> "TenantRegistry":
        tenants: dict[str, Tenant] = {}
        for path in sorted(Path(directory).glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            tenant = Tenant(**data)
            if tenant.id in tenants:
                raise ValueError(f"duplicate tenant id: {tenant.id}")
            tenants[tenant.id] = tenant
        return cls(tenants)

    def get(self, tenant_id: str) -> Tenant:
        try:
            return self._tenants[tenant_id]
        except KeyError:
            raise KeyError(f"unknown tenant: {tenant_id}") from None

    def ids(self) -> list[str]:
        return sorted(self._tenants)

    def bot_token(self, tenant_id: str, *, test: bool) -> str | None:
        tenant = self.get(tenant_id)
        return os.environ.get(tenant.test_bot_token_env if test else tenant.bot_token_env) or None

    def webapp_url(self, tenant_id: str) -> str | None:
        return os.environ.get(self.get(tenant_id).webapp_url_env) or None
