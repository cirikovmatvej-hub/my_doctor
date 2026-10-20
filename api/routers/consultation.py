"""
Symptom consultation — text-only for Phase 1 (photo/PDF deferred).

Stateless by design: unlike the bot (which keeps the Groq conversation in
aiogram FSM memory as an optimization), every turn here rebuilds the full
transcript from the `messages` table. The assistant's raw JSON reply is
persisted as-is so the next call reconstructs exactly what the model saw.
"""
import asyncio
import json
import re
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException

from ai.assistant import RECOMMENDATION_DISCLAIMER, analyze_symptoms
from api.deps import get_current_user
from api.schemas import (
    BadOut, ConsultationCreate, ConsultationOut, ConsultationTranscriptOut, DoctorOut,
    MessageIn, MessageOut, TranscriptTurn,
)
from config import MAX_QUESTIONS, SHOW_DOCTOR_RECOMMENDATIONS, WEB_DAILY_MESSAGE_LIMIT
from data.resources import BAD_DETAILS, BADS, DOCTORS
from database.db import (
    add_messages, count_recent_user_messages, create_session, get_family_member, get_session, get_session_messages,
    get_user_profile_by_id, set_session_complaint, update_session_summary,
)

router = APIRouter(prefix="/consultations", tags=["consultation"])

# Same wording as the bot's EMERGENCY_MSG, as plain text. Like the bot, the app
# always shows this for an emergency and never whatever the model wrote — a
# life-safety message shouldn't vary between runs.
EMERGENCY_TEXT = (
    "Описанные симптомы могут требовать немедленной медицинской помощи.\n\n"
    "Позвоните прямо сейчас:\n"
    "• 112 — единый номер экстренных служб\n"
    "• 103 — скорая помощь\n\n"
    "Не ждите — обратитесь за помощью прямо сейчас!"
)
EMERGENCY_SUMMARY = "Экстренная ситуация — пользователь направлен в скорую."


# The bot builds this as HTML for Telegram; the app renders plain text.
DISCLAIMER = re.sub(r"</?i>", "", RECOMMENDATION_DISCLAIMER)


def _doctor_out(specialty: str | None) -> DoctorOut | None:
    # Same switch the bot's build_recommendation_message() honors — while
    # doctor recommendations are turned off there, the app must not show them.
    if not SHOW_DOCTOR_RECOMMENDATIONS:
        return None
    if not specialty or specialty not in DOCTORS:
        return None
    d = DOCTORS[specialty]
    return DoctorOut(specialty=specialty, name=d["name"], url=d["url"])


def _bad_out(key: str | None) -> BadOut | None:
    if not key or key not in BADS:
        return None
    b = BADS[key]
    d = BAD_DETAILS[key]
    return BadOut(
        key=key, name=b["name"], url=b["url"], description=b["description"],
        course_days=d["course_days"], daily_doses=d["daily_doses"], default_times=d["default_times"],
    )


# One in-flight model turn per session. A double-tap or client retry would
# otherwise run two LLM calls over the same history and persist two replies.
# Per-process: the API runs as a single uvicorn process (the bot is separate).
_session_locks: dict[int, asyncio.Lock] = {}
_session_lock_users: defaultdict[int, int] = defaultdict(int)  # holders + waiters, so a lock is dropped only when idle


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
    await _own_session(session_id, user_id)  # 404 early, without creating a lock for foreign ids
    lock = _session_locks.setdefault(session_id, asyncio.Lock())
    _session_lock_users[session_id] += 1
    try:
        async with lock:
            # Re-read under the lock: a concurrent turn may have just completed it.
            session = await _own_session(session_id, user_id)
            return await _answer_message(session_id, session, body, user_id)
    finally:
        _session_lock_users[session_id] -= 1
        if _session_lock_users[session_id] == 0:
            del _session_lock_users[session_id]
            del _session_locks[session_id]


async def _answer_message(
    session_id: int, session: dict, body: MessageIn, user_id: int
) -> MessageOut:
    if session["status"] != "active":
        raise HTTPException(status_code=409, detail="Consultation already completed")

    # Every turn is a paid model call and the web app is public, so one
    # account can't send unlimited messages. Rolling 24h, counted from saved turns.
    if await count_recent_user_messages(user_id) >= WEB_DAILY_MESSAGE_LIMIT:
        raise HTTPException(
            status_code=429, detail="Достигнут дневной лимит сообщений. Попробуйте завтра.",
        )

    if not session["complaint"]:
        await set_session_complaint(session_id, body.text[:200])

    profile = await _load_profile(session, user_id)
    gender = profile.get("gender") if profile else None
    age_range = profile.get("age_range") if profile else None

    # The new user message is only saved once the model has actually answered —
    # if the call fails the client retries the same text, which must not leave
    # a duplicate behind.
    history = await get_session_messages(session_id)
    transcript = [{"role": role, "content": content} for role, content in history]
    transcript.append({"role": "user", "content": body.text})
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

    # A failed model call comes back as a canned "technical error, see a
    # therapist" recommendation. The bot shows it; here it must not be stored,
    # end the consultation, or read as advice — tell the client to try again.
    if ai.get("_technical_error"):
        raise HTTPException(
            status_code=503, detail="Не удалось получить ответ. Попробуйте отправить сообщение ещё раз."
        )

    if ai.get("type") == "emergency":
        ai["text"] = EMERGENCY_TEXT

    # Persist the user turn and the assistant's raw JSON reply together, so the
    # next call rebuilds the exact conversation the model saw (and the
    # transcript shows what the user saw) — never a half-saved turn. False
    # means the session vanished mid-call (account deleted).
    if not await add_messages(session_id, [
        ("user", body.text),
        ("assistant", json.dumps(ai, ensure_ascii=False)),
    ]):
        raise HTTPException(status_code=404, detail="Consultation not found")

    text = ai.get("text", "")
    session_status = "active"
    if ai.get("type") in ("recommendation", "emergency"):
        # Only schedule the "how are you feeling?" check-in when the model
        # asked for one — the bot does the same; an emergency never gets one.
        await update_session_summary(
            session_id,
            EMERGENCY_SUMMARY if ai.get("type") == "emergency" else text[:480],
            schedule_followup=ai.get("type") == "recommendation" and bool(ai.get("needs_followup")),
        )
        session_status = "completed"

    bad = _bad_out(ai.get("bad_recommendation"))
    general_supplement = ai.get("general_supplement_suggestion") or None
    is_recommendation = ai.get("type", "recommendation") == "recommendation"

    # Mirrors build_recommendation_message(): grounded safety warnings ride
    # along with whichever supplement they're about, and the disclaimer is
    # attached in code, never left to the model.
    safety_warnings: list[str] = []
    if is_recommendation:
        if bad:
            safety_warnings += ai.get("_grounded_safety_warnings") or []
        if general_supplement:
            safety_warnings += ai.get("_grounded_general_safety_warnings") or []

    return MessageOut(
        type=ai.get("type", "recommendation"),
        text=text,
        doctor=_doctor_out(ai.get("doctor_specialty")),
        bad=bad,
        is_lifestyle=bool(ai.get("is_lifestyle")),
        session_status=session_status,
        general_supplement=general_supplement if is_recommendation else None,
        safety_warnings=safety_warnings,
        disclaimer=DISCLAIMER if is_recommendation else None,
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
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = None
            text = parsed.get("text", content) if isinstance(parsed, dict) else content
        else:
            text = content
        turns.append(TranscriptTurn(role=role, text=text))

    return ConsultationTranscriptOut(session_id=session_id, status=session["status"], turns=turns)
