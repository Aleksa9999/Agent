"""All human-readable text comes from locales/<lang>.yaml, with per-tenant overrides."""

from pathlib import Path

import yaml

from app.tenants import TenantRegistry

DEFAULT_LOCALE = "ru"


class MissingTranslationError(KeyError):
    pass


class Translator:
    def __init__(self, locales_dir: Path, tenants: TenantRegistry):
        self._tenants = tenants
        self._locales: dict[str, dict[str, str]] = {}
        for path in sorted(Path(locales_dir).glob("*.yaml")):
            self._locales[path.stem] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if DEFAULT_LOCALE not in self._locales:
            raise ValueError(f"default locale '{DEFAULT_LOCALE}' is missing in {locales_dir}")

    def t(self, tenant_id: str, key: str, **values: object) -> str:
        tenant = self._tenants.get(tenant_id)
        template = (
            tenant.strings.get(key)
            or self._locales.get(tenant.locale, {}).get(key)
            or self._locales[DEFAULT_LOCALE].get(key)
        )
        if template is None:
            raise MissingTranslationError(f"{key} ({tenant.locale})")
        return template.format(brand=tenant.brand_name, **values)

    def keys(self, locale: str) -> set[str]:
        return set(self._locales[locale])
