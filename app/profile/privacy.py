"""The gate between a person's profile and the shared group topic.

The patterns live in config/privacy_patterns.yaml (data, not code). A piece of text that matches
any of them is not published. Used twice: while the public card is composed, and once more on the
final message just before it is sent."""

import re
from functools import lru_cache
from pathlib import Path

import yaml

CATEGORIES = ("contact", "money", "age")


@lru_cache
def _compiled(path: str) -> dict[str, tuple[re.Pattern, ...]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {
        category: tuple(re.compile(p, re.IGNORECASE | re.UNICODE) for p in data.get(category, []))
        for category in CATEGORIES
    }


def violations(text: str, path: Path) -> list[str]:
    """Categories (contact, money, age) the text falls under; empty means it may be published."""
    compiled = _compiled(str(path))
    return [c for c in CATEGORIES if any(p.search(text) for p in compiled[c])]


def is_clean(text: str, path: Path) -> bool:
    return not violations(text, path)
