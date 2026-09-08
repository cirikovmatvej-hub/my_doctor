"""
Product tracking — start a course, view progress, log intake.

Reminders themselves are scheduled client-side as local iOS notifications
(see the iOS app's NotificationScheduler) rather than server-pushed, so
there's no reminder loop here — unlike the bot, which polls Telegram.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user
from api.schemas import IntakeRequest, TrackerCreateRequest, TrackerOut
from data.resources import BAD_DETAILS
from database.db import create_tracking, get_active_trackings, get_days_taken, get_tracking, log_intake

router = APIRouter(prefix="/tracker", tags=["tracker"])


@router.get("", response_model=list[TrackerOut])
async def list_trackings(user_id: int = Depends(get_current_user)) -> list[TrackerOut]:
    rows = await get_active_trackings(user_id)
    result = []
    for tracking_id, product_key, start_date, course_days, rt1, rt2 in rows:
        d = BAD_DETAILS.get(product_key, {})
        days_taken = await get_days_taken(tracking_id)
        result.append(TrackerOut(
            id=tracking_id, product_key=product_key,
            emoji=d.get("emoji", "💊"), full_name=d.get("full_name", product_key),
            start_date=start_date, course_days=course_days, days_taken=days_taken,
            reminder_time_1=rt1, reminder_time_2=rt2,
        ))
    return result


@router.post("", response_model=TrackerOut)
async def start_tracking(
    body: TrackerCreateRequest, user_id: int = Depends(get_current_user)
) -> TrackerOut:
    if body.product_key not in BAD_DETAILS:
        raise HTTPException(status_code=404, detail="Unknown product")
    d = BAD_DETAILS[body.product_key]

    tracking_id = await create_tracking(
        user_id, body.product_key, d["course_days"],
        body.reminder_time_1, body.reminder_time_2,
    )

    return TrackerOut(
        id=tracking_id, product_key=body.product_key,
        emoji=d["emoji"], full_name=d["full_name"],
        start_date=datetime.now().strftime("%Y-%m-%d"), course_days=d["course_days"],
        days_taken=0, reminder_time_1=body.reminder_time_1, reminder_time_2=body.reminder_time_2,
    )


@router.post("/{tracking_id}/intake")
async def log_tracking_intake(
    tracking_id: int, body: IntakeRequest, user_id: int = Depends(get_current_user)
) -> dict:
    tracking = await get_tracking(tracking_id)
    if not tracking or tracking["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Tracking not found")
    today = datetime.now().strftime("%Y-%m-%d")
    await log_intake(tracking_id, today, body.slot, body.status)
    return {"status": "ok"}
