"""JSON logging with secret masking: tokens never reach stdout or log files."""

import json
import logging
import os
import re
from datetime import UTC, datetime

MASK = "***"
_PATTERNS = [
    re.compile(r"(?<!\d)\d{8,10}:[A-Za-z0-9_-]{30,}"),  # Telegram bot token
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),  # model provider keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),  # GitHub tokens
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)=([^&\s]+)"),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),  # user:password in URLs
]
_SECRET_ENV_HINTS = ("TOKEN", "KEY", "SECRET", "PASSWORD")


def _secret_values() -> list[str]:
    values = []
    for name, value in os.environ.items():
        if value and len(value) >= 8 and any(h in name.upper() for h in _SECRET_ENV_HINTS):
            values.append(value)
    return sorted(values, key=len, reverse=True)


def mask(text: str) -> str:
    for value in _secret_values():
        text = text.replace(value, MASK)
    for pattern in _PATTERNS:
        text = pattern.sub(
            lambda m: (m.group(1) + "=" + MASK) if m.lastindex and m.lastindex >= 2 else MASK,
            text,
        )
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": mask(record.getMessage()),
        }
        if record.exc_info:
            payload["exc"] = mask(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
