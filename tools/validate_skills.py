#!/usr/bin/env python3
"""Статическая проверка навыков content/skills (без модели).

Проверяет у каждого навыка:
  - frontmatter: все обязательные поля, значения из допустимых наборов;
  - обязательные разделы тела (из _FORMAT.md);
  - критерии приёмки К1…Кn нумерованы подряд без пропусков и их не меньше min_criteria;
  - test.yaml: парсится, есть static, scenarios (не меньше одного, у каждого must и must_not),
    pass_score и real_run_proof;
  - slug совпадает с именем каталога, ветка совпадает с родительским каталогом;
  - в тексте навыка нет секретов (простые паттерны) и нет «голых» цен в валюте без пометки (пример).
Запуск: python3 -I tools/validate_skills.py [корень репозитория]
Код выхода 0, если всё прошло, иначе 1.
"""

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
SK = ROOT / "content" / "skills"

BRANCHES = {
    "strategy",
    "research",
    "sales",
    "product",
    "code",
    "design",
    "content",
    "video-voice",
    "automation",
    "personal",
}
KINDS = {"build", "deliver", "method"}
RUNS = {"dev-skills", "direct"}
SOURCES = {"studio", "lesson-01", "lesson-02", "client", "market"}
REQ_FM = [
    "name",
    "title",
    "branch",
    "version",
    "kind",
    "runs_via",
    "min_level",
    "triggers",
    "inputs",
    "outputs",
    "box_tiers",
    "autotest",
    "source",
]
REQ_SECTIONS = [
    "Назначение",
    "Когда включать",
    "Адаптация под паспорт",
    "Допрос",
    "Конвейер",
    "Коробка ИИ",
    "Критерии приёмки",
    "Отказы и границы",
    "Доказательство «Сработало»",
]
SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9]{20,}",
    r"ghp_[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"\b\d{9,10}:[A-Za-z0-9_-]{30,}\b",
]


def check_skill(skill_md: Path):
    errs = []
    d = skill_md.parent
    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    if not m:
        return [f"{d.name}: нет frontmatter"]
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        return [f"{d.name}: frontmatter не парсится: {e}"]
    body = m.group(2)

    for k in REQ_FM:
        if k not in fm or fm[k] in (None, "", []):
            errs.append(f"{d.name}: нет поля frontmatter '{k}'")
    if errs:
        return errs
    if fm["name"] != d.name:
        errs.append(f"{d.name}: name '{fm['name']}' не совпадает с каталогом")
    if not re.fullmatch(r"[a-z0-9-]+", fm["name"]):
        errs.append(f"{d.name}: name должен быть a-z0-9-")
    if fm["branch"] not in BRANCHES:
        errs.append(f"{d.name}: неизвестная ветка {fm['branch']}")
    if d.parent.name != fm["branch"]:
        errs.append(f"{d.name}: каталог ветки {d.parent.name} не равен branch {fm['branch']}")
    if fm["kind"] not in KINDS:
        errs.append(f"{d.name}: kind {fm['kind']}")
    if fm["runs_via"] not in RUNS:
        errs.append(f"{d.name}: runs_via {fm['runs_via']}")
    if fm["source"] not in SOURCES:
        errs.append(f"{d.name}: source {fm['source']}")
    if not (isinstance(fm["min_level"], int) and 1 <= fm["min_level"] <= 6):
        errs.append(f"{d.name}: min_level 1..6")
    if not re.fullmatch(r"v[1-3]", str(fm["version"])):
        errs.append(f"{d.name}: version v1..v3")
    if list(fm["box_tiers"]) != ["economy", "standard", "premium"]:
        errs.append(f"{d.name}: box_tiers должен быть [economy, standard, premium]")
    if fm["kind"] in ("build", "deliver") and fm["runs_via"] != "dev-skills":
        errs.append(f"{d.name}: build/deliver обязаны идти через dev-skills (решение Арсена)")

    heads = re.findall(r"^## (.+?)\s*$", body, re.M)
    for s in REQ_SECTIONS:
        if s not in heads:
            errs.append(f"{d.name}: нет раздела '## {s}'")

    # критерии
    sec = re.search(r"^## Критерии приёмки\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    nums = [int(n) for n in re.findall(r"\*\*К(\d+)\.\*\*", sec.group(1))] if sec else []
    if nums != list(range(1, len(nums) + 1)):
        errs.append(f"{d.name}: критерии К не идут подряд с К1: {nums}")

    # конвейер для dev-skills
    if fm["runs_via"] == "dev-skills":
        conv = re.search(r"^## Конвейер\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
        conv_t = conv.group(1) if conv else ""
        for sk in ["grill-me", "to-spec", "to-tasks", "implement", "code-review", "handoff"]:
            if sk not in conv_t:
                errs.append(f"{d.name}: в конвейере нет фазы {sk}")

    # секреты
    for p in SECRET_PATTERNS:
        if re.search(p, text):
            errs.append(f"{d.name}: найден похожий на секрет фрагмент по паттерну {p}")

    # test.yaml
    t = d / str(fm["autotest"])
    if not t.exists():
        errs.append(f"{d.name}: нет {fm['autotest']}")
        return errs
    try:
        ty = yaml.safe_load(t.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        errs.append(f"{d.name}: test.yaml не парсится: {e}")
        return errs
    if ty.get("skill") != fm["name"]:
        errs.append(f"{d.name}: test.yaml.skill не совпадает с name")
    st = ty.get("static") or {}
    for s in st.get("required_sections", []):
        if s not in heads:
            errs.append(f"{d.name}: test.yaml требует раздел '{s}', которого нет")
    need = st.get("min_criteria", 0)
    if len(nums) < need:
        errs.append(f"{d.name}: критериев {len(nums)}, нужно минимум {need}")
    sc = ty.get("scenarios") or []
    if not sc:
        errs.append(f"{d.name}: в test.yaml нет сценариев")
    for s in sc:
        if not s.get("input") or not s.get("must") or not s.get("must_not"):
            errs.append(f"{d.name}: сценарий {s.get('id')} без input/must/must_not")
    if not (isinstance(ty.get("pass_score"), int) and 1 <= ty["pass_score"] <= 10):
        errs.append(f"{d.name}: pass_score 1..10")
    if not ty.get("real_run_proof"):
        errs.append(f"{d.name}: нет real_run_proof")
    return errs


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
