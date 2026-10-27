#!/usr/bin/env python3
"""Статическая проверка навыков content/skills (без модели).

Правила проверки лежат в skillkit/validator.py: тот же код проверяет загрузку навыка владельцем.
Запуск: python3 -I tools/validate_skills.py [корень репозитория]
Код выхода 0, если всё прошло, иначе 1.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # -I drops the implicit path, so it is added by hand

from skillkit.validator import check_skill  # noqa: E402

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO
SK = ROOT / "content" / "skills"


def main():
    files = sorted(SK.glob("*/*/SKILL.md"))
    if not files:
        print("навыков не найдено")
        return 1
    all_errs, names = [], []
    for f in files:
        all_errs += check_skill(f)
        names.append(f.parent.name)
    dup = {n for n in names if names.count(n) > 1}
    for n in dup:
        all_errs.append(f"дубль slug: {n}")
    for e in all_errs:
        print("ОШИБКА", e)
    by_branch = {}
    for f in files:
        by_branch.setdefault(f.parent.parent.name, 0)
        by_branch[f.parent.parent.name] += 1
    print(f"навыков: {len(files)}; по веткам: {dict(sorted(by_branch.items()))}")
    print("результат:", "ОК" if not all_errs else f"ошибок: {len(all_errs)}")
    return 0 if not all_errs else 1


if __name__ == "__main__":
    sys.exit(main())
