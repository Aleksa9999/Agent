"""Skill library in the database: repository skills are loaded at start, the owner adds new ones.

A skill is stored per version and never overwritten: a new version is a new row, an old row stays
for the people who still work on it. A skill reaches the catalog only as `published`."""

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import utcnow
from app.db.models import SkillVersion
from skillkit.parse import SkillDoc, check_bundle, parse_skill, version_number

log = logging.getLogger("app.skills")

PENDING, PUBLISHED, DISCARDED = "pending", "published", "discarded"
CONFLICT_OTHER_BRANCH = "other_branch"
CONFLICT_VERSION_EXISTS = "version_exists"
CONFLICT_STALE = "stale"
CONFLICT_NOT_FOUND = "not_found"


@dataclass(frozen=True)
class UploadResult:
    errors: list[str] = field(default_factory=list)  # validator findings, owner-facing
    conflict: str | None = None  # a version rule that failed (see CONFLICT_*)
    doc: SkillDoc | None = None
    pending_id: int | None = None  # set only when the skill passed and waits for "Publish"
    latest: str | None = None  # newest published version, for the conflict message


@dataclass(frozen=True)
class PublishResult:
    ok: bool
    conflict: str | None = None
    doc: SkillDoc | None = None


def _hash(skill_md: str, test_yaml: str) -> str:
    return hashlib.sha256(f"{skill_md}\0{test_yaml}".encode()).hexdigest()


class SkillStore:
    def __init__(self, engine: Engine):
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    # repository ----------------------------------------------------------
    def sync_repo(self, skills_dir: Path, tenant_ids: list[str]) -> int:
        """Loads content/skills into every tenant. Repeatable; returns the skills read."""
        found = []
        for skill_md in sorted(Path(skills_dir).glob("*/*/SKILL.md")):
            test_file = skill_md.parent / "test.yaml"
            try:
                text = skill_md.read_text(encoding="utf-8")
                tests = test_file.read_text(encoding="utf-8")
                found.append((parse_skill(text), text, tests))
            except (OSError, ValueError) as exc:
                log.warning("skill %s was not loaded: %s", skill_md.parent.name, type(exc).__name__)
        with self._sessions.begin() as s:
            for tenant_id in tenant_ids:
                for doc, text, tests in found:
                    row = s.scalar(
                        select(SkillVersion).where(
                            SkillVersion.tenant_id == tenant_id,
                            SkillVersion.slug == doc.slug,
                            SkillVersion.version == doc.version,
                        )
                    )
                    digest = _hash(text, tests)
                    if row is None:
                        s.add(
                            SkillVersion(
                                tenant_id=tenant_id,
                                slug=doc.slug,
                                version=doc.version,
                                branch=doc.branch,
                                status=PUBLISHED,
                                origin="repo",
                                skill_md=text,
                                test_yaml=tests,
                                content_hash=digest,
                                published_at=utcnow(),
                            )
                        )
                    elif row.origin == "repo" and row.content_hash != digest:
                        row.skill_md, row.test_yaml, row.content_hash = text, tests, digest
                        row.branch = doc.branch
        return len(found)

    # catalog -------------------------------------------------------------
    def catalog(self, tenant_id: str) -> list[SkillDoc]:
        """The newest published version of every skill."""
        with self._sessions() as s:
            rows = s.scalars(
                select(SkillVersion).where(
                    SkillVersion.tenant_id == tenant_id, SkillVersion.status == PUBLISHED
                )
            ).all()
        newest: dict[str, SkillVersion] = {}
        for row in rows:
            best = newest.get(row.slug)
            if best is None or version_number(row.version) > version_number(best.version):
                newest[row.slug] = row
        return [parse_skill(row.skill_md) for row in newest.values()]

    def get(self, tenant_id: str, slug: str, version: str | None = None) -> SkillDoc | None:
        """A published skill: the given version, or the newest one."""
        with self._sessions() as s:
            rows = s.scalars(
                select(SkillVersion).where(
                    SkillVersion.tenant_id == tenant_id,
                    SkillVersion.slug == slug,
                    SkillVersion.status == PUBLISHED,
                )
            ).all()
        if version is not None:
            rows = [r for r in rows if r.version == version]
        if not rows:
            return None
        return parse_skill(max(rows, key=lambda r: version_number(r.version)).skill_md)

    def text(self, tenant_id: str, slug: str, version: str) -> str | None:
        """The SKILL.md of a published version."""
        with self._sessions() as s:
            return s.scalar(
                select(SkillVersion.skill_md).where(
                    SkillVersion.tenant_id == tenant_id,
                    SkillVersion.slug == slug,
                    SkillVersion.version == version,
                    SkillVersion.status == PUBLISHED,
                )
            )

    def versions(self, tenant_id: str, slug: str) -> list[str]:
        with self._sessions() as s:
            rows = s.scalars(
                select(SkillVersion.version).where(
                    SkillVersion.tenant_id == tenant_id,
                    SkillVersion.slug == slug,
                    SkillVersion.status == PUBLISHED,
                )
            ).all()
        return sorted(rows, key=version_number)

    # owner upload --------------------------------------------------------
    def add_pending(
        self, tenant_id: str, skill_md: str, test_yaml: str, uploaded_by: int
    ) -> UploadResult:
        """Runs the repository validator. A skill with errors is not stored at all."""
        errors, doc = check_bundle(skill_md, test_yaml)
        if errors or doc is None:
            return UploadResult(errors=errors or ["unreadable"], doc=doc)
        with self._sessions.begin() as s:
            same_slug = s.scalars(
                select(SkillVersion).where(
                    SkillVersion.tenant_id == tenant_id, SkillVersion.slug == doc.slug
                )
            ).all()
            published = [r for r in same_slug if r.status == PUBLISHED]
            if any(r.branch != doc.branch for r in published):
                return UploadResult(conflict=CONFLICT_OTHER_BRANCH, doc=doc)
            if any(version_number(r.version) >= version_number(doc.version) for r in published):
                latest = max(published, key=lambda r: version_number(r.version)).version
                return UploadResult(conflict=CONFLICT_VERSION_EXISTS, doc=doc, latest=latest)
            row = next((r for r in same_slug if r.version == doc.version), None)
            if row is None:  # a re-upload of a pending or discarded version replaces that row
                row = SkillVersion(
                    tenant_id=tenant_id, slug=doc.slug, version=doc.version, origin="upload"
                )
                s.add(row)
            row.branch, row.status = doc.branch, PENDING
            row.skill_md, row.test_yaml = skill_md, test_yaml
            row.content_hash = _hash(skill_md, test_yaml)
            row.uploaded_by = uploaded_by
            s.flush()
            return UploadResult(doc=doc, pending_id=row.id)

    def publish(self, tenant_id: str, pending_id: int) -> PublishResult:
        with self._sessions.begin() as s:
            row = s.get(SkillVersion, pending_id)
            if row is None or row.tenant_id != tenant_id or row.status != PENDING:
                return PublishResult(False, CONFLICT_NOT_FOUND)
            doc = parse_skill(row.skill_md)
            published = s.scalars(
                select(SkillVersion).where(
                    SkillVersion.tenant_id == tenant_id,
                    SkillVersion.slug == row.slug,
                    SkillVersion.status == PUBLISHED,
                )
            ).all()
            if any(version_number(r.version) >= version_number(row.version) for r in published):
                return PublishResult(False, CONFLICT_STALE, doc)  # published meanwhile
            row.status, row.published_at = PUBLISHED, utcnow()
            return PublishResult(True, doc=doc)

    def discard(self, tenant_id: str, pending_id: int) -> bool:
        with self._sessions.begin() as s:
            row = s.get(SkillVersion, pending_id)
            if row is None or row.tenant_id != tenant_id or row.status != PENDING:
                return False
            row.status = DISCARDED
            return True
