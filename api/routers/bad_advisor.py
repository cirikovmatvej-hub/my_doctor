"""
BAD advisor — goal-based supplement recommendation, read-only for Phase 2
(starting a tracked course happens in Phase 3's tracker router).

Mirrors handlers/bad_advisor.py's safety-check and card logic, but returns
plain structured text instead of pre-assembled HTML — the client renders it.
"""
import re

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user
from api.schemas import BadCardOut, BadGoalOut, GoalCheckRequest, GoalCheckResponse
from data.bad_safety import check_bad_safety
from data.resources import BAD_DETAILS, BAD_GOALS, BADS, LIFESTYLE_TIPS
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
    )


@router.get("/bad-goals", response_model=list[BadGoalOut])
async def list_bad_goals() -> list[BadGoalOut]:
    return [
        BadGoalOut(key=key, label=goal["label"], description=goal["description"])
        for key, goal in BAD_GOALS.items()
    ]


@router.post("/bad-advisor/check", response_model=GoalCheckResponse)
async def check_goal(
    body: GoalCheckRequest, user_id: int = Depends(get_current_user)
) -> GoalCheckResponse:
    goal = BAD_GOALS.get(body.goal_key)
    if not goal:
        raise HTTPException(status_code=404, detail="Unknown goal")

    profile = await get_user_profile_by_id(user_id)

    warnings: list[str] = []
    for bad_key in goal["bads"]:
        warnings.extend(w.message for w in check_bad_safety(bad_key, profile))

    return GoalCheckResponse(
        goal_label=goal["label"],
        warnings=warnings,
        lifestyle_tips=_strip_html(LIFESTYLE_TIPS.get(body.goal_key, "")),
        bads=[_bad_card(bad_key) for bad_key in goal["bads"]],
    )
