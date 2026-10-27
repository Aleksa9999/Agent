import pytest

from app.i18n import MissingTranslationError, Translator
from app.tenants import TenantRegistry
from tests.conftest import ROOT


def _translator(tenants_dir):
    registry = TenantRegistry.load(tenants_dir)
    return registry, Translator(ROOT / "locales", registry)


def test_second_tenant_needs_only_a_config_file(partner_tenant):
    registry, tr = _translator(partner_tenant)
    assert registry.ids() == ["acme", "default"]
    assert "Googlagent" in tr.t("default", "greeting")
    assert tr.t("acme", "greeting").startswith("Hi! I am Acme Agent")
    assert tr.t("acme", "start_button") == "Meet Acme"  # tenant override
    assert tr.t("default", "start_button") == "Начать с моим агентом"


def test_bot_tokens_come_from_tenant_specific_variables(partner_tenant, monkeypatch):
    registry = TenantRegistry.load(partner_tenant)
    monkeypatch.setenv("ACME_TEST_BOT_TOKEN", "acme-test-value")
    monkeypatch.setenv("TG_TEST_BOT_TOKEN", "default-test-value")
    monkeypatch.delenv("ACME_BOT_TOKEN", raising=False)
    assert registry.bot_token("acme", test=True) == "acme-test-value"
    assert registry.bot_token("default", test=True) == "default-test-value"
    assert registry.bot_token("acme", test=False) is None


def test_invalid_tenant_files_are_rejected(tenants_dir):
    (tenants_dir / "bad.yaml").write_text(
        "id: Bad Id\nbrand_name: X\nbot_token_env: lower\n"
        "test_bot_token_env: A\nwebapp_url_env: B\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        TenantRegistry.load(tenants_dir)


def test_unknown_tenant_and_missing_key_fail_loudly(tenants_dir):
    registry, tr = _translator(tenants_dir)
    with pytest.raises(KeyError):
        registry.get("nobody")
    with pytest.raises(MissingTranslationError):
        tr.t("default", "no_such_key")


def test_every_russian_key_exists_in_english():
    registry = TenantRegistry.load(ROOT / "config/tenants")
    tr = Translator(ROOT / "locales", registry)
    assert tr.keys("ru") == tr.keys("en")
