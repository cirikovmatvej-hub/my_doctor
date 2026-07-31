"""Wellbeing diary — daily self-assessment (sleep / energy / stress / BADs taken)."""
from datetime import datetime

from fastapi import APIRouter, Depends

from api.deps import get_current_user
from api.schemas import DiaryEntryIn, DiaryEntryOut
from database.db import get_diary_entries, save_diary_entry

router = APIRouter(prefix="/diary", tags=["diary"])


@router.get("", response_model=list[DiaryEntryOut])
async def list_diary(limit: int = 7, user_id: int = Depends(get_current_user)) -> list[DiaryEntryOut]:
    rows = await get_diary_entries(user_id, limit=limit)
    return [
        DiaryEntryOut(
            entry_date=entry_date, sleep_quality=sleep, energy_level=energy,
            stress_level=stress, bads_taken=bool(bads), notes=notes,
        )
        for entry_date, sleep, energy, stress, bads, notes in rows
    ]


@router.put("/today", response_model=DiaryEntryOut)
async def put_today_entry(
    body: DiaryEntryIn, user_id: int = Depends(get_current_user)
) -> DiaryEntryOut:
    today = datetime.now().strftime("%Y-%m-%d")
    await save_diary_entry(
        user_id=user_id, entry_date=today,
        sleep_quality=body.sleep_quality, energy_level=body.energy_level,
        stress_level=body.stress_level, bads_taken=int(body.bads_taken),
        notes=body.notes,
    )
    return DiaryEntryOut(
        entry_date=today, sleep_quality=body.sleep_quality, energy_level=body.energy_level,
        stress_level=body.stress_level, bads_taken=body.bads_taken, notes=body.notes,
    )
