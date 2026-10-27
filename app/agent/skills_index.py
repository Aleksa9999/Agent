"""A compact skills catalog for the agent: one line per skill from the SKILL.md frontmatter."""

import re
from pathlib import Path

import yaml


def skills_index(skills_dir: Path) -> str:
    lines = []
    for path in sorted(Path(skills_dir).glob("*/*/SKILL.md")):
        match = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
        if not match:
            continue
        meta = yaml.safe_load(match.group(1))
        lines.append(f"{meta['name']} ({meta['kind']}, level {meta['min_level']}): {meta['title']}")
    return "\n".join(lines)


def skill_names(skills_dir: Path) -> str:
    return ", ".join(line.split(" (")[0] for line in skills_index(skills_dir).splitlines())
