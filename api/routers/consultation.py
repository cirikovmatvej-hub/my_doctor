"""
Symptom consultation — text-only for Phase 1 (photo/PDF deferred).

Stateless by design: unlike the bot (which keeps the Groq conversation in
aiogram FSM memory as an optimization), every turn here rebuilds the full
transcript from the `messages` table. The assistant's raw JSON reply is
persisted as-is so the next call reconstructs exactly what the model saw.
"""
import json

from fastapi import APIRouter, Depends, HTTPException

from ai.assistant import analyze_symptoms
from api.deps import get_current_user
from api.schemas import (
    BadOut, ConsultationCreate, ConsultationOut, ConsultationTranscriptOut, DoctorOut,
    MessageIn, MessageOut, TranscriptTurn,
)
from config import MAX_QUESTIONS
from data.resources import BADS, DOCTORS
from database.db import (
    add_message, create_session, get_family_member, get_session, get_session_messages,
    get_user_profile_by_id, set_session_complaint, update_session_summary,
)

router = APIRouter(prefix="/consultations", tags=["consultation"])

EMERGENCY_NOTICE = (
    "\n\n🚨 Это может быть неотложным состоянием. "
    "Немедленно позвоните 112 (единая служба спасения) или 103 (скорая помощь)."
)


def _doctor_out(specialty: str | None) -> DoctorOut | None:
    if not specialty or specialty not in DOCTORS:
        return None
    d = DOCTORS[specialty]
    return DoctorOut(specialty=specialty, name=d["name"], url=d["url"])


def _bad_out(key: str | None) -> BadOut | None:
    if not key or key not in BADS:
        return None
    b = BADS[key]
    return BadOut(key=key, name=b["name"], url=b["url"], description=b["description"])


async def _own_session(session_id: int, user_id: int) -> dict:
    session = await get_session(session_id)
    if not session or session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Consultation not found")
    return session


async def _load_profile(session: dict, user_id: int) -> dict | None:
    """Family-aware: use the family member's profile if this session is for
    one of them, otherwise the account owner's own profile."""
    family_member_id = session.get("family_member_id")
    if family_member_id:
        member = await get_family_member(family_member_id)
        if member:
            return member  # already has a "name" key -> _build_system's per-member header
    return await get_user_profile_by_id(user_id)


@router.post("", response_model=ConsultationOut)
async def create_consultation(
    body: ConsultationCreate, user_id: int = Depends(get_current_user)
) -> ConsultationOut:
    family_member_id = body.family_member_id
    if family_member_id is not None:
        member = await get_family_member(family_member_id)
        if not member or member["owner_user_id"] != user_id:
            raise HTTPException(status_code=404, detail="Family member not found")

    session_id = await create_session(user_id, complaint="", family_member_id=family_member_id)
    return ConsultationOut(
        session_id=session_id,
        opening_prompt="Расскажите, что вас беспокоит — я задам несколько уточняющих вопросов.",
    )


@router.post("/{session_id}/messages", response_model=MessageOut)
async def send_message(
    session_id: int, body: MessageIn, user_id: int = Depends(get_current_user)
) -> MessageOut:
    session = await _own_session(session_id, user_id)
    if session["status"] != "active":
        raise HTTPException(status_code=409, detail="Consultation already completed")

    if not session["complaint"]:
        await set_session_complaint(session_id, body.text[:200])

    await add_message(session_id, "user", body.text)

    profile = await _load_profile(session, user_id)
    gender = profile.get("gender") if profile else None
    age_range = profile.get("age_range") if profile else None

    history = await get_session_messages(session_id)
    transcript = [{"role": role, "content": content} for role, content in history]
    prior_questions = sum(1 for role, _ in history if role == "assistant")

    ai = await analyze_symptoms(transcript, gender=gender, age_range=age_range, profile=profile)

    if ai.get("type") == "question" and prior_questions + 1 >= MAX_QUESTIONS:
        nudge = {
            "role": "user",
            "content": (
                "[Информации достаточно. Дай финальную рекомендацию "
                '(type="recommendation"), больше вопросов не задавай.]'
            ),
        }
        ai = await analyze_symptoms(
            transcript + [nudge], gender=gender, age_range=age_range, profile=profile
        )
        if ai.get("type") == "question":
            ai["type"] = "recommendation"

    # Persist the assistant's raw JSON turn so the next call rebuilds the exact
    # conversation the model saw.
    await add_message(session_id, "assistant", json.dumps(ai, ensure_ascii=False))

    text = ai.get("text", "")
    session_status = "active"
    if ai.get("type") in ("recommendation", "emergency"):
        if ai.get("type") == "emergency":
            text += EMERGENCY_NOTICE
        await update_session_summary(session_id, text[:480])
        session_status = "completed"

    return MessageOut(
        type=ai.get("type", "recommendation"),
        text=text,
        doctor=_doctor_out(ai.get("doctor_specialty")),
        bad=_bad_out(ai.get("bad_recommendation")),
        is_lifestyle=bool(ai.get("is_lifestyle")),
        session_status=session_status,
    )


@router.get("/{session_id}", response_model=ConsultationTranscriptOut)
async def get_consultation(
    session_id: int, user_id: int = Depends(get_current_user)
) -> ConsultationTranscriptOut:
    session = await _own_session(session_id, user_id)
    history = await get_session_messages(session_id)

    turns = []
    for role, content in history:
        if role == "assistant":
            try:
                text = json.loads(content).get("text", content)
            except json.JSONDecodeError:
                text = content
        else:
            text = content
        turns.append(TranscriptTurn(role=role, text=text))

    return ConsultationTranscriptOut(session_id=session_id, status=session["status"], turns=turns)
