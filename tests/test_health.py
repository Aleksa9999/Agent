from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import ROOT

TENANTS = ROOT / "config" / "tenants"


def _client(checks):
    return TestClient(create_app(Settings(app_env="test", tenants_dir=TENANTS), checks=checks))


def test_health_ok_when_all_checks_pass():
    response = _client({"db": lambda: None, "redis": lambda: None}).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "env": "test",
        "tenants": ["default"],
        "checks": {"db": "ok", "redis": "ok"},
    }


def test_health_degraded_names_the_failed_dependency_without_leaking_details():
    def broken():
        raise RuntimeError("postgresql://user:hunter2@db/prod refused")

    response = _client({"db": broken, "redis": lambda: None}).get("/health")
    assert response.status_code == 503
    assert response.json()["checks"] == {"db": "fail", "redis": "ok"}
    assert "hunter2" not in response.text


def test_api_docs_are_not_exposed():
    client = _client({})
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_health_lists_a_second_tenant_added_only_by_a_config_file(partner_tenant):
    settings = Settings(app_env="test", tenants_dir=partner_tenant)
    body = TestClient(create_app(settings, checks={})).get("/health").json()
    assert body["tenants"] == ["acme", "default"]
