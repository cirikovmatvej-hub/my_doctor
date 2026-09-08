"""
Doctor appointment follow-ups — simplified for the app vs. the bot.

The bot polls a background loop to send the "did you book?" ask and a later
reminder. The app instead schedules both as local notifications client-side
right when a doctor recommendation is shown (see the iOS NotificationScheduler),
so this router is just persistence: create the record, update its status.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user
from api.schemas import AppointmentCreate, AppointmentOut, AppointmentStatusUpdate
from config import APPOINTMENT_ASK_HOURS
from data.resources import DOCTORS
from database.db import (
    create_appointment_followup, get_appointment_followup,
    set_appointment_reason, set_appointment_status,
)

router = APIRouter(prefix="/appointments", tags=["appointment"])


@router.post("", response_model=AppointmentOut)
async def create_appointment(
    body: AppointmentCreate, user_id: int = Depends(get_current_user)
) -> AppointmentOut:
    if body.doctor_specialty not in DOCTORS:
        raise HTTPException(status_code=404, detail="Unknown doctor specialty")

    ask_at = datetime.now() + timedelta(hours=APPOINTMENT_ASK_HOURS)
    followup_id = await create_appointment_followup(user_id, body.doctor_specialty, ask_at)

    return AppointmentOut(
        id=followup_id,
        doctor_specialty=body.doctor_specialty,
        doctor_name=DOCTORS[body.doctor_specialty]["name"],
        status="pending",
    )


@router.put("/{followup_id}/status")
async def update_appointment_status(
    followup_id: int, body: AppointmentStatusUpdate, user_id: int = Depends(get_current_user)
) -> dict:
    followup = await get_appointment_followup(followup_id)
    if not followup or followup["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Appointment not found")
    await set_appointment_status(followup_id, body.status)
    if body.reason:
        await set_appointment_reason(followup_id, body.reason)
    return {"status": "ok"}
