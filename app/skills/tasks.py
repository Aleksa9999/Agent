"""Tasks (vertical slices with blockers and a coverage map) and the prompt pack.

Pure functions: validation of what the model proposes and rendering of what the person sees.
`t` is the translator bound to a tenant: t(key, **values) -> text."""

from collections.abc import Callable

from skillkit.parse import SkillDoc

Translate = Callable[..., str]


class TaskError(ValueError):
    """The proposal breaks a rule. The text goes back to the model so that it fixes it."""


def _clip(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _numbers(value: object, name: str, limit: int, *, below: int | None = None) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TaskError(f"{name} must be a list of numbers")
    found: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise TaskError(f"{name} holds only whole numbers")
        if not 1 <= item <= limit or (below is not None and item >= below):
            raise TaskError(f"{name}: {item} is not allowed here")
        if item not in found:
            found.append(item)
    return found


def validate_tasks(arguments: dict, spec: dict, rules: dict) -> dict:
    raw = arguments.get("tasks")
    if not isinstance(raw, list) or not raw:
        raise TaskError("tasks: at least one task is required")
    if len(raw) > rules["max_tasks"]:
        raise TaskError(f"tasks: at most {rules['max_tasks']}")
    criteria_count = len(spec["criteria"])
    tasks = []
    for number, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise TaskError(f"task {number} must be an object")
        title = _clip(item.get("title"), 160)
        what = _clip(item.get("what"), 800)
        if len(title) < rules["min_task_title_chars"]:
            raise TaskError(f"task {number}: the title is too short")
        if len(what) < rules["min_task_what_chars"]:
            raise TaskError(
                f"task {number}: describe the end-to-end result the person can show or check"
            )
        tasks.append(
            {
                "n": number,
                "title": title,
                "what": what,
                # a task may only wait for earlier tasks: no cycles are possible
                "blocked_by": _numbers(
                    item.get("blocked_by"), f"task {number} blocked_by", len(raw), below=number
                ),
                "criteria": _numbers(
                    item.get("criteria"), f"task {number} criteria", criteria_count
                ),
            }
        )
    coverage = {
        k: [t["n"] for t in tasks if k in t["criteria"]] for k in range(1, criteria_count + 1)
    }
    uncovered = [k for k, closed_by in coverage.items() if not closed_by]
    return {
        "tasks": tasks,
        "coverage": {str(k): v for k, v in coverage.items()},
        "uncovered": uncovered,
    }


def render_tasks(t: Translate, doc: SkillDoc, spec: dict, plan: dict) -> str:
    lines = [t("tasks_title", title=doc.title), ""]
    for task in plan["tasks"]:
        lines.append(t("tasks_item", n=task["n"], title=task["title"]))
        blocked = ", ".join(str(n) for n in task["blocked_by"])
        lines.append(t("tasks_blocked", tasks=blocked) if blocked else t("tasks_blocked_none"))
        lines.append(t("tasks_what", text=task["what"]))
        closes = ", ".join(f"{t('tasks_k')}{k}" for k in task["criteria"])
        lines.append(t("tasks_closes", criteria=closes) if closes else t("tasks_closes_none"))
        lines.append("")
    lines.append(t("tasks_cov_head"))
    for k, closed_by in plan["coverage"].items():
        if closed_by:
            lines.append(t("tasks_cov_line", k=k, tasks=", ".join(str(n) for n in closed_by)))
    if plan["uncovered"]:
        lines += ["", t("tasks_uncovered_head")]
        for k in plan["uncovered"]:
            lines.append(t("tasks_uncovered_line", k=k, text=spec["criteria"][k - 1]))
        lines += ["", t("tasks_aware_ask")]
    return "\n".join(lines)


def validate_pack(arguments: dict, plan: dict, rules: dict) -> dict:
    fence = rules["code_fence"]

    def clean(value: object, name: str, minimum: int, limit: int) -> str:
        text = _clip(value, limit)
        if len(text) < minimum:
            raise TaskError(f"{name} is missing or too short")
        if rules["forbid_code_fence_in_pack"] and fence in text:
            raise TaskError(
                f"{name}: the pack holds no code blocks; describe behavior, limits and checks"
            )
        return text

    minimum = rules["min_pack_field_chars"]
    steps = [clean(s, "a step", 3, 400) for s in arguments.get("steps") or []]
    pack_rules = [clean(r, "a rule", 3, 400) for r in arguments.get("rules") or []]
    if not steps or not pack_rules:
        raise TaskError("steps and rules: at least one of each")
    prompts, seen = [], set()
    for item in arguments.get("prompts") or []:
        if not isinstance(item, dict) or not isinstance(item.get("task"), int):
            raise TaskError("each prompt names its task by number")
        number = item["task"]
        if number in seen or not any(task["n"] == number for task in plan["tasks"]):
            raise TaskError(f"prompt for task {number}: unknown or repeated")
        seen.add(number)
        prompts.append(
            {
                "task": number,
                "goal": clean(item.get("goal"), f"task {number} goal", minimum, 800),
                "context": clean(item.get("context"), f"task {number} context", minimum, 800),
                "constraints": clean(
                    item.get("constraints"), f"task {number} constraints", minimum, 800
                ),
                "checks": clean(item.get("checks"), f"task {number} checks", minimum, 800),
            }
        )
    missing = [task["n"] for task in plan["tasks"] if task["n"] not in seen]
    if missing:
        raise TaskError(f"no prompt for tasks: {missing}")
    prompts.sort(key=lambda p: p["task"])
    return {"steps": steps, "rules": pack_rules, "prompts": prompts}


def render_pack(t: Translate, doc: SkillDoc, spec: dict, plan: dict, pack: dict) -> str:
    titles = {task["n"]: task["title"] for task in plan["tasks"]}
    lines = [t("pack_title", title=doc.title), "", t("pack_h_steps")]
    lines += [f"{i}. {step}" for i, step in enumerate(pack["steps"], start=1)]
    lines += ["", t("pack_h_rules")]
    lines += [t("spec_bullet", text=rule) for rule in pack["rules"]]
    lines += [
        t("spec_bullet", text=t("pack_rule_secrets")),
        t("spec_bullet", text=t("pack_rule_scope")),
    ]
    lines += ["", t("pack_h_checklist")]
    lines += [
        t("pack_check_line", k=i, text=text) for i, text in enumerate(spec["criteria"], start=1)
    ]
    lines += ["", t("pack_h_prompts")]
    for prompt in pack["prompts"]:
        lines += [
            "",
            t("pack_prompt_head", n=prompt["task"], title=titles[prompt["task"]]),
            t("pack_goal", text=prompt["goal"]),
            t("pack_context", text=prompt["context"]),
            t("pack_constraints", text=prompt["constraints"]),
            t("pack_checks", text=prompt["checks"]),
        ]
    return "\n".join(lines)
