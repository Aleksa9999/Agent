"""The track of a person and the three first skills (table in _docs/placement-test.md).

Rules, first match wins:
  student                                              -> study
  business owner with a working or starting business   -> automation (wants to build) or business
  goal for 10 weeks is a prototype or a site           -> site_tool
  experience in teaching, not a business owner         -> teach
  goal for 10 weeks is clients/money, not a business   -> ai_services
  has an idea (clear, rough or several)                -> have_idea
  everything else                                      -> find_idea
Only answers given with a button (a code) steer the rules; own words and "don't know" fall
through to the next rule, so nobody lands on a track by accident."""

from dataclasses import dataclass

from app.profile.fields import Answers, role_code

TRACK_ORDER = (
    "find_idea",
    "have_idea",
    "site_tool",
    "business",
    "study",
    "ai_services",
    "teach",
    "automation",
)
TRACK_SKILLS: dict[str, tuple[str, str, str | None]] = {
    "find_idea": ("idea-interview", "idea-card", "competitors-quick-check"),
    "have_idea": ("idea-card", "competitors-quick-check", "idea-validation"),
    "site_tool": ("idea-card", "mvp-scope", None),  # the third one depends on complexity
    "business": ("routine-audit", "competitors-analysis", "casdev-questions"),
    "study": ("tutor-oge-ege", "idea-card", "claude-code-basics"),
    "ai_services": ("ai-consulting", "ai-agency", "site-with-ai"),
    "teach": ("idea-card", "sell-ai-courses", "site-with-ai"),
    "automation": ("routine-audit", "automation-build", "virtual-employees"),
}
SITE, APP = "site-with-ai", "app-with-ai"
EXTRA_SKILL = "claude-code-basics"
DEEP = ("2", "3")
WORKING_BUSINESS = ("o1", "o2", "o3")  # works, just launching, services as self-employed


@dataclass(frozen=True)
class TrackPlan:
    track: str
    skills: tuple[str, str, str]
    extra: str | None  # added when the person wants to understand the technical side


def _code(answers: Answers, field: str) -> str | None:
    answer = answers.get(field)
    return answer.code if answer is not None and answer.kind in ("option", "voice") else None


def choose_track(answers: Answers) -> str:
    role = role_code(answers)
    if role == "student":
        return "study"
    if role == "business" and _code(answers, "business") in WORKING_BUSINESS:
        wants_depth = _code(answers, "tech_depth") in DEEP or _code(answers, "ai_level") in DEEP
        return "automation" if _code(answers, "business") == "o1" and wants_depth else "business"
    goal = _code(answers, "goal_10w")
    if goal == "o2":
        return "site_tool"
    if _code(answers, "experience") == "o4" and role != "business":
        return "teach"
    if goal == "o1" and role in ("employee", "searching"):
        return "ai_services"
    if _code(answers, "idea") in ("o1", "o2", "o3"):
        return "have_idea"
    return "find_idea"


def plan_for(answers: Answers) -> TrackPlan:
    track = choose_track(answers)
    first, second, third = TRACK_SKILLS[track]
    if third is None:  # a site for most people, an application when the person wants depth
        deep = _code(answers, "tech_depth") in DEEP or _code(answers, "goal_year") == "o4"
        third = APP if deep else SITE
    skills = (first, second, third)
    extra = (
        EXTRA_SKILL if _code(answers, "tech_depth") in DEEP and EXTRA_SKILL not in skills else None
    )
    return TrackPlan(track, skills, extra)


# what the first result is for each track
RESULT_KIND = {
    "find_idea": "idea",
    "have_idea": "idea",
    "site_tool": "idea",
    "business": "routines",
    "automation": "routines",
    "study": "plan",
    "ai_services": "plan",
    "teach": "plan",
}
LEVEL_STARTS = (0, 25, 100, 250, 500, 1000)  # skills counted: level 1 .. 6


def level_for(counter: int) -> int:
    return sum(1 for start in LEVEL_STARTS if counter >= start)
