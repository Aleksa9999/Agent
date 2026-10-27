from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tenants_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "tenants"
    directory.mkdir()
    (directory / "default.yaml").write_text(
        (ROOT / "config/tenants/default.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return directory


@pytest.fixture
def partner_tenant(tenants_dir: Path) -> Path:
    """A second brand: one YAML file, nothing else."""
    (tenants_dir / "acme.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "acme",
                "brand_name": "Acme Agent",
                "locale": "en",
                "bot_token_env": "ACME_BOT_TOKEN",
                "test_bot_token_env": "ACME_TEST_BOT_TOKEN",
                "webapp_url_env": "ACME_WEBAPP_URL",
                "strings": {"start_button": "Meet Acme"},
            }
        ),
        encoding="utf-8",
    )
    return tenants_dir
