"""Standard A in Telegram: four options, a star on the recommended one, and four controls."""

import json
from dataclasses import asdict

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.agent.options import Option, Question

PREFIX = "v1:q"
BUTTON_TITLE_LIMIT = 40
ACTIONS = ("o0", "o1", "o2", "o3", "custom", "unknown", "back", "compare")


def callback(question_id: str, action: str) -> str:
    return f"{PREFIX}:{question_id}:{action}"


def parse_callback(data: str | None) -> tuple[str, str] | None:
    parts = (data or "").split(":")
    if len(parts) == 4 and f"{parts[0]}:{parts[1]}" == PREFIX and parts[3] in ACTIONS:
        return parts[2], parts[3]
    return None


def to_payload(question: Question) -> dict:
    return json.loads(json.dumps(asdict(question), ensure_ascii=False))


def from_payload(payload: dict) -> Question:
    options = tuple(
        Option(
            title=o["title"],
            description=o["description"],
            cost=o["cost"],
            pros=tuple(o["pros"]),
            cons=tuple(o["cons"]),
            recommended=o["recommended"],
        )
        for o in payload["options"]
    )
    return Question(id=payload["id"], text=payload["text"], options=options)


def render_text(question: Question, star: str) -> str:
    lines = [question.text, ""]
    for i, option in enumerate(question.options, start=1):
        mark = f"{star} " if option.recommended else ""
        lines.append(f"{i}. {mark}{option.title}: {option.description} ({option.cost})")
    return "\n".join(lines)


def render_keyboard(question: Question, labels: dict[str, str]) -> InlineKeyboardMarkup:
    """labels: star, custom, unknown, back, compare (all from the translator)."""
    rows = []
    for i, option in enumerate(question.options):
        title = (f"{labels['star']} " if option.recommended else "") + option.title
        rows.append(
            [
                InlineKeyboardButton(
                    text=title[:BUTTON_TITLE_LIMIT], callback_data=callback(question.id, f"o{i}")
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=labels["custom"], callback_data=callback(question.id, "custom")
            ),
            InlineKeyboardButton(
                text=labels["unknown"], callback_data=callback(question.id, "unknown")
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text=labels["back"], callback_data=callback(question.id, "back")),
            InlineKeyboardButton(
                text=labels["compare"], callback_data=callback(question.id, "compare")
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def render_comparison(question: Question, labels: dict[str, str]) -> str:
    blocks = [question.text, ""]
    for i, o in enumerate(question.options, start=1):
        star = f" {labels['star']}" if o.recommended else ""
        blocks.append(f"{i}. {o.title}{star}")
        blocks.append(f"{labels['cost']}: {o.cost}")
        blocks.extend(f"+ {p}" for p in o.pros)
        blocks.extend(f"- {c}" for c in o.cons)
        blocks.append("")
    return "\n".join(blocks).strip()
