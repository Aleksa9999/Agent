"""Standard A: a question with exactly four meaningfully different options, one recommended.

The model proposes the question through the `ask_options` tool; this module validates it so that
a lazy or malformed question is sent back to the model instead of reaching the person.
"""

import secrets
from dataclasses import dataclass

CONTROLS = ("custom", "unknown", "back", "compare")
OPTION_COUNT = 4


class InvalidQuestionError(ValueError):
    """The text is safe to show to the model so that it can fix its question."""


@dataclass(frozen=True)
class Option:
    title: str
    description: str
    cost: str
    pros: tuple[str, ...]
    cons: tuple[str, ...]
    recommended: bool


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    options: tuple[Option, ...]

    @property
    def recommended_index(self) -> int:
        return next(i for i, o in enumerate(self.options) if o.recommended)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidQuestionError(f"{field} must be a non-empty string")
    return value.strip()


def _lines(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise InvalidQuestionError(f"{field} must be a non-empty list of strings")
    return tuple(v.strip() for v in value)


def parse_question(arguments: dict, *, question_id: str | None = None) -> Question:
    text = _text(arguments.get("question"), "question")
    raw = arguments.get("options")
    if not isinstance(raw, list) or len(raw) != OPTION_COUNT:
        raise InvalidQuestionError(f"exactly {OPTION_COUNT} options are required, no filler")
    options = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise InvalidQuestionError(f"option {i} must be an object")
        options.append(
            Option(
                title=_text(item.get("title"), f"option {i} title"),
                description=_text(item.get("description"), f"option {i} description"),
                cost=_text(item.get("cost"), f"option {i} cost (price and time)"),
                pros=_lines(item.get("pros"), f"option {i} pros"),
                cons=_lines(item.get("cons"), f"option {i} cons"),
                recommended=item.get("recommended") is True,
            )
        )
    if sum(o.recommended for o in options) != 1:
        raise InvalidQuestionError("exactly one option must be marked recommended")
    if len({o.title.casefold() for o in options}) != OPTION_COUNT:
        raise InvalidQuestionError("option titles must differ")
    return Question(id=question_id or secrets.token_urlsafe(6), text=text, options=tuple(options))


QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "The question for the person."},
        "options": {
            "type": "array",
            "minItems": OPTION_COUNT,
            "maxItems": OPTION_COUNT,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "cost": {
                        "type": "string",
                        "description": "Price and time, e.g. '500 RUB, 2 h'.",
                    },
                    "pros": {"type": "array", "items": {"type": "string"}},
                    "cons": {"type": "array", "items": {"type": "string"}},
                    "recommended": {"type": "boolean"},
                },
                "required": ["title", "description", "cost", "pros", "cons", "recommended"],
            },
        },
    },
    "required": ["question", "options"],
}
