#!/usr/bin/env python3
"""Собирает content/skills/INDEX.md из frontmatter всех навыков."""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
SK = ROOT / "content" / "skills"
RU = {
    "strategy": "Стратегия",
    "research": "Исследования",
    "sales": "Клиенты и продажи",
    "product": "Продукт",
    "code": "Код",
    "design": "Дизайн",
    "content": "Контент",
    "video-voice": "Видео и голос",
    "automation": "Автоматизация",
    "personal": "Личная эффективность",
}
rows = {}
for f in sorted(SK.glob("*/*/SKILL.md")):
    fm = yaml.safe_load(
        re.match(r"---\n(.*?)\n---\n", f.read_text(encoding="utf-8"), re.S).group(1)
    )
    rows.setdefault(fm["branch"], []).append(fm)
out = [
    "# Библиотека навыков студии",
    "",
    "Файл собирается командой `python3 tools/build_index.py`, руками не правится.",
    "",
]
total = sum(len(v) for v in rows.values())
out.append(
    f"Всего навыков: **{total}**. Пустые ветки: "
    + (", ".join(RU[b] for b in RU if b not in rows) or "нет")
    + "."
)
out.append("")
for b in RU:
    if b not in rows:
        continue
    out += [
        f"## {RU[b]}",
        "",
        "| Навык | Вид | Конвейер | Уровень | Источник |",
        "|---|---|---|---|---|",
    ]
    for fm in rows[b]:
        out.append(
            f"| `{fm['name']}` — {fm['title']} | {fm['kind']} | {fm['runs_via']} "
            f"| {fm['min_level']} | {fm['source']} |"
        )
    out.append("")
(SK / "INDEX.md").write_text("\n".join(out), encoding="utf-8")
print("INDEX.md:", total, "навыков")
