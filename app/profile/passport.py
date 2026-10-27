"""Passport rows. A new version is written only when the confirmed profile really changed."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import Passport
from app.profile.fields import Answers


@dataclass(frozen=True)
class PassportRow:
    version: int
    data: dict
    content_hash: str
    group_message_id: int | None
    created_at: datetime


class Publisher(Protocol):
    """Posts the public card into the person's group topic; returns the message id or None."""

    async def publish(
        self,
        tenant: str,
        user_id: int,
        name: str,
        lines: list[tuple[str, str]],
        previous: int | None,
    ) -> int | None: ...


def fingerprint(answers: Answers) -> str:
    payload = {f: a.to_json() for f, a in sorted(answers.items())}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _row(p: Passport) -> PassportRow:
    return PassportRow(p.version, p.data, p.content_hash, p.group_message_id, p.created_at)


class PassportStore:
    def __init__(self, engine: Engine):
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def latest(self, tenant_id: str, user_id: int) -> PassportRow | None:
        with self._sessions() as s:
            row = s.scalar(
                select(Passport)
                .where(Passport.tenant_id == tenant_id, Passport.user_id == user_id)
                .order_by(Passport.version.desc())
                .limit(1)
            )
        return _row(row) if row else None

    def versions(self, tenant_id: str, user_id: int) -> list[PassportRow]:
        with self._sessions() as s:
            rows = s.scalars(
                select(Passport)
                .where(Passport.tenant_id == tenant_id, Passport.user_id == user_id)
                .order_by(Passport.version)
            ).all()
        return [_row(r) for r in rows]

    def last_message_id(self, tenant_id: str, user_id: int) -> int | None:
        for row in reversed(self.versions(tenant_id, user_id)):
            if row.group_message_id is not None:
                return row.group_message_id
        return None

    def create(self, tenant_id: str, user_id: int, data: dict, content_hash: str) -> PassportRow:
        """The next version. Two simultaneous confirmations cannot both take the same number."""
        for _ in range(3):
            latest = self.latest(tenant_id, user_id)
            if latest is not None and latest.content_hash == content_hash:
                return latest
            version = (latest.version if latest else 0) + 1
            try:
                with self._sessions.begin() as s:
                    s.add(
                        Passport(
                            tenant_id=tenant_id,
                            user_id=user_id,
                            version=version,
                            data=data,
                            content_hash=content_hash,
                        )
                    )
            except IntegrityError:
                continue
            created = self.latest(tenant_id, user_id)
            assert created is not None
            return created
        raise RuntimeError("passport version was taken too often at once")

    def set_message(self, tenant_id: str, user_id: int, version: int, message_id: int) -> None:
        with self._sessions.begin() as s:
            s.execute(
                update(Passport)
                .where(
                    Passport.tenant_id == tenant_id,
                    Passport.user_id == user_id,
                    Passport.version == version,
                )
                .values(group_message_id=message_id)
            )
