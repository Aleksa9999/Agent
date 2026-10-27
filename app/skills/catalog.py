"""The catalog the Mini App shows: 8 studio directions as cards and the 10 branches of the tree."""

from dataclasses import asdict

from skillkit.parse import SkillDoc

BRANCH_ORDER = (
    "strategy",
    "research",
    "sales",
    "product",
    "code",
    "design",
    "content",
    "video-voice",
    "automation",
    "personal",
)
# The 8 directions of _docs/placement-test.md, in the order people see them.
DIRECTIONS = (
    "site-with-ai",
    "app-with-ai",
    "automation-build",
    "virtual-employees",
    "ai-agency",
    "sell-ai-courses",
    "tutor-oge-ege",
    "ai-consulting",
)


def skill_view(doc: SkillDoc) -> dict:
    """One skill as the catalog shows it: road, estimate by tier, and what unlocks it."""
    return {
        "slug": doc.slug,
        "title": doc.title,
        "branch": doc.branch,
        "version": doc.version,
        "kind": doc.kind,
        "roads": doc.roads,
        "estimate": {
            "price_source": "model_catalog",  # prices come from the model catalog, never from text
            "tiers": [asdict(tier) for tier in doc.tiers],
        },
        "unlock": {"min_level": doc.min_level, "proof": doc.proof},
    }


def catalog_view(docs: list[SkillDoc]) -> dict:
    ordered = sorted(docs, key=lambda d: (BRANCH_ORDER.index(d.branch), d.title))
    return {
        "total": len(ordered),
        "directions": [skill_view(d) for slug in DIRECTIONS for d in ordered if d.slug == slug],
        "branches": [
            {"id": branch, "skills": [skill_view(d) for d in ordered if d.branch == branch]}
            for branch in BRANCH_ORDER
        ],
    }
