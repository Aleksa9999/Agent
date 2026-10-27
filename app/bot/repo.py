"""Database access for the bot. Plain dataclasses go in and out, sessions stay inside."""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import Topic, User


@dataclass(frozen=True)
class UserRow:
    id: int
    tenant_id: str
    tg_id: int
    role: str
    first_name: str
    last_name: str | None
    username: str | None
    status: str
    dm_chat_id: int | None
    dm_topics_supported: bool | None
    active_context: str | None


@dataclass(frozen=True)
class TopicRow:
    user_id: int
    kind: str
    chat_id: int
    thread_id: int


def _user(u: User) -> UserRow:
    return UserRow(
        u.id,
        u.tenant_id,
        u.tg_id,
        u.role,
        u.first_name,
        u.last_name,
        u.username,
        u.status,
        u.dm_chat_id,
        u.dm_topics_supported,
        u.active_context,
    )


class KeyedLock:
    """Serialises work per key inside one process (a user's join and /start must not race)."""

    def __init__(self) -> None:
        self._locks: dict[Any, asyncio.Lock] = defaultdict(asyncio.Lock)

    def __call__(self, key: Any) -> asyncio.Lock:
        return self._locks[key]


class BotRepo:
    def __init__(self, engine: Engine):
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    async def _run(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    # users ---------------------------------------------------------------
    def _upsert_user(self, tenant_id, tg_id, role, first_name, last_name, username, lang):
        with self._sessions.begin() as s:
            user = s.scalar(select(User).where(User.tenant_id == tenant_id, User.tg_id == tg_id))
            if user is None:
                user = User(tenant_id=tenant_id, tg_id=tg_id)
                s.add(user)
            user.role = role  # always recomputed from the registry
            user.first_name = first_name
            user.last_name = last_name
            user.username = username
            user.language_code = lang
            user.status = "active"
            s.flush()
            return _user(user)

    async def upsert_user(self, tenant_id, tg_id, *, role, first_name, last_name, username, lang):
        return await self._run(
            self._upsert_user, tenant_id, tg_id, role, first_name, last_name, username, lang
        )

    def _get_user(self, tenant_id, tg_id):
        with self._sessions() as s:
            user = s.scalar(select(User).where(User.tenant_id == tenant_id, User.tg_id == tg_id))
            return _user(user) if user else None

    async def get_user(self, tenant_id: str, tg_id: int) -> UserRow | None:
        return await self._run(self._get_user, tenant_id, tg_id)

    def _update_user(self, user_id, **fields):
        with self._sessions.begin() as s:
            user = s.get(User, user_id)
            for key, value in fields.items():
                setattr(user, key, value)

    async def update_user(self, user_id: int, **fields) -> None:
        await self._run(self._update_user, user_id, **fields)

    def _members(self, tenant_id, limit):
        with self._sessions() as s:
            total = s.scalar(
                select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
            )
            rows = s.scalars(
                select(User)
                .where(User.tenant_id == tenant_id)
                .order_by(User.id.desc())
                .limit(limit)
            ).all()
            return total, [_user(u) for u in rows]

    async def members(self, tenant_id: str, limit: int = 20) -> tuple[int, list[UserRow]]:
        return await self._run(self._members, tenant_id, limit)

    # topics --------------------------------------------------------------
    def _get_topic(self, tenant_id, user_id, kind):
        with self._sessions() as s:
            t = s.scalar(
                select(Topic).where(
                    Topic.tenant_id == tenant_id, Topic.user_id == user_id, Topic.kind == kind
                )
            )
            return TopicRow(t.user_id, t.kind, t.chat_id, t.thread_id) if t else None

    async def get_topic(self, tenant_id: str, user_id: int, kind: str) -> TopicRow | None:
        return await self._run(self._get_topic, tenant_id, user_id, kind)

    def _kind_by_thread(self, tenant_id, user_id, thread_id):
        with self._sessions() as s:
            return s.scalar(
                select(Topic.kind).where(
                    Topic.tenant_id == tenant_id,
                    Topic.user_id == user_id,
                    Topic.thread_id == thread_id,
                )
            )

    async def kind_by_thread(self, tenant_id: str, user_id: int, thread_id: int) -> str | None:
        return await self._run(self._kind_by_thread, tenant_id, user_id, thread_id)

    def _add_topic(self, tenant_id, user_id, kind, chat_id, thread_id) -> bool:
        try:
            with self._sessions.begin() as s:
                s.add(
                    Topic(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        kind=kind,
                        chat_id=chat_id,
                        thread_id=thread_id,
                    )
                )
            return True
        except IntegrityError:
            return False  # another request stored it first

    async def add_topic(self, tenant_id, user_id, kind, chat_id, thread_id) -> bool:
        return await self._run(self._add_topic, tenant_id, user_id, kind, chat_id, thread_id)
