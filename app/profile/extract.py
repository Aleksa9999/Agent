"""Turns a recognised story into profile fields through one model call with one function.

The story is untrusted text. It can only change the profile fields: the model answers through a
function whose arguments are validated here (known fields, allowed codes, short plain text)."""

import re
from pathlib import Path

from app.agent.model import ModelPort
from app.agent.prompts import load_prompt
from app.agent.types import FunctionSpec, Message, ModelRequest
from app.profile.fields import CUSTOM_LIMIT, ENUM_CODES, FIELDS

FUNCTION_NAME = "save_profile"
STORY_LIMIT = 6000
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_text(value: object, limit: int = CUSTOM_LIMIT) -> str:
    if not isinstance(value, str):
        return ""
    return _CONTROL.sub(" ", value).strip()[:limit].strip()


def _spec() -> FunctionSpec:
    properties: dict = {}
    for field in FIELDS:
        if field in ENUM_CODES:
            properties[field] = {"type": "string", "enum": list(ENUM_CODES[field])}
        else:
            properties[field] = {"type": "string", "maxLength": 200}
    return FunctionSpec(
        name=FUNCTION_NAME,
        description="Save the profile fields the person stated directly.",
        parameters={"type": "object", "properties": properties},
    )


async def extract_profile(model: ModelPort, prompts_dir: Path, story: str) -> dict[str, str]:
    """field -> value for fields the person stated. Anything unknown or malformed is dropped."""
    request = ModelRequest(
        mode="summary",
        instructions=load_prompt(prompts_dir, "profile_extract.md"),
        messages=[Message("user", f"<story>\n{story[:STORY_LIMIT]}\n</story>")],
        functions=(_spec(),),
    )
    result = await model.complete(request)
    call = next((c for c in result.tool_calls if c.name == FUNCTION_NAME), None)
    if call is None:
        return {}
    found: dict[str, str] = {}
    for field in FIELDS:
        value = call.arguments.get(field)
        if field in ENUM_CODES:
            if isinstance(value, (str, int)) and str(value) in ENUM_CODES[field]:
                found[field] = str(value)
        elif clean_text(value):
            found[field] = clean_text(value)
    return found
