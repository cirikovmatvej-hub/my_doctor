"""Wellbeing diary — daily self-assessment (sleep / energy / stress / BADs taken)."""
from fastapi import APIRouter, Depends, HTTPException

from api.dates import resolve_client_date
from api.deps import get_current_user
from api.schemas import (
    DiaryChangeOut, DiaryCorrelationOut, DiaryCourseOut, DiaryEntryIn, DiaryEntryOut,
    DiaryInsightsOut,
)
from data.diary_insights import course_correlations
from data.resources import BAD_DETAILS
from database.db import get_all_trackings, get_diary_entries, save_diary_entry

router = APIRouter(prefix="/diary", tags=["diary"])

MAX_ENTRIES = 90
INSIGHTS_DAYS = 30  # same window the bot's chart plots


def _full_name(product_key: str) -> str:
    return BAD_DETAILS.get(product_key, {}).get("full_name", product_key)


@router.get("", response_model=list[DiaryEntryOut])
async def list_diary(limit: int = 7, user_id: int = Depends(get_current_user)) -> list[DiaryEntryOut]:
    rows = await get_diary_entries(user_id, limit=min(max(limit, 1), MAX_ENTRIES))
    return [
        DiaryEntryOut(
            entry_date=entry_date, sleep_quality=sleep, energy_level=energy,
            stress_level=stress, bads_taken=bool(bads), notes=notes,
        )
        for entry_date, sleep, energy, stress, bads, notes in rows
    ]


@router.get("/insights", response_model=DiaryInsightsOut)
async def diary_insights(user_id: int = Depends(get_current_user)) -> DiaryInsightsOut:
    """Course start dates within the charted window, plus what moved in the
    user's own diary averages since each course began. The chart itself is
    drawn client-side from GET /diary?limit=30."""
    entries = list(reversed(await get_diary_entries(user_id, limit=INSIGHTS_DAYS)))  # chronological
    trackings = await get_all_trackings(user_id)

    courses = []
    if entries:
        date_min, date_max = entries[0][0], entries[-1][0]
        courses = [
            DiaryCourseOut(
                product_key=product_key, full_name=_full_name(product_key),
                start_date=start_date[:10], status=status, ended_at=ended_at,
            )
            for _tid, product_key, start_date, status, ended_at in trackings
            if date_min <= start_date[:10] <= date_max
        ]

    correlations = [
        DiaryCorrelationOut(
            product_key=c.product_key, full_name=_full_name(c.product_key),
            changes=[DiaryChangeOut(metric=m.metric, before=m.before, after=m.after) for m in c.changes],
        )
        for c in course_correlations(entries, trackings)
    ]
    return DiaryInsightsOut(courses=courses, correlations=correlations)


@router.put("/today", response_model=DiaryEntryOut)
async def put_today_entry(
    body: DiaryEntryIn, user_id: int = Depends(get_current_user)
) -> DiaryEntryOut:
    entry_date = resolve_client_date(body.date)
    saved = await save_diary_entry(
        user_id=user_id, entry_date=entry_date,
        sleep_quality=body.sleep_quality, energy_level=body.energy_level,
        stress_level=body.stress_level, bads_taken=int(body.bads_taken),
        notes=body.notes,
    )
    if not saved:
        raise HTTPException(status_code=404, detail="User not found")
    return DiaryEntryOut(
        entry_date=entry_date, sleep_quality=body.sleep_quality, energy_level=body.energy_level,
        stress_level=body.stress_level, bads_taken=body.bads_taken, notes=body.notes,
    )
