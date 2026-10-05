"""
Product tracking — start a course, view progress, log intake, stop a course,
browse past courses.

Reminders themselves are scheduled client-side as local iOS notifications
(see the iOS app's NotificationScheduler) rather than server-pushed, so
there's no reminder loop here — unlike the bot, which polls Telegram.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from api.dates import resolve_client_date
from api.deps import get_current_user
from api.schemas import (
    DATE_PATTERN, IntakeOut, IntakeRequest, OkOut, TrackerCreateRequest,
    TrackerHistoryOut, TrackerOut,
)
from data.resources import BAD_DETAILS
from database.db import (
    complete_finished_trackings, create_tracking, get_active_trackings, get_days_taken,
    get_tracking, get_tracking_history, log_intake, stop_tracking,
)

router = APIRouter(prefix="/tracker", tags=["tracker"])

MAX_CUSTOM_NAME_LEN = 100   # same bounds as the bot's custom-БАД flow
MAX_COURSE_DAYS = 365


def _display(product_key: str) -> tuple[str, str]:
    """(emoji, full_name) — catalog products have both; a custom supplement
    is stored under the user's own name and gets the generic pill."""
    d = BAD_DETAILS.get(product_key, {})
    return d.get("emoji", "💊"), d.get("full_name", product_key)


@router.get("", response_model=list[TrackerOut])
async def list_trackings(user_id: int = Depends(get_current_user)) -> list[TrackerOut]:
    # Retire courses that reached their length, so they show up in history
    # rather than lingering as "active" at 100%.
    await complete_finished_trackings(user_id)

    rows = await get_active_trackings(user_id)
    result = []
    for tracking_id, product_key, start_date, course_days, rt1, rt2 in rows:
        emoji, full_name = _display(product_key)
        days_taken = await get_days_taken(tracking_id)
        result.append(TrackerOut(
            id=tracking_id, product_key=product_key,
            emoji=emoji, full_name=full_name,
            start_date=start_date, course_days=course_days, days_taken=days_taken,
            reminder_time_1=rt1, reminder_time_2=rt2,
        ))
    return result


@router.get("/history", response_model=list[TrackerHistoryOut])
async def list_tracking_history(
    limit: int = 15, user_id: int = Depends(get_current_user)
) -> list[TrackerHistoryOut]:
    await complete_finished_trackings(user_id)

    rows = await get_tracking_history(user_id, limit=min(max(limit, 1), 50))
    result = []
    for tracking_id, product_key, start_date, course_days, status in rows:
        emoji, full_name = _display(product_key)
        result.append(TrackerHistoryOut(
            id=tracking_id, product_key=product_key, emoji=emoji, full_name=full_name,
            start_date=start_date, course_days=course_days,
            days_taken=await get_days_taken(tracking_id), status=status,
        ))
    return result


@router.post("", response_model=TrackerOut)
async def start_tracking(
    body: TrackerCreateRequest, user_id: int = Depends(get_current_user)
) -> TrackerOut:
    if body.product_key in BAD_DETAILS:
        course_days = BAD_DETAILS[body.product_key]["course_days"]
    else:
        # Not one of ours — a supplement the user named themselves (either
        # typed in, or picked from the non-catalog suggestions).
        name = body.product_key.strip()
        if not (1 <= len(name) <= MAX_CUSTOM_NAME_LEN):
            raise HTTPException(
                status_code=422, detail=f"Name must be 1-{MAX_CUSTOM_NAME_LEN} characters"
            )
        if body.course_days is None or not (1 <= body.course_days <= MAX_COURSE_DAYS):
            raise HTTPException(
                status_code=422, detail=f"course_days (1-{MAX_COURSE_DAYS}) is required for a custom supplement"
            )
        body.product_key = name
        course_days = body.course_days

    # The course starts on the user's own calendar day, not the server's —
    # otherwise intakes logged with the device's date can pre-date start_date.
    start_date = resolve_client_date(body.date)
    tracking_id = await create_tracking(
        user_id, body.product_key, course_days,
        body.reminder_time_1, body.reminder_time_2,
        start_date=start_date,
    )

    emoji, full_name = _display(body.product_key)
    return TrackerOut(
        id=tracking_id, product_key=body.product_key,
        emoji=emoji, full_name=full_name,
        start_date=start_date, course_days=course_days,
        days_taken=0, reminder_time_1=body.reminder_time_1, reminder_time_2=body.reminder_time_2,
    )


async def _own_tracking(tracking_id: int, user_id: int) -> dict:
    tracking = await get_tracking(tracking_id)
    if not tracking or tracking["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Tracking not found")
    return tracking


@router.post("/{tracking_id}/intake", response_model=IntakeOut)
async def log_tracking_intake(
    tracking_id: int, body: IntakeRequest, user_id: int = Depends(get_current_user)
) -> IntakeOut:
    tracking = await _own_tracking(tracking_id, user_id)
    if tracking["status"] != "active":
        raise HTTPException(status_code=409, detail="Course is not active")
    if not await log_intake(tracking_id, resolve_client_date(body.date), body.slot, body.status):
        # The course was deleted (account removal) between the ownership check and the write.
        raise HTTPException(status_code=404, detail="Tracking not found")

    days_taken = await get_days_taken(tracking_id)
    finished = await complete_finished_trackings(user_id)
    return IntakeOut(
        status="ok", days_taken=days_taken, course_days=tracking["course_days"],
        course_completed=any(tid == tracking_id for tid, *_ in finished),
    )


@router.delete("/{tracking_id}", response_model=OkOut)
async def stop_course(
    tracking_id: int,
    date: str | None = Query(default=None, pattern=DATE_PATTERN),
    user_id: int = Depends(get_current_user),
) -> OkOut:
    tracking = await _own_tracking(tracking_id, user_id)
    if tracking["status"] != "active":
        # Already completed/stopped — keep its recorded end state as is.
        raise HTTPException(status_code=409, detail="Course is not active")
    await stop_tracking(tracking_id, ended_at=resolve_client_date(date))
    return OkOut()
