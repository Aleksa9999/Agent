"""Where the person is in the questionnaire. Pure functions: state in, state out.

state = {"batch": [fields still to ask in this block], "size": block length, "history": [fields
answered through the questions]}. The current question is the first of the batch. A block is never
longer than five questions; the next block is planned from everything answered so far."""

from app.profile.fields import BATCH_SIZE, Answers, next_batch


def ensure(state: dict | None, answers: Answers) -> dict:
    """A stored state, or a new one planned from the answers (the history is kept)."""
    if state and state.get("batch"):
        return state
    batch = next_batch(answers)
    return {"batch": batch, "size": len(batch), "history": list((state or {}).get("history", []))}


def current(state: dict) -> str | None:
    return state["batch"][0] if state.get("batch") else None


def index(state: dict) -> int:
    """1-based position of the current question inside its block."""
    return max(1, state["size"] - len(state["batch"]) + 1)


def after_answer(state: dict, answers: Answers) -> dict:
    """The current question was answered (the answer is already in `answers`)."""
    done = state["batch"][0]
    history = [*state.get("history", []), done]
    batch = state["batch"][1:]
    if not batch:
        batch = next_batch(answers)
        return {"batch": batch, "size": len(batch), "history": history}
    return {"batch": batch, "size": state["size"], "history": history}


def after_back(state: dict) -> dict:
    """Return to the previous question; its answer stays until a new one replaces it."""
    history = list(state.get("history", []))
    if not history:
        return state
    previous = history.pop()
    batch = [previous, *[f for f in state["batch"] if f != previous]][:BATCH_SIZE]
    return {"batch": batch, "size": max(state["size"], len(batch)), "history": history}


def after_merge(answers: Answers, history: list[str]) -> dict:
    """New facts arrived (a voice story): plan again from what is still missing."""
    batch = next_batch(answers)
    return {"batch": batch, "size": len(batch), "history": history}
