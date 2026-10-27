"""Reads one skill into a plain structure: what the catalog shows (road, estimate, unlock rule)."""

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from skillkit.validator import BRANCHES, check_skill

TIER_NAMES = {"Эконом": "economy", "Стандарт": "standard", "Премиум": "premium"}
ROADS = ("agent", "self")  # both roads exist for every skill; the same test.yaml checks both
SLUG = re.compile(r"[a-z0-9-]{1,64}")
VERSION = re.compile(r"v(\d+)")
FRONTMATTER = re.compile(r"---\n(.*?)\n---\n(.*)", re.S)
TEST_FILE = "test.yaml"


@dataclass(frozen=True)
class Tier:
    id: str
    includes: str
    roles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillDoc:
    slug: str
    title: str
    branch: str
    version: str
    kind: str
    runs_via: str
    min_level: int
    source: str
    triggers: list[str]
    roads: list[str]
    tiers: list[Tier]
    proof: str


def version_number(version: str) -> int:
    match = VERSION.fullmatch(version)
    return int(match.group(1)) if match else 0


def _section(body: str, name: str) -> str:
    match = re.search(rf"^## {re.escape(name)}\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return match.group(1).strip() if match else ""


def _tiers(body: str) -> list[Tier]:
    """Tables come in two shapes: level | roles, and level | what is included | roles.
    A row that starts with "+" (or names no roles) adds to the tier before it."""
    tiers: list[Tier] = []
    for line in _section(body, "Коробка ИИ").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] not in TIER_NAMES:
            continue
        roles = list(dict.fromkeys(re.findall(r"`([a-z_]+)`", cells[-1])))
        if tiers and (cells[-1].startswith("+") or not roles):
            roles = list(dict.fromkeys([*tiers[-1].roles, *roles]))
        includes = cells[1] if len(cells) >= 3 else ""
        tiers.append(Tier(TIER_NAMES[cells[0]], includes, roles))
    return tiers


def parse_skill(text: str) -> SkillDoc:
    """Raises ValueError when the text has no readable frontmatter."""
    match = FRONTMATTER.match(text)
    if not match:
        raise ValueError("no_frontmatter")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError("bad_frontmatter") from exc
    if not isinstance(meta, dict):
        raise ValueError("bad_frontmatter")
    try:
        return SkillDoc(
            slug=str(meta["name"]),
            title=str(meta["title"]),
            branch=str(meta["branch"]),
            version=str(meta["version"]),
            kind=str(meta["kind"]),
            runs_via=str(meta["runs_via"]),
            min_level=int(meta["min_level"]),
            source=str(meta["source"]),
            triggers=[str(t) for t in meta.get("triggers") or []],
            roads=list(ROADS),
            tiers=_tiers(match.group(2)),
            proof=_section(match.group(2), "Доказательство «Сработало»"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("bad_frontmatter") from exc


def check_bundle(skill_md: str, test_yaml: str) -> tuple[list[str], SkillDoc | None]:
    """The repository validator run on uploaded text. Returns (errors, parsed skill).

    The slug and the branch become directory names, so they are checked before they are used."""
    try:
        doc = parse_skill(skill_md)
    except ValueError as exc:
        return [str(exc)], None
    if not SLUG.fullmatch(doc.slug):
        return [f"{doc.slug[:40]}: name must be a-z0-9-"], None
    if doc.branch not in BRANCHES:
        return [f"{doc.slug}: unknown branch {doc.branch[:40]}"], None
    declared = yaml.safe_load(FRONTMATTER.match(skill_md).group(1)).get("autotest")  # type: ignore[union-attr]
    if declared != TEST_FILE:
        return [f"{doc.slug}: autotest must be {TEST_FILE}"], doc
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / doc.branch / doc.slug
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(skill_md, encoding="utf-8")
        (folder / TEST_FILE).write_text(test_yaml, encoding="utf-8")
        return check_skill(folder / "SKILL.md"), doc
