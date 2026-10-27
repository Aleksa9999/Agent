"""Profile rows. A save carries the version it was based on; a stale save is refused."""

from dataclasses import dataclass

from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import utcnow
from app.db.models import Profile
from app.profile.fields import Answer, Answers


@dataclass(frozen=True)
class ProfileData:
    answers: Answers
    state: dict
    version: int


class ProfileStore:
    def __init__(self, engine: Engine):
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def load(self, tenant_id: str, user_id: int) -> ProfileData:
        """The stored profile, or an empty one (created on the first save)."""
        with self._sessions() as s:
            row = s.scalar(
                select(Profile).where(Profile.tenant_id == tenant_id, Profile.user_id == user_id)
            )
        if row is None:
            return ProfileData({}, {}, 0)
        return ProfileData(
            {f: Answer.from_json(a) for f, a in row.answers.items()}, dict(row.state), row.version
        )

    def save(
        self, tenant_id: str, user_id: int, answers: Answers, state: dict, based_on: int
    ) -> bool:
        """False when somebody saved after `based_on`: the caller reloads and tries again."""
        payload = {f: a.to_json() for f, a in answers.items()}
        try:
            with self._sessions.begin() as s:
                if based_on == 0:
                    s.add(
                        Profile(
                            tenant_id=tenant_id,
                            user_id=user_id,
                            answers=payload,
                            state=state,
                            version=1,
                        )
                    )
                    return True
                result = s.execute(
                    update(Profile)
                    .where(
                        Profile.tenant_id == tenant_id,
                        Profile.user_id == user_id,
                        Profile.version == based_on,
                    )
                    .values(answers=payload, state=state, version=based_on + 1, updated_at=utcnow())
                )
                return result.rowcount == 1
        except IntegrityError:
            return False  # another request created the row first
