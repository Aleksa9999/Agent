"""The profile card (7-8 lines) and its public part.

A line combines related fields. Lines marked private (time and budget, country) are never part of
the public card. Free-text parts that look like contacts, money or age are left out of the public
card even on a public line (see privacy.py)."""

from dataclasses import dataclass
from pathlib import Path

from app.i18n import Translator
from app.profile.fields import FIELDS, Answers, plan
from app.profile.privacy import is_clean

# (line id, its fields, may it be shown in the group)
LINES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("role", ("role",), True),
    ("goal_10w", ("goal_10w",), True),
    ("goal_year", ("goal_year",), True),
    ("project", ("idea", "business", "audience"), True),
    ("resources", ("time_week", "budget"), False),
    ("experience", ("experience",), True),
    ("ai", ("ai_level", "tech_depth"), True),
    ("country", ("country",), False),
)
LINE_IDS = tuple(line_id for line_id, _, _ in LINES)
JOINER = "; "


@dataclass(frozen=True)
class CardLine:
    id: str
    label: str
    text: str
    public: bool


def line_fields(line_id: str, answers: Answers) -> list[str]:
    """The answered fields of a line, in the order they are asked."""
    for current, fields, _ in LINES:
        if current == line_id:
            asked = [f for f in plan(answers) if f in fields and f in answers]
            return asked + [f for f in fields if f in answers and f not in asked]
    return []


def _parts(answers: Answers, fields: tuple[str, ...]) -> list[str]:
    return [
        answers[f].text
        for f in FIELDS
        if f in fields and f in answers and answers[f].kind != "unknown" and answers[f].text
    ]


def card_lines(tr: Translator, tenant: str, answers: Answers) -> list[CardLine]:
    lines = []
    for line_id, fields, public in LINES:
        if not any(f in answers for f in fields):
            continue  # a role that was never asked about this line (a student has no business)
        text = JOINER.join(_parts(answers, fields)) or tr.t(tenant, "pf_unknown_text")
        lines.append(CardLine(line_id, tr.t(tenant, f"card_{line_id}"), text, public))
    return lines


def public_lines(
    tr: Translator, tenant: str, answers: Answers, patterns: Path
) -> list[tuple[str, str]]:
    """(label, text) pairs for the group topic: public lines, clean parts only."""
    shown = []
    for line_id, fields, public in LINES:
        if not public:
            continue
        clean = [p for p in _parts(answers, fields) if is_clean(p, patterns)]
        if clean:
            shown.append((tr.t(tenant, f"card_{line_id}"), JOINER.join(clean)))
    return shown
