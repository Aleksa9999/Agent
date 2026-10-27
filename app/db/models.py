"""Business tables. Every table carries tenant_id (see TenantMixin)."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, UniqueConstraint
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
