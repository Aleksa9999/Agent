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
        self.drafts_supported = True
        self.known_chats: set[int] | None = None  # None: every chat is reachable
        self.upload = b""  # what a download of any file returns
        self._thread = 100
        self._message = 0

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        yield self.upload

    def of(self, api_method: str) -> list[Any]:
        return [m for name, m in self.calls if name == api_method]

    async def make_request(self, bot, method, timeout=None):
        name = method.__api_method__
        self.calls.append((name, method))
        if name == "createForumTopic" and method.chat_id > 0 and not self.private_topics_supported:
            raise TelegramBadRequest(method=method, message="Bad Request: topics are not enabled")
        if name == "sendMessageDraft" and not self.drafts_supported:
            raise TelegramBadRequest(method=method, message="Bad Request: drafts are not available")
        scope_chat = getattr(getattr(method, "scope", None), "chat_id", None)
        if name == "setMyCommands" and scope_chat is not None and self.known_chats is not None:
            if scope_chat not in self.known_chats:
                raise TelegramBadRequest(method=method, message="Bad Request: chat not found")
        result: Any = True
        if name == "getMe":
            result = {"id": 999, "is_bot": True, "first_name": "Bot", "username": BOT_USERNAME}
        elif name == "getFile":
            result = {"file_id": method.file_id, "file_unique_id": "u", "file_path": "docs/f.zip"}
        elif name == "createForumTopic":
            self._thread += 1
            result = {"message_thread_id": self._thread, "name": method.name, "icon_color": 0}
        elif name in ("sendMessage", "sendDocument"):
            self._message += 1
            result = {
                "message_id": self._message,
                "date": 0,
                "chat": {
                    "id": method.chat_id,
                    "type": "private" if method.chat_id > 0 else "supergroup",
                },
                "text": getattr(method, "text", None) or getattr(method, "caption", None),
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


def callback_update(
    user: dict, data: str, update_id: int = 4, message_id: int | None = None
) -> dict:
    query = {"id": "cb1", "from": user, "chat_instance": "ci", "data": data}
    if message_id is not None:
        query["message"] = {
            "message_id": message_id,
            "date": 0,
            "chat": {"id": user["id"], "type": "private"},
            "text": "offer",
        }
    return {"update_id": update_id, "callback_query": query}


def text_update(user: dict, text: str, update_id: int = 5, thread_id: int | None = None) -> dict:
    message = {
        "message_id": 3,
        "date": 0,
        "chat": {"id": user["id"], "type": "private"},
        "from": user,
        "text": text,
    }
    if thread_id is not None:
        message["message_thread_id"] = thread_id
    return {"update_id": update_id, "message": message}


def document_update(user: dict, size: int, caption: str | None = None, update_id: int = 6) -> dict:
    message = {
        "message_id": 4,
        "date": 0,
        "chat": {"id": user["id"], "type": "private"},
        "from": user,
        "document": {
            "file_id": "doc1",
            "file_unique_id": "u1",
            "file_name": "skill.zip",
            "file_size": size,
        },
    }
    if caption:
        message["caption"] = caption
    return {"update_id": update_id, "message": message}


def voice_update(
    user: dict,
    size: int = 1000,
    mime: str | None = "audio/ogg",
    update_id: int = 7,
    thread_id: int | None = None,
) -> dict:
    voice = {"file_id": "voice1", "file_unique_id": "v1", "duration": 30, "file_size": size}
    if mime:
        voice["mime_type"] = mime
    message = {
        "message_id": 5,
        "date": 0,
        "chat": {"id": user["id"], "type": "private"},
        "from": user,
        "voice": voice,
    }
    if thread_id is not None:
        message["message_thread_id"] = thread_id
    return {"update_id": update_id, "message": message}
