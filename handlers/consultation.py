import base64
import logging
from io import BytesIO

try:
    import fitz  # PyMuPDF
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ai.assistant import (
    analyze_symptoms, analyze_photo, analyze_lab_text,
    build_recommendation_message, AGE_RU, GENDER_RU,
)
from config import MAX_QUESTIONS
from database.db import (
    add_message,
    create_session,
    get_family_member,
    get_family_members,
    get_or_create_user,
    get_user_profile,
    update_session_summary,
)
from keyboards.keyboards import consult_for_keyboard, main_menu, remove_keyboard

router = Router()

EMERGENCY_MSG = (
    "🚨 <b>Внимание!</b>\n\n"
    "Описанные симптомы могут требовать <b>немедленной медицинской помощи</b>.\n\n"
    "📞 <b>Позвоните прямо сейчас:</b>\n"
    "• <b>112</b> — единый номер экстренных служб\n"
    "• <b>103</b> — скорая помощь\n\n"
    "<i>Не ждите — обратитесь за помощью прямо сейчас!</i>"
)


_PDF_MIME = "application/pdf"


class Consultation(StatesGroup):
    active = State()


# ── helpers ────────────────────────────────────────────────────────────────

async def _force_recommendation(
    messages: list[dict],
    gender: str | None,
    age_range: str | None,
    profile: dict | None = None,
) -> dict:
    hint = {"role": "user", "content": "Это все мои симптомы. Пожалуйста, дай рекомендации."}
    return await analyze_symptoms(messages + [hint], gender=gender, age_range=age_range, profile=profile)


def _profile_line(gender: str | None, age_range: str | None) -> str:
    """Human-readable one-liner for the session summary."""
    parts = []
    if gender:
        parts.append(GENDER_RU.get(gender, gender))
    if age_range:
        parts.append(AGE_RU.get(age_range, age_range))
    return ", ".join(parts) if parts else "не указано"


# ── handlers ───────────────────────────────────────────────────────────────

async def _init_for_self(message: Message, state: FSMContext) -> None:
    await state.set_state(Consultation.active)
    await state.update_data(
        messages=[], question_count=0, session_id=None, user_id=None,
        gender=None, age_range=None, profile=None, profile_ready=False,
    )
    await message.answer(
        "Расскажите, что вас беспокоит? Опишите симптомы в свободной форме 👇",
        reply_markup=remove_keyboard(),
    )


async def _init_for_member(message: Message, state: FSMContext, member: dict) -> None:
    await state.set_state(Consultation.active)
    await state.update_data(
        messages=[], question_count=0, session_id=None, user_id=None,
        gender=member.get("gender"), age_range=member.get("age_range"),
        profile=member, profile_ready=True,
    )
    await message.answer(
        f"Консультирую <b>{member['name']}</b>. Расскажите, что беспокоит? 👇",
        parse_mode="HTML",
        reply_markup=remove_keyboard(),
    )


@router.message(F.text == "🩺 Анализ симптомов")
async def start_consultation(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = await get_or_create_user(message.from_user.id, message.from_user.username)
    members = await get_family_members(user_id)
    if members:
        await message.answer("Для кого консультация?", reply_markup=consult_for_keyboard(members))
    else:
        await _init_for_self(message, state)


@router.callback_query(F.data.startswith("consult_for:"))
async def cb_consult_for(call: CallbackQuery, state: FSMContext) -> None:
    parts = call.data.split(":")
    await call.message.edit_reply_markup(reply_markup=None)
    if parts[1] == "self":
        await _init_for_self(call.message, state)
    else:
        member = await get_family_member(int(parts[2]))
        if not member:
            await call.answer("Профиль не найден", show_alert=True)
            return
        await _init_for_member(call.message, state, member)
    await call.answer()


@router.message(Consultation.active, F.text)
async def handle_symptom(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    messages: list[dict] = data.get("messages", [])
    question_count: int = data.get("question_count", 0)
    session_id: int | None = data.get("session_id")

    user_text = message.text.strip()

    # Create DB session on first message + load profile
    if session_id is None:
        user_id = await get_or_create_user(message.from_user.id, message.from_user.username)
        session_id = await create_session(user_id, user_text)

        if data.get("profile_ready"):
            # Consulting for a family member — profile pre-set, don't overwrite
            profile   = data.get("profile")
            gender    = data.get("gender")
            age_range = data.get("age_range")
        else:
            profile   = await get_user_profile(message.from_user.id)
            gender    = profile["gender"]    if profile else None
            age_range = profile["age_range"] if profile else None

        await state.update_data(
            session_id=session_id, user_id=user_id,
            gender=gender, age_range=age_range, profile=profile,
        )
    else:
        gender    = data.get("gender")
        age_range = data.get("age_range")
        profile   = data.get("profile")

    messages.append({"role": "user", "content": user_text})
    await add_message(session_id, "user", user_text)

    # If question limit reached — force recommendation
    if question_count >= MAX_QUESTIONS:
        ai = await _force_recommendation(messages, gender, age_range, profile)
    else:
        ai = await analyze_symptoms(messages, gender=gender, age_range=age_range, profile=profile)

    ai_type = ai.get("type", "recommendation")

    # ── EMERGENCY ──────────────────────────────────────────────────────────
    if ai_type == "emergency":
        await add_message(session_id, "assistant", EMERGENCY_MSG)
        await update_session_summary(session_id, "Экстренная ситуация — пользователь направлен в скорую.")
        await state.clear()
        await message.answer(EMERGENCY_MSG, parse_mode="HTML", reply_markup=main_menu())
        return

    # ── QUESTION ───────────────────────────────────────────────────────────
    if ai_type == "question" and question_count < MAX_QUESTIONS:
        reply = ai.get("text", "")
        messages.append({"role": "assistant", "content": reply})
        await add_message(session_id, "assistant", reply)
        await state.update_data(messages=messages, question_count=question_count + 1)
        await message.answer(reply)
        return

    # ── RECOMMENDATION ─────────────────────────────────────────────────────
    if ai_type == "question":
        ai = await _force_recommendation(messages, gender, age_range)

    final_text = build_recommendation_message(ai)
    await add_message(session_id, "assistant", final_text)

    # Summary includes patient profile for the doctor
    summary = f"[{_profile_line(gender, age_range)}] {(ai.get('text') or '')[:480]}"
    await update_session_summary(session_id, summary)

    await state.clear()
    await message.answer(
        final_text,
        parse_mode="HTML",
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )


@router.message(
    Consultation.active,
    ~F.text,
    ~F.photo,
    ~(F.document & (F.document.mime_type == _PDF_MIME)),
)
async def handle_non_text(message: Message) -> None:
    await message.answer("Пожалуйста, опишите симптомы текстом, отправьте фото или PDF с анализами.")


# ── Анализ фото ────────────────────────────────────────────────────────────

async def _process_photo(message: Message, state: FSMContext) -> None:
    """Shared logic: download photo, run vision AI, send result."""
    await message.answer("🔍 Анализирую изображение, подождите немного…")

    # Download photo
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    buf = BytesIO()
    await message.bot.download_file(file.file_path, destination=buf)
    buf.seek(0)
    raw_bytes = buf.read()
    image_b64 = base64.b64encode(raw_bytes).decode()
    logging.info(f"Photo downloaded: {len(raw_bytes)} bytes, b64 len={len(image_b64)}")

    # Load profile for context
    data = await state.get_data()
    gender    = data.get("gender")
    age_range = data.get("age_range")

    if gender is None:
        from database.db import get_user_profile
        profile = await get_user_profile(message.from_user.id)
        if profile:
            gender    = profile["gender"]
            age_range = profile["age_range"]

    ai = await analyze_photo(image_b64, gender=gender, age_range=age_range)

    # Страховка: для медицинских документов врач обязателен
    if not ai.get("doctor_specialty"):
        ai["doctor_specialty"] = "therapist"

    final_text = build_recommendation_message(ai)

    await state.clear()
    await message.answer(
        final_text,
        parse_mode="HTML",
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )


@router.message(Consultation.active, F.photo)
async def handle_photo_in_consultation(message: Message, state: FSMContext) -> None:
    await _process_photo(message, state)


@router.message(StateFilter(None), F.photo)
async def handle_photo_direct(message: Message, state: FSMContext) -> None:
    await _process_photo(message, state)


# ── Анализ PDF ─────────────────────────────────────────────────────────────

async def _process_pdf(message: Message, state: FSMContext) -> None:
    """Download PDF, extract text (or render first page), analyze lab results."""
    await message.answer("📄 Читаю PDF, подождите немного…")

    # Download file
    file = await message.bot.get_file(message.document.file_id)
    buf = BytesIO()
    await message.bot.download_file(file.file_path, destination=buf)
    pdf_bytes = buf.getvalue()

    # Load profile for context
    data = await state.get_data()
    gender    = data.get("gender")
    age_range = data.get("age_range")
    if gender is None:
        profile = await get_user_profile(message.from_user.id)
        if profile:
            gender    = profile["gender"]
            age_range = profile["age_range"]

    if not _FITZ_AVAILABLE:
        await message.answer(
            "😔 Библиотека для чтения PDF не установлена на сервере.\n"
            "Пожалуйста, сфотографируйте документ и отправьте фото — так тоже работает.",
            reply_markup=main_menu(),
        )
        await state.clear()
        return

    # Try text extraction first (works for 99% of clinic PDFs)
    text = ""
    pdf_bytes_for_render = pdf_bytes
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()
    except Exception as e:
        logging.error(f"PDF text extraction error: {e}")

    text = text.strip()

    if len(text) >= 50:
        logging.info(f"PDF text extracted: {len(text)} chars")
        ai = await analyze_lab_text(text, gender=gender, age_range=age_range)
    else:
        logging.info("PDF has no text, falling back to vision model")
        try:
            with fitz.open(stream=pdf_bytes_for_render, filetype="pdf") as doc:
                pix = doc[0].get_pixmap(dpi=150)
                img_bytes = pix.tobytes("jpeg")
            image_b64 = base64.b64encode(img_bytes).decode()
            ai = await analyze_photo(image_b64, gender=gender, age_range=age_range)
        except Exception as e:
            logging.error(f"PDF render error: {e}")
            await message.answer(
                "😔 Не удалось прочитать этот PDF.\n"
                "Попробуйте сделать фото документа и отправить его — так тоже работает.",
                reply_markup=main_menu(),
            )
            await state.clear()
            return

    if not ai.get("doctor_specialty"):
        ai["doctor_specialty"] = "therapist"

    final_text = build_recommendation_message(ai)
    await state.clear()
    await message.answer(
        final_text,
        parse_mode="HTML",
        reply_markup=main_menu(),
        disable_web_page_preview=True,
    )


@router.message(Consultation.active, F.document, F.document.mime_type == _PDF_MIME)
async def handle_pdf_in_consultation(message: Message, state: FSMContext) -> None:
    await _process_pdf(message, state)


@router.message(StateFilter(None), F.document, F.document.mime_type == _PDF_MIME)
async def handle_pdf_direct(message: Message, state: FSMContext) -> None:
    await _process_pdf(message, state)


# ── Auto-start: пользователь пишет симптомы без нажатия кнопки ────────────

# Тексты кнопок и команд, которые НЕ должны запускать консультацию
_RESERVED = {
    "🩺 Анализ симптомов",
    "💊 Подбор БАД",
    "📊 Мой трекер",
    "📔 Дневник",
    "📋 История",
    "👨‍👩‍👧 Семья",
    "⚙️ Мой профиль",
}

@router.message(
    StateFilter(None),        # пользователь не в каком-либо состоянии
    F.text,
    ~F.text.in_(_RESERVED),   # не нажал кнопку меню
)
async def auto_start(message: Message, state: FSMContext) -> None:
    """Если пользователь пишет сразу — автоматически начинаем консультацию."""
    # Инициализируем состояние как будто нажал кнопку
    await state.set_state(Consultation.active)
    await state.update_data(
        messages=[], question_count=0,
        session_id=None, user_id=None,
        gender=None, age_range=None,
    )
    # Сразу обрабатываем сообщение как первую жалобу
    await handle_symptom(message, state)
