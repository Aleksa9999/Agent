"""Verification of Telegram Mini App launch data (initData).

Algorithm from the Telegram documentation: the data-check string is every received field except
`hash`, sorted by name, as `name=value` lines joined with newlines. It is signed with
HMAC-SHA256 using a key derived as HMAC-SHA256("WebAppData", bot_token). The launch time must be
recent. Anything else is rejected.
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

DEFAULT_MAX_AGE_SECONDS = 3600
CLOCK_SKEW_SECONDS = 60


class InvalidInitDataError(Exception):
    """`reason` is a short machine-readable code that is safe to show to the client."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class TelegramUser:
    id: int
    first_name: str
    last_name: str | None
    username: str | None
    language_code: str | None


def sign(data_check_string: str, bot_token: str) -> str:
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()


def verify_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: float | None = None,
) -> TelegramUser:
    if not init_data:
        raise InvalidInitDataError("missing")
    fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received_hash = fields.pop("hash", "")
    if not received_hash:
        raise InvalidInitDataError("missing_hash")

    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    if not hmac.compare_digest(sign(check_string, bot_token), received_hash):
        raise InvalidInitDataError("invalid_signature")

    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError):
        raise InvalidInitDataError("invalid_auth_date") from None
    current = time.time() if now is None else now
    if auth_date > current + CLOCK_SKEW_SECONDS:
        raise InvalidInitDataError("invalid_auth_date")
    if current - auth_date > max_age_seconds:
        raise InvalidInitDataError("expired")

    try:
        user = json.loads(fields["user"])
        return TelegramUser(
            id=int(user["id"]),
            first_name=str(user.get("first_name", "")),
            last_name=user.get("last_name"),
            username=user.get("username"),
            language_code=user.get("language_code"),
        )
    except (KeyError, ValueError, TypeError):
        raise InvalidInitDataError("invalid_user") from None
