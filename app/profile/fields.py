"""The profile the agent needs from a new person and the order in which it asks.

Twelve fields. The order depends on the role: a business owner is asked about the business, a
student is not. The same plan serves the voice follow-up (only gaps) and the questionnaire
(everything, in blocks of five), so both fill one profile and one can finish what the other began.
"""

from dataclasses import dataclass

BATCH_SIZE = 5
OPTION_COUNT = 4
CUSTOM_LIMIT = 300

FIELDS = (
    "role",
    "goal_10w",
    "goal_year",
    "idea",
    "business",
    "audience",
    "time_week",
    "budget",
    "experience",
    "ai_level",
    "tech_depth",
    "country",
)

# Fields whose four options have a meaning of their own; other fields use o1..o4.
ENUM_CODES = {
    "role": ("business", "employee", "student", "searching"),
    "ai_level": ("0", "1", "2", "3"),
    "tech_depth": ("0", "1", "2", "3"),
}
PLAIN_CODES = ("o1", "o2", "o3", "o4")

# Asked before the role is known: the role first, then what matters for every person.
GENERIC_ORDER = (
    "role",
    "goal_10w",
    "time_week",
    "budget",
    "ai_level",
    "goal_year",
    "experience",
    "tech_depth",
    "country",
    "idea",
)
OTHER_ORDER = (
    "goal_10w",
    "time_week",
    "budget",
    "ai_level",
    "goal_year",
    "experience",
    "tech_depth",
    "idea",
    "country",
)
ROLE_ORDER = {
    "business": (
        "goal_10w",
        "business",
        "audience",
        "time_week",
        "budget",
        "goal_year",
        "idea",
        "ai_level",
        "tech_depth",
        "country",
        "experience",
    ),
    "employee": (
        "goal_10w",
        "idea",
        "time_week",
        "experience",
        "ai_level",
        "goal_year",
        "budget",
        "tech_depth",
        "country",
    ),
    "student": (
        "goal_10w",
        "experience",
        "time_week",
        "ai_level",
        "tech_depth",
        "idea",
        "goal_year",
        "budget",
        "country",
    ),
    "searching": (
        "goal_10w",
        "experience",
        "time_week",
        "ai_level",
        "budget",
        "goal_year",
        "tech_depth",
        "country",
    ),
}

# Index of the starred option when nothing else is known, and per role.
DEFAULT_STAR = {
    "role": 0,
    "goal_10w": 2,
    "goal_year": 2,
    "idea": 1,
    "business": 0,
    "audience": 2,
    "time_week": 1,
    "budget": 1,
    "experience": 0,
    "ai_level": 1,
    "tech_depth": 1,
    "country": 0,
}
ROLE_STAR = {
    "goal_10w": {"business": 0, "employee": 2, "student": 2, "searching": 3},
    "goal_year": {"business": 0, "employee": 1, "student": 2, "searching": 3},
    "idea": {"business": 1, "employee": 2, "student": 3, "searching": 3},
    "experience": {"student": 3, "employee": 1, "searching": 0},
}


@dataclass(frozen=True)
class Answer:
    """kind: option (a button), custom (own words), unknown, voice (taken from the story)."""

    kind: str
    text: str = ""
    code: str | None = None

    def to_json(self) -> dict:
        data: dict = {"kind": self.kind, "text": self.text}
        if self.code is not None:
            data["code"] = self.code
        return data

    @classmethod
    def from_json(cls, data: dict) -> "Answer":
        return cls(kind=data["kind"], text=data.get("text", ""), code=data.get("code"))


Answers = dict[str, Answer]


def codes(field: str) -> tuple[str, ...]:
    return ENUM_CODES.get(field, PLAIN_CODES)


def role_code(answers: Answers) -> str | None:
    answer = answers.get("role")
    if answer is not None and answer.code in ENUM_CODES["role"]:
        return answer.code
    return None


def plan(answers: Answers) -> tuple[str, ...]:
    """Every field that matters for this person, in the order of asking."""
    if "role" not in answers:
        return GENERIC_ORDER
    return ROLE_ORDER.get(role_code(answers) or "", OTHER_ORDER)


def missing(answers: Answers) -> list[str]:
    ordered = plan(answers)
    return [f for f in ordered if f not in answers]


def next_batch(answers: Answers) -> list[str]:
    return missing(answers)[:BATCH_SIZE]


def relevant_total(answers: Answers) -> int:
    """Answered plus still missing: the length of this person's questionnaire."""
    ordered = plan(answers)
    return len(set(ordered) | set(answers))


def star_index(field: str, answers: Answers) -> int:
    by_role = ROLE_STAR.get(field, {})
    role = role_code(answers)
    if role in by_role:
        return by_role[role]
    if field == "tech_depth":
        level = answers.get("ai_level")
        if level is not None and level.code in ("2", "3"):
            return 2
    return DEFAULT_STAR[field]
