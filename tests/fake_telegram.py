"""A recorded stand-in for the Telegram HTTP API, used under the real aiogram Bot."""

import json
from collections.abc import AsyncGenerator
from typing import Any

from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest

BOT_USERNAME = "test_bot"
GROUP_ID = -1001234


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, Any]] = []
        self.private_topics_supported = True
        self._thread = 100
        self._message = 0

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        raise NotImplementedError
        yield b""  # pragma: no cover

    def of(self, api_method: str) -> list[Any]:
        return [m for name, m in self.calls if name == api_method]

    async def make_request(self, bot, method, timeout=None):
        name = method.__api_method__
        self.calls.append((name, method))
        if name == "createForumTopic" and method.chat_id > 0 and not self.private_topics_supported:
            raise TelegramBadRequest(method=method, message="Bad Request: topics are not enabled")
        result: Any = True
        if name == "getMe":
            result = {"id": 999, "is_bot": True, "first_name": "Bot", "username": BOT_USERNAME}
        elif name == "createForumTopic":
            self._thread += 1
            result = {"message_thread_id": self._thread, "name": method.name, "icon_color": 0}
        elif name == "sendMessage":
            self._message += 1
            result = {
                "message_id": self._message,
                "date": 0,
                "chat": {
                    "id": method.chat_id,
                    "type": "private" if method.chat_id > 0 else "supergroup",
                },
                "text": method.text,
            }
        content = json.dumps({"ok": True, "result": result})
        return self.check_response(bot=bot, method=method, status_code=200, content=content).result


def person(
    user_id: int, first_name: str = "Anna", last_name: str | None = "Ivanova", **extra
) -> dict:
    data = {"id": user_id, "is_bot": False, "first_name": first_name, **extra}
    if last_name:
        data["last_name"] = last_name
    return data


def join_update(user: dict, chat_id: int = GROUP_ID, update_id: int = 1) -> dict:
    return {
        "update_id": update_id,
        "chat_member": {
            "chat": {"id": chat_id, "type": "supergroup", "title": "Studio"},
            "from": person(1, "Admin", None),
            "date": 0,
            "old_chat_member": {"status": "left", "user": user},
            "new_chat_member": {"status": "member", "user": user},
        },
    }


def service_join_update(user: dict, chat_id: int = GROUP_ID, update_id: int = 2) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "date": 0,
            "chat": {"id": chat_id, "type": "supergroup", "title": "Studio"},
            "from": user,
            "new_chat_members": [user],
        },
    }


def command_update(user: dict, text: str, update_id: int = 3) -> dict:
    command = text.split()[0]
    return {
        "update_id": update_id,
        "message": {
            "message_id": 2,
            "date": 0,
            "chat": {"id": user["id"], "type": "private"},
            "from": user,
            "text": text,
            "entities": [{"type": "bot_command", "offset": 0, "length": len(command)}],
        },
    }


def callback_update(user: dict, data: str, update_id: int = 4) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": "cb1",
            "from": user,
            "chat_instance": "ci",
            "data": data,
        },
    }
