"""Prompt files live in prompts/*.md (content, edited without touching code)."""

from pathlib import Path


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def load_prompt(directory: Path, filename: str, /, **values: object) -> str:
    text = (Path(directory) / filename).read_text(encoding="utf-8")
    return text.format_map(_Safe(**{k: str(v) for k, v in values.items()}))
