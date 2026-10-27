"""Conversation storage: messages, summaries and pending questions."""

import asyncio
from dataclasses import dataclass

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import ChatMessage, PendingQuestion, SessionSummary


@dataclass(frozen=True)
class StoredMessage:
    id: int
    role: str
    content: str


@dataclass(frozen=True)
class StoredQuestion:
    id: str
    user_id: int
    context_key: str
    payload: dict
    status: str
    message_id: int | None


def _question(q: PendingQuestion) -> StoredQuestion:
    return StoredQuestion(q.id, q.user_id, q.context_key, q.payload, q.status, q.message_id)


class AgentStore:
    def __init__(self, engine: Engine):
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    # messages ------------------------------------------------------------
    def _add_message(self, tenant_id, user_id, context_key, role, content) -> int:
        with self._sessions.begin() as s:
            row = ChatMessage(
                tenant_id=tenant_id,
                user_id=user_id,
                context_key=context_key,
                role=role,
                content=content,
            )
            s.add(row)
            s.flush()
            return row.id

    async def add_message(self, tenant_id, user_id, context_key, role, content) -> int:
        return await asyncio.to_thread(
            self._add_message, tenant_id, user_id, context_key, role, content
        )

    def _history(self, tenant_id, user_id, context_key, after_id) -> list[StoredMessage]:
        with self._sessions() as s:
            rows = s.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.tenant_id == tenant_id,
                    ChatMessage.user_id == user_id,
                    ChatMessage.context_key == context_key,
                    ChatMessage.id > after_id,
                )
                .order_by(ChatMessage.id)
            ).all()
            return [StoredMessage(r.id, r.role, r.content) for r in rows]

    async def history(self, tenant_id, user_id, context_key, after_id=0) -> list[StoredMessage]:
        return await asyncio.to_thread(self._history, tenant_id, user_id, context_key, after_id)

    # summaries -----------------------------------------------------------
    def _get_summary(self, tenant_id, user_id, context_key):
        with self._sessions() as s:
            row = s.scalar(
                select(SessionSummary).where(
                    SessionSummary.tenant_id == tenant_id,
                    SessionSummary.user_id == user_id,
                    SessionSummary.context_key == context_key,
                )
            )
            return (row.summary, row.upto_message_id) if row else None

    async def get_summary(self, tenant_id, user_id, context_key) -> tuple[str, int] | None:
        return await asyncio.to_thread(self._get_summary, tenant_id, user_id, context_key)

    def _save_summary(self, tenant_id, user_id, context_key, summary, upto_id) -> None:
        with self._sessions.begin() as s:
            row = s.scalar(
                select(SessionSummary).where(
                    SessionSummary.tenant_id == tenant_id,
                    SessionSummary.user_id == user_id,
                    SessionSummary.context_key == context_key,
                )
            )
            if row is None:
                row = SessionSummary(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    context_key=context_key,
                    summary=summary,
                    upto_message_id=upto_id,
                )
                s.add(row)
            row.summary, row.upto_message_id = summary, upto_id

    async def save_summary(self, tenant_id, user_id, context_key, summary, upto_id) -> None:
        await asyncio.to_thread(
            self._save_summary, tenant_id, user_id, context_key, summary, upto_id
        )

    # questions -----------------------------------------------------------
    def _create_question(self, tenant_id, user_id, context_key, payload, qid) -> None:
        with self._sessions.begin() as s:
            s.add(
                PendingQuestion(
                    id=qid,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    context_key=context_key,
                    payload=payload,
                )
            )
        return qid

    async def create_question(self, tenant_id, user_id, context_key, payload, qid) -> None:
        await asyncio.to_thread(
            self._create_question, tenant_id, user_id, context_key, payload, qid
        )

    def _get_question(self, tenant_id, qid) -> StoredQuestion | None:
        with self._sessions() as s:
            row = s.scalar(
                select(PendingQuestion).where(
                    PendingQuestion.tenant_id == tenant_id, PendingQuestion.id == qid
                )
            )
            return _question(row) if row else None

    async def get_question(self, tenant_id, qid) -> StoredQuestion | None:
        return await asyncio.to_thread(self._get_question, tenant_id, qid)

    def _set_question(self, qid, status, message_id) -> None:
        with self._sessions.begin() as s:
            row = s.get(PendingQuestion, qid)
            row.status = status
            if message_id is not None:
                row.message_id = message_id

    async def set_question(self, qid, status, message_id=None) -> None:
        await asyncio.to_thread(self._set_question, qid, status, message_id)

    def _awaiting_custom(self, tenant_id, user_id) -> StoredQuestion | None:
        with self._sessions() as s:
            row = s.scalar(
                select(PendingQuestion)
                .where(
                    PendingQuestion.tenant_id == tenant_id,
                    PendingQuestion.user_id == user_id,
                    PendingQuestion.status == "awaiting_custom",
                )
                .order_by(PendingQuestion.created_at.desc())
            )
            return _question(row) if row else None

    async def awaiting_custom(self, tenant_id, user_id) -> StoredQuestion | None:
        return await asyncio.to_thread(self._awaiting_custom, tenant_id, user_id)
