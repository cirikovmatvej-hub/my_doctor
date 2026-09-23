"""
BAD advisor — goal-based supplement recommendation, read-only (starting a
tracked course happens in the tracker router).

Mirrors handlers/bad_advisor.py's logic — including its safety split: a
product with a contraindication for this profile is left out entirely (its
reason goes in blocked_notes), while non-blocking cautions come back as
warnings next to a card that is still shown. Returns plain structured text
instead of pre-assembled HTML — the client renders it.
"""
import re

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user
from api.schemas import (
    BadCardOut, BadGoalOut, ClarifyOptionOut, ClarifyOut, GeneralCardOut,
    GoalCheckRequest, GoalCheckResponse,
)
from data.bad_safety import check_bad_safety, get_bad_synergies, suggest_goal_keys
from data.general_supplements import GENERAL_SUPPLEMENTS, check_general_supplement_safety
from data.resources import BAD_DETAILS, BAD_GOALS, BADS, GOAL_CLARIFY_QUESTIONS, LIFESTYLE_TIPS
from database.db import get_user_profile_by_id

router = APIRouter(tags=["bad_advisor"])


def _strip_html(text: str) -> str:
    return re.sub(r"</?b>", "", text)


def _bad_card(bad_key: str) -> BadCardOut:
    d = BAD_DETAILS[bad_key]
    b = BADS[bad_key]
    return BadCardOut(
        key=bad_key,
        emoji=d["emoji"],
        full_name=d["full_name"],
        goal=d["goal"],
        course_days=d["course_days"],
        dosage=d["dosage"],
        daily_doses=d["daily_doses"],
        default_times=d["default_times"],
        best_time=d["best_time"],
        with_food=d["with_food"],
        notes=d["notes"],
        url=b["url"],
        synergies=[s.message for s in get_bad_synergies(bad_key)],
    )


def _general_card(general_key: str) -> GeneralCardOut:
    d = GENERAL_SUPPLEMENTS[general_key]
    return GeneralCardOut(key=general_key, label=d["label"], goal=d["goal"], notes=d.get("notes"))


def _clarify_out(goal_key: str) -> ClarifyOut | None:
    clarify = GOAL_CLARIFY_QUESTIONS.get(goal_key)
    if not clarify:
        return None
    return ClarifyOut(
        question=clarify["question"],
        options=[ClarifyOptionOut(key=k, label=label) for k, label in clarify["options"]],
    )


@router.get("/bad-goals", response_model=list[BadGoalOut])
async def list_bad_goals(user_id: int = Depends(get_current_user)) -> list[BadGoalOut]:
    profile = await get_user_profile_by_id(user_id)
    suggested = set(suggest_goal_keys(profile))
    goals = [
        BadGoalOut(
            key=key, label=goal["label"], description=goal["description"],
            suggested=key in suggested, clarify=_clarify_out(key),
        )
        for key, goal in BAD_GOALS.items()
    ]
    # Presentation only, like the bot's keyboard: profile matches first, nothing hidden.
    return sorted(goals, key=lambda g: not g.suggested)


@router.post("/bad-advisor/check", response_model=GoalCheckResponse)
async def check_goal(
    body: GoalCheckRequest, user_id: int = Depends(get_current_user)
) -> GoalCheckResponse:
    goal = BAD_GOALS.get(body.goal_key)
    if not goal:
        raise HTTPException(status_code=404, detail="Unknown goal")

    extra_note = None
    if body.clarify_option is not None:
        clarify = GOAL_CLARIFY_QUESTIONS.get(body.goal_key)
        extra_note = clarify["notes"].get(body.clarify_option) if clarify else None
        if extra_note is None:
            raise HTTPException(status_code=404, detail="Unknown clarify option")

    profile = await get_user_profile_by_id(user_id)

    blocked_bad_keys: set[str] = set()
    blocked_general_keys: set[str] = set()
    warnings: list[str] = []
    blocked_notes: list[str] = []

    for bad_key in goal["bads"]:
        found = check_bad_safety(bad_key, profile)
        if any(w.kind == "contraindication" for w in found):
            blocked_bad_keys.add(bad_key)
            blocked_notes.extend(w.message for w in found if w.kind == "contraindication")
        else:
            warnings.extend(w.message for w in found)

    general_keys = goal.get("general_supplements", [])
    for general_key in general_keys:
        found = check_general_supplement_safety(general_key, profile)
        if any(w.kind == "contraindication" for w in found):
            blocked_general_keys.add(general_key)
            blocked_notes.extend(w.message for w in found if w.kind == "contraindication")
        else:
            warnings.extend(w.message for w in found)

    return GoalCheckResponse(
        goal_label=goal["label"],
        warnings=warnings,
        blocked_notes=blocked_notes,
        extra_note=extra_note,
        lifestyle_tips=_strip_html(LIFESTYLE_TIPS.get(body.goal_key, "")),
        bads=[_bad_card(k) for k in goal["bads"] if k not in blocked_bad_keys],
        general_supplements=[_general_card(k) for k in general_keys if k not in blocked_general_keys],
    )
