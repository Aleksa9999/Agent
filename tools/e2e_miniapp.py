"""Browser check of the Mini App against a running stack (API on :8000, Mini App on :3000).

Telegram is replaced by a stub that supplies launch data signed with TEST_BOT_TOKEN, which must
equal the token the API runs with. Usage: TEST_BOT_TOKEN=... python3 -I tools/e2e_miniapp.py
"""

import hashlib
import hmac
import json
import os
import sys
import time
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

TOKEN = os.environ["TEST_BOT_TOKEN"]
APP = os.environ.get("MINIAPP_URL", "http://localhost:3000")
API = os.environ.get("API_URL", "http://localhost:8000")


def signed(auth_date: int, name: str = "Anna") -> str:
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAH",
        "user": json.dumps({"id": 7, "first_name": name, "language_code": "ru"}),
    }
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def screen(init_data: str | None) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 780})
        if init_data is None:
            stub = "window.Telegram = undefined"
        else:
            stub = (
                "window.Telegram = {WebApp: {initData: "
                + json.dumps(init_data)
                + ", ready(){}, expand(){}, initDataUnsafe: {user: {language_code: 'ru'}}}}"
            )
        page.add_init_script(stub)
        page.route("**/telegram.org/**", lambda r: r.abort())
        page.route("**/api/**", lambda r: r.continue_(url=r.request.url.replace(APP, API)))
        page.goto(f"{APP}/?tenant=default")
        page.wait_for_timeout(1500)
        text = page.inner_text("main").replace("\n", " | ")
        browser.close()
        return text


now = int(time.time())
checks = [
    ("valid launch data", signed(now), "Привет, Anna!"),
    ("expired launch data", signed(now - 86_400), "Сессия устарела"),
    (
        "forged launch data",
        signed(now, "Anna").replace("Anna", "Evil"),
        "Не удалось подтвердить вход",
    ),
    ("outside Telegram", None, "Откройте из Telegram"),
]
failed = 0
for label, data, expected in checks:
    got = screen(data)
    ok = expected in got
    failed += not ok
    print(("PASS" if ok else "FAIL"), label, "->", got)
sys.exit(1 if failed else 0)
