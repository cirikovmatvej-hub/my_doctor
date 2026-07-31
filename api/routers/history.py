"""Consultation history. Full transcripts are already served by GET /consultations/{id}."""
from fastapi import APIRouter, Depends

from api.deps import get_current_user
from api.schemas import HistoryEntryOut
from database.db import get_user_sessions_full

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=list[HistoryEntryOut])
async def list_history(limit: int = 5, user_id: int = Depends(get_current_user)) -> list[HistoryEntryOut]:
    rows = await get_user_sessions_full(user_id, limit=limit)
    return [
        HistoryEntryOut(
            session_id=r[0], complaint=r[1], summary=r[2], created_at=r[3], family_member_name=r[4],
        )
        for r in rows
    ]
