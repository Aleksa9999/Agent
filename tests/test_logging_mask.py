import json
import logging

from app.config import Settings
from app.logging_setup import MASK, JsonFormatter, mask


def test_token_shaped_values_are_masked():
    bot = "1234567890:" + "A" * 35
    text = f"call https://api.telegram.org/bot{bot}/getMe with sk-{'b' * 24} and ghp_{'c' * 30}"
    masked = mask(text)
    assert bot not in masked and "sk-" + "b" * 24 not in masked and "ghp_" + "c" * 30 not in masked
    assert MASK in masked


def test_password_in_url_and_query_is_masked():
    masked = mask("postgresql://user:hunter2@db:5432/x?password=hunter3&ok=1")
    assert "hunter2" not in masked and "hunter3" not in masked and "ok=1" in masked


def test_values_of_secret_environment_variables_are_masked(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "plain-looking-secret-value")
    assert "plain-looking-secret-value" not in mask("key is plain-looking-secret-value here")


def test_formatter_masks_messages_and_exceptions(monkeypatch):
    monkeypatch.setenv("FERNET_KEY", "another-secret-value-123")
    record = logging.LogRecord(
        "t", logging.ERROR, "f", 1, "boom another-secret-value-123", (), None
    )
    line = json.loads(JsonFormatter().format(record))
    assert "another-secret-value-123" not in line["msg"]


def test_settings_repr_does_not_reveal_secrets():
    settings = Settings(tg_bot_token="1234567890:" + "Z" * 35, qwen_api_key="sk-" + "q" * 30)
    assert "ZZZZZ" not in repr(settings) and "qqqqq" not in repr(settings)
