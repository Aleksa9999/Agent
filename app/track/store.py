"""Rows of a person's skill tree and first results."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from app.db.base import utcnow
from app.db.models import FirstResult, UserSkill

UNVERIFIED, VERIFIED = "unverified", "verified"
TRACK_SOURCE = "track"


@dataclass(frozen=True)
class SkillRow:
    slug: str
    version: str
    status: str
    source: str


@dataclass(frozen=True)
class ResultRow:
    passport_version: int
    track: str
    kind: str
    content: str
    code: str | None
    seconds: float
    created_at: datetime


class UserSkillStore:
    def __init__(self, engine: Engine):
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def assign(self, tenant_id: str, user_id: int, items: list[tuple[str, str]]) -> None:
        """Suggest skills (slug, version) to a person. Suggestions of an older track that were
        never worked on are replaced; a verified skill is never touched."""
        wanted = {slug for slug, _ in items}
        with self._sessions.begin() as s:
            s.execute(
                delete(UserSkill).where(
                    UserSkill.tenant_id == tenant_id,
                    UserSkill.user_id == user_id,
                    UserSkill.status == UNVERIFIED,
                    UserSkill.source == TRACK_SOURCE,
                    UserSkill.slug.not_in(wanted) if wanted else True,
                )
            )
            have = set(
                s.scalars(
                    select(UserSkill.slug).where(
                        UserSkill.tenant_id == tenant_id, UserSkill.user_id == user_id
                    )
                )
            )
            for slug, version in items:
                if slug not in have:
                    s.add(
                        UserSkill(
                            tenant_id=tenant_id,
                            user_id=user_id,
                            slug=slug,
                            version=version,
                            status=UNVERIFIED,
                            source=TRACK_SOURCE,
                        )
                    )

    def rows(self, tenant_id: str, user_id: int) -> list[SkillRow]:
        with self._sessions() as s:
            found = s.scalars(
                select(UserSkill)
                .where(UserSkill.tenant_id == tenant_id, UserSkill.user_id == user_id)
                .order_by(UserSkill.id)
            ).all()
        return [SkillRow(r.slug, r.version, r.status, r.source) for r in found]

    def counter(self, tenant_id: str, user_id: int) -> int:
        """Skills that count: only the verified ones."""
        with self._sessions() as s:
            return (
                s.scalar(
                    select(func.count())
                    .select_from(UserSkill)
                    .where(
                        UserSkill.tenant_id == tenant_id,
                        UserSkill.user_id == user_id,
                        UserSkill.status == VERIFIED,
                    )
                )
                or 0
            )


class FirstResultStore:
    def __init__(self, engine: Engine):
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def get(self, tenant_id: str, user_id: int, passport_version: int) -> ResultRow | None:
        with self._sessions() as s:
            row = s.scalar(
                select(FirstResult).where(
                    FirstResult.tenant_id == tenant_id,
                    FirstResult.user_id == user_id,
                    FirstResult.passport_version == passport_version,
                )
            )
        if row is None:
            return None
        return ResultRow(
            row.passport_version,
            row.track,
            row.kind,
            row.content,
            row.code,
            row.seconds,
            row.created_at,
        )

    def save(
        self,
        tenant_id: str,
        user_id: int,
        passport_version: int,
        track: str,
        kind: str,
        content: str,
        code: str | None,
        seconds: float,
    ) -> None:
        with self._sessions.begin() as s:
            row = s.scalar(
                select(FirstResult).where(
                    FirstResult.tenant_id == tenant_id,
                    FirstResult.user_id == user_id,
                    FirstResult.passport_version == passport_version,
                )
            )
            if row is None:
                row = FirstResult(
                    tenant_id=tenant_id, user_id=user_id, passport_version=passport_version
                )
                s.add(row)
            row.track, row.kind, row.content, row.code = track, kind, content, code
            row.seconds, row.created_at = seconds, utcnow()
