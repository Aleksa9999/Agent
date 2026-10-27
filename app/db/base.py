"""Declarative base. Every table except `tenants` must carry a non-null tenant_id."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def utcnow() -> datetime:
    return datetime.now(UTC)


class TenantMixin:
    """Add to every business table: rows always belong to exactly one tenant."""

    @declared_attr
    def tenant_id(cls) -> Mapped[str]:  # noqa: N805
        return mapped_column(String(63), ForeignKey("tenants.id"), nullable=False, index=True)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(63), primary_key=True)
    brand_name: Mapped[str] = mapped_column(String(200), nullable=False)
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="ru")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def tables_without_tenant(metadata: MetaData = Base.metadata) -> list[str]:
    """Names of tables that break the tenant rule. CI keeps this list empty."""
    bad = []
    for table in metadata.sorted_tables:
        if table.name == "tenants":
            continue
        column = table.columns.get("tenant_id")
        if column is None or column.nullable:
            bad.append(table.name)
    return bad
