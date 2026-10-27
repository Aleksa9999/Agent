"""Business tables. Every table carries tenant_id (see TenantMixin)."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, utcnow


class User(TenantMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "tg_id", name="uq_users_tenant_tg"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    first_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    last_name: Mapped[str | None] = mapped_column(String(256))
    username: Mapped[str | None] = mapped_column(String(64))
    language_code: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    dm_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    dm_topics_supported: Mapped[bool | None] = mapped_column(Boolean)
    active_context: Mapped[str | None] = mapped_column(String(24))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Topic(TenantMixin, Base):
    """A Telegram topic that belongs to one user: the public group topic or a private-chat topic."""

    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "kind", name="uq_topics_user_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    thread_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatMessage(TenantMixin, Base):
    """One message of the conversation between a person and their agent, per context."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_user_context", "user_id", "context_key", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    context_key: Mapped[str] = mapped_column(String(24), nullable=False)
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SessionSummary(TenantMixin, Base):
    """Older messages of a context folded into text; messages up to upto_message_id are inside."""

    __tablename__ = "session_summaries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "context_key", name="uq_summaries_context"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    context_key: Mapped[str] = mapped_column(String(24), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    upto_message_id: Mapped[int] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PendingQuestion(TenantMixin, Base):
    """A Standard A question shown to a person; its buttons refer to this row."""

    __tablename__ = "pending_questions"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    context_key: Mapped[str] = mapped_column(String(24), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
