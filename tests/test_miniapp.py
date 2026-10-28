"""Mini App entry: signed launch data, the session endpoint, the blue button and the offer."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.miniapp_api.auth import InvalidInitDataError, verify_init_data
from tests.conftest import OWNER_ID
from tests.fake_telegram import callback_update, command_update, person

TOKEN = "123456:TEST-BOT-TOKEN-FOR-TESTS-ONLY"
NOW = 1_800_000_000
URL = "https://app.example.test"


def signed(bot_token: str = TOKEN, *, user_id: int = 7, auth_date: int = NOW, **overrides) -> str:
    """Launch data built the way the Telegram documentation describes (independent of app code)."""
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAH",
        "user": json.dumps({"id": user_id, "first_name": "Anna", "language_code": "ru"}),
        **overrides,
    }
    lines = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, lines.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_launch_data_is_accepted():
    user = verify_init_data(signed(), TOKEN, now=NOW + 10)
    assert (user.id, user.first_name, user.language_code) == (7, "Anna", "ru")


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda: "", "missing"),
        (lambda: "auth_date=1&user=%7B%7D", "missing_hash"),
        (lambda: signed("999:OTHER-BOT-TOKEN"), "invalid_signature"),
        (lambda: signed().replace("Anna", "Evil"), "invalid_signature"),
        (lambda: signed(user_id=8).replace("id%22%3A+8", "id%22%3A+1"), "invalid_signature"),
        (lambda: signed(auth_date=NOW - 7200), "expired"),
        (lambda: signed(auth_date=NOW + 3600), "invalid_auth_date"),
        (lambda: signed(auth_date="abc"), "invalid_auth_date"),
        (lambda: signed(user="not json"), "invalid_user"),
    ],
)
def test_forged_stale_or_broken_launch_data_is_rejected(make, reason):
    with pytest.raises(InvalidInitDataError) as caught:
        verify_init_data(make(), TOKEN, now=NOW)
    assert caught.value.reason == reason


def test_a_hash_alone_cannot_be_replayed_with_new_fields():
    original = signed()
    forged = original + "&extra=1"  # extra field changes the data-check string
    with pytest.raises(InvalidInitDataError):
        verify_init_data(forged, TOKEN, now=NOW)


@pytest.fixture
def client(settings, runtime, monkeypatch):
    monkeypatch.setenv("TG_TEST_BOT_TOKEN", TOKEN)
    return TestClient(create_app(settings, checks={}, runtime=runtime))


def _post(client, init_data, tenant="default", scheme="tma"):
    headers = {"Authorization": f"{scheme} {init_data}"} if init_data is not None else {}
    return client.post(f"/api/miniapp/{tenant}/session", headers=headers)


def test_session_returns_the_person_the_role_and_the_brand(client):
    fresh = signed(auth_date=int(time.time()))
    response = _post(client, fresh)
    assert response.status_code == 200
    assert response.json() == {
        "user": {"id": 7, "first_name": "Anna", "role": "member"},
        "brand": "Googlagent",
        "locale": "ru",
    }


def test_session_marks_the_owner_by_registry(client):
    body = _post(client, signed(user_id=OWNER_ID, auth_date=int(time.time()))).json()
    assert body["user"]["role"] == "owner"


def test_session_rejects_forged_and_expired_launch_data(client):
    forged = _post(client, signed("1:OTHER-TOKEN", auth_date=int(time.time())))
    assert (forged.status_code, forged.json()) == (401, {"error": "invalid_signature"})
    old = _post(client, signed(auth_date=int(time.time()) - 86_400))
    assert (old.status_code, old.json()) == (401, {"error": "expired"})
    assert _post(client, None).status_code == 401
    assert _post(client, signed(auth_date=int(time.time())), scheme="Bearer").status_code == 401


def test_session_needs_a_known_tenant_and_a_configured_token(settings, runtime, monkeypatch):
    app_client = TestClient(create_app(settings, checks={}, runtime=runtime))
    monkeypatch.delenv("TG_TEST_BOT_TOKEN", raising=False)
    assert _post(app_client, signed()).status_code == 503
    assert _post(app_client, signed(), tenant="nobody").status_code == 404


async def test_start_removes_the_old_keyboard_button_and_offers_a_blue_open_button(
    runtime, session
):
    """An app opened from a keyboard button gets no sign-in data, so that button is gone;
    the sign-in works from the menu button and from the inline "Open" button."""
    runtime.settings.webapp_url = URL
    anna = person(7)
    await runtime.feed("default", command_update(anna, "/start"))

    intro, offer = session.of("sendMessage")[-2:]
    assert intro.reply_markup.remove_keyboard is True  # the persistent button is taken away

    open_button, later_button = offer.reply_markup.inline_keyboard[0]
    assert "Откроем Mini App?" in offer.text
    assert (open_button.text, open_button.style) == ("Открыть", "primary")
    assert open_button.web_app.url == f"{URL}/?tenant=default"
    assert (later_button.text, later_button.callback_data) == ("Не сейчас", "v1:miniapp:later")
    assert later_button.web_app is None  # only "Open" can launch the app: nothing opens by itself


async def test_not_now_dismisses_the_offer_politely(runtime, session):
    anna = person(7)
    await runtime.feed("default", callback_update(anna, "v1:miniapp:later", message_id=55))
    (answer,) = session.of("answerCallbackQuery")
    assert "Кнопка" in answer.text and not answer.show_alert
    (deleted,) = session.of("deleteMessage")
    assert deleted.message_id == 55


async def test_setup_installs_the_menu_button(runtime, session):
    runtime.settings.webapp_url = URL
    await runtime.setup("default", URL)
    (menu,) = session.of("setChatMenuButton")
    assert menu.menu_button.web_app.url == f"{URL}/?tenant=default"


async def test_without_an_https_address_there_is_no_open_button_and_no_offer(runtime, session):
    runtime.settings.webapp_url = "http://insecure.example.test"
    await runtime.feed("default", command_update(person(7), "/start"))
    for message in session.of("sendMessage"):
        markup = message.reply_markup
        assert markup is None or getattr(markup, "remove_keyboard", False)  # never an app button
        assert not getattr(markup, "inline_keyboard", None)
    await runtime.service("default").sync_menu_button()
    assert session.of("setChatMenuButton") == []
