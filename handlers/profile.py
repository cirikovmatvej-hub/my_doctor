"""
Profile onboarding — gender/age + 10-question health questionnaire.

Question flow:
  Female (10 вопросов): chronic → allergies → medications → pregnancy →
                        surgeries → hereditary → smoking → alcohol → activity → height_weight
  Male   (9 вопросов):  chronic → allergies → medications →
                        surgeries → hereditary → smoking → alcohol → activity → height_weight
"""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database.db import (
    get_or_create_user, get_user_profile,
    set_health_field, update_user_profile,
)

# ── Inline labels (for profile summary display) ────────────────────────────
from ai.assistant import SMOKING_RU, ALCOHOL_RU, ACTIVITY_RU, PREGNANCY_RU
from keyboards.keyboards import (
    activity_keyboard, age_keyboard, alcohol_keyboard,
    gender_keyboard, main_menu, pregnancy_keyboard,
    skip_keyboard, smoking_keyboard, update_profile_keyboard,
)

router = Router()

# ── Labels ─────────────────────────────────────────────────────────────────

GENDER_LABELS = {"male": "Мужской", "female": "Женский"}
AGE_LABELS = {
    "under_18": "до 18 лет", "18_30": "18–30 лет",
    "31_45": "31–45 лет",    "46_60": "46–60 лет", "60_plus": "60+ лет",
}
SMOKING_LABELS = {
    "never": "Не курю", "former": "Бросил(а)",
    "light": "Иногда",  "heavy": "Регулярно",
}
ALCOHOL_LABELS = {
    "never": "Не употребляю", "rarely": "Редко",
    "moderate": "Умеренно",   "frequent": "Часто",
}
ACTIVITY_LABELS = {
    "sedentary": "Сидячий", "light": "Лёгкая",
    "moderate":  "Умеренная", "high": "Высокая",
}
PREGNANCY_LABELS = {
    "pregnant": "🤰 Беременность", "lactating": "🤱 Лактация", "no": "Нет",
}


# ── States ─────────────────────────────────────────────────────────────────

class ProfileStates(StatesGroup):
    waiting_gender      = State()
    waiting_age         = State()
    waiting_chronic     = State()
    waiting_allergies   = State()
    waiting_medications = State()
    waiting_pregnancy   = State()
    waiting_surgeries   = State()
    waiting_hereditary  = State()
    waiting_smoking     = State()
    waiting_alcohol     = State()
    waiting_activity    = State()
    waiting_height      = State()


# ── Question numbering helper ──────────────────────────────────────────────

def _q(num_female: int, gender: str) -> str:
    """Return 'Q/Total' string adjusted for gender (males skip pregnancy)."""
    total = 10 if gender == "female" else 9
    num = num_female if gender == "female" else (num_female - 1 if num_female > 4 else num_female)
    return f"({num}/{total})"


# ── Entry points (called externally) ──────────────────────────────────────

async def ask_gender(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileStates.waiting_gender)
    await message.answer(
        "👤 Прежде чем начать — несколько коротких вопросов.\n\n"
        "<b>Укажите ваш пол:</b>",
        parse_mode="HTML",
        reply_markup=gender_keyboard(),
    )


async def ask_chronic_diseases(message: Message, state: FSMContext) -> None:
    """Entry point for health questionnaire (after gender/age are already set)."""
    profile = await get_user_profile(message.chat.id)
    gender = (profile or {}).get("gender", "female")
    data = await state.get_data()
    if not data.get("gender"):
        await state.update_data(gender=gender)

    await state.set_state(ProfileStates.waiting_chronic)
    await message.answer(
        "🏥 <b>Анкета здоровья</b>\n"
        "<i>Заполняется один раз. Помогает давать безопасные и точные рекомендации.</i>\n\n"
        f"1️⃣ <b>Хронические заболевания?</b> {_q(1, gender)}\n"
        "<i>Диабет, гипертония, заболевания почек, сердца, щитовидной железы…</i>\n\n"
        "Напишите или нажмите «Нет».",
        parse_mode="HTML",
        reply_markup=skip_keyboard("chronic:no"),
    )


# ── Gender ─────────────────────────────────────────────────────────────────

@router.callback_query(ProfileStates.waiting_gender, F.data.startswith("gender:"))
async def cb_gender(call: CallbackQuery, state: FSMContext) -> None:
    gender = call.data.split(":")[1]
    await state.update_data(gender=gender)
    await state.set_state(ProfileStates.waiting_age)
    await call.message.edit_text(
        f"👤 Пол: <b>{GENDER_LABELS[gender]}</b>\n\n"
        "📅 <b>Укажите ваш возраст:</b>",
        parse_mode="HTML",
        reply_markup=age_keyboard(),
    )
    await call.answer()


# ── Age ────────────────────────────────────────────────────────────────────

@router.callback_query(ProfileStates.waiting_age, F.data.startswith("age:"))
async def cb_age(call: CallbackQuery, state: FSMContext) -> None:
    age_range = call.data.split(":")[1]
    data = await state.get_data()
    gender = data["gender"]
    await get_or_create_user(call.from_user.id, call.from_user.username)
    await update_user_profile(call.from_user.id, gender, age_range)
    await state.update_data(age_range=age_range)
    await call.message.edit_text(
        f"👤 Пол: <b>{GENDER_LABELS[gender]}</b>\n"
        f"📅 Возраст: <b>{AGE_LABELS[age_range]}</b>\n\n"
        "✅ Основные данные сохранены!",
        parse_mode="HTML",
    )
    await ask_chronic_diseases(call.message, state)
    await call.answer()


# ── Q1 Chronic diseases ────────────────────────────────────────────────────

@router.message(ProfileStates.waiting_chronic)
async def msg_chronic(message: Message, state: FSMContext) -> None:
    await set_health_field(message.from_user.id, "chronic_diseases", message.text.strip())
    await _ask_allergies(message, state)

@router.callback_query(ProfileStates.waiting_chronic, F.data == "chronic:no")
async def cb_chronic_no(call: CallbackQuery, state: FSMContext) -> None:
    await set_health_field(call.from_user.id, "chronic_diseases", "нет")
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_allergies(call.message, state)
    await call.answer()


async def _ask_allergies(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    gender = data.get("gender", "female")
    await state.set_state(ProfileStates.waiting_allergies)
    await message.answer(
        f"2️⃣ <b>Аллергии?</b> {_q(2, gender)}\n"
        "<i>Лекарственные, пищевые, на пыльцу, латекс…</i>\n\n"
        "Напишите или нажмите «Нет».",
        parse_mode="HTML",
        reply_markup=skip_keyboard("allergies:no"),
    )


# ── Q2 Allergies ───────────────────────────────────────────────────────────

@router.message(ProfileStates.waiting_allergies)
async def msg_allergies(message: Message, state: FSMContext) -> None:
    await set_health_field(message.from_user.id, "allergies", message.text.strip())
    await _ask_medications(message, state)

@router.callback_query(ProfileStates.waiting_allergies, F.data == "allergies:no")
async def cb_allergies_no(call: CallbackQuery, state: FSMContext) -> None:
    await set_health_field(call.from_user.id, "allergies", "нет")
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_medications(call.message, state)
    await call.answer()


async def _ask_medications(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    gender = data.get("gender", "female")
    await state.set_state(ProfileStates.waiting_medications)
    await message.answer(
        f"3️⃣ <b>Постоянно принимаемые лекарства?</b> {_q(3, gender)}\n"
        "<i>Гормоны, антикоагулянты, антидепрессанты, антибиотики…</i>\n\n"
        "Напишите или нажмите «Нет».",
        parse_mode="HTML",
        reply_markup=skip_keyboard("medications:no"),
    )


# ── Q3 Medications ─────────────────────────────────────────────────────────

@router.message(ProfileStates.waiting_medications)
async def msg_medications(message: Message, state: FSMContext) -> None:
    await set_health_field(message.from_user.id, "medications", message.text.strip())
    data = await state.get_data()
    if data.get("gender") == "male":
        await _ask_surgeries(message, state)
    else:
        await _ask_pregnancy(message, state)

@router.callback_query(ProfileStates.waiting_medications, F.data == "medications:no")
async def cb_medications_no(call: CallbackQuery, state: FSMContext) -> None:
    await set_health_field(call.from_user.id, "medications", "нет")
    await call.message.edit_reply_markup(reply_markup=None)
    data = await state.get_data()
    if data.get("gender") == "male":
        await _ask_surgeries(call.message, state)
    else:
        await _ask_pregnancy(call.message, state)
    await call.answer()


# ── Q4 Pregnancy (female only) ─────────────────────────────────────────────

async def _ask_pregnancy(message: Message, state: FSMContext) -> None:
    await state.set_state(ProfileStates.waiting_pregnancy)
    await message.answer(
        "4️⃣ <b>Беременность или лактация?</b> (4/10)",
        parse_mode="HTML",
        reply_markup=pregnancy_keyboard(),
    )

@router.callback_query(ProfileStates.waiting_pregnancy, F.data.startswith("pregnancy:"))
async def cb_pregnancy(call: CallbackQuery, state: FSMContext) -> None:
    value = call.data.split(":")[1]
    await set_health_field(call.from_user.id, "pregnancy", value)
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_surgeries(call.message, state)
    await call.answer()


# ── Q5 Past surgeries ──────────────────────────────────────────────────────

async def _ask_surgeries(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    gender = data.get("gender", "female")
    await state.set_state(ProfileStates.waiting_surgeries)
    await message.answer(
        f"5️⃣ <b>Перенесённые операции или госпитализации?</b> {_q(5, gender)}\n"
        "<i>Операции на сердце, ЖКТ, суставах; серьёзные травмы…</i>\n\n"
        "Напишите или нажмите «Нет».",
        parse_mode="HTML",
        reply_markup=skip_keyboard("surgeries:no"),
    )

@router.message(ProfileStates.waiting_surgeries)
async def msg_surgeries(message: Message, state: FSMContext) -> None:
    await set_health_field(message.from_user.id, "past_surgeries", message.text.strip())
    await _ask_hereditary(message, state)

@router.callback_query(ProfileStates.waiting_surgeries, F.data == "surgeries:no")
async def cb_surgeries_no(call: CallbackQuery, state: FSMContext) -> None:
    await set_health_field(call.from_user.id, "past_surgeries", "нет")
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_hereditary(call.message, state)
    await call.answer()


# ── Q6 Hereditary diseases ─────────────────────────────────────────────────

async def _ask_hereditary(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    gender = data.get("gender", "female")
    await state.set_state(ProfileStates.waiting_hereditary)
    await message.answer(
        f"6️⃣ <b>Наследственные заболевания в семье?</b> {_q(6, gender)}\n"
        "<i>Диабет, рак, болезни сердца, инсульт у близких родственников…</i>\n\n"
        "Напишите или нажмите «Нет».",
        parse_mode="HTML",
        reply_markup=skip_keyboard("hereditary:no"),
    )

@router.message(ProfileStates.waiting_hereditary)
async def msg_hereditary(message: Message, state: FSMContext) -> None:
    await set_health_field(message.from_user.id, "hereditary_diseases", message.text.strip())
    await _ask_smoking(message, state)

@router.callback_query(ProfileStates.waiting_hereditary, F.data == "hereditary:no")
async def cb_hereditary_no(call: CallbackQuery, state: FSMContext) -> None:
    await set_health_field(call.from_user.id, "hereditary_diseases", "нет")
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_smoking(call.message, state)
    await call.answer()


# ── Q7 Smoking ─────────────────────────────────────────────────────────────

async def _ask_smoking(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    gender = data.get("gender", "female")
    await state.set_state(ProfileStates.waiting_smoking)
    await message.answer(
        f"7️⃣ <b>Курение?</b> {_q(7, gender)}",
        parse_mode="HTML",
        reply_markup=smoking_keyboard(),
    )

@router.callback_query(ProfileStates.waiting_smoking, F.data.startswith("smoking:"))
async def cb_smoking(call: CallbackQuery, state: FSMContext) -> None:
    value = call.data.split(":")[1]
    await set_health_field(call.from_user.id, "smoking", value)
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_alcohol(call.message, state)
    await call.answer()


# ── Q8 Alcohol ─────────────────────────────────────────────────────────────

async def _ask_alcohol(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    gender = data.get("gender", "female")
    await state.set_state(ProfileStates.waiting_alcohol)
    await message.answer(
        f"8️⃣ <b>Алкоголь?</b> {_q(8, gender)}",
        parse_mode="HTML",
        reply_markup=alcohol_keyboard(),
    )

@router.callback_query(ProfileStates.waiting_alcohol, F.data.startswith("alcohol:"))
async def cb_alcohol(call: CallbackQuery, state: FSMContext) -> None:
    value = call.data.split(":")[1]
    await set_health_field(call.from_user.id, "alcohol", value)
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_activity(call.message, state)
    await call.answer()


# ── Q9 Physical activity ───────────────────────────────────────────────────

async def _ask_activity(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    gender = data.get("gender", "female")
    await state.set_state(ProfileStates.waiting_activity)
    await message.answer(
        f"9️⃣ <b>Уровень физической активности?</b> {_q(9, gender)}",
        parse_mode="HTML",
        reply_markup=activity_keyboard(),
    )

@router.callback_query(ProfileStates.waiting_activity, F.data.startswith("activity:"))
async def cb_activity(call: CallbackQuery, state: FSMContext) -> None:
    value = call.data.split(":")[1]
    await set_health_field(call.from_user.id, "physical_activity", value)
    await call.message.edit_reply_markup(reply_markup=None)
    await _ask_height_weight(call.message, state)
    await call.answer()


# ── Q10 Height / weight ────────────────────────────────────────────────────

async def _ask_height_weight(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    gender = data.get("gender", "female")
    await state.set_state(ProfileStates.waiting_height)
    await message.answer(
        f"🔟 <b>Рост и вес?</b> {_q(10, gender)}\n"
        "<i>Например: 175 / 70</i>\n\n"
        "Напишите или нажмите «Пропустить».",
        parse_mode="HTML",
        reply_markup=skip_keyboard("height:skip"),
    )

@router.message(ProfileStates.waiting_height)
async def msg_height(message: Message, state: FSMContext) -> None:
    await set_health_field(message.from_user.id, "height_weight", message.text.strip())
    await _finish(message, state)

@router.callback_query(ProfileStates.waiting_height, F.data == "height:skip")
async def cb_height_skip(call: CallbackQuery, state: FSMContext) -> None:
    await set_health_field(call.from_user.id, "height_weight", "не указано")
    await call.message.edit_reply_markup(reply_markup=None)
    await _finish(call.message, state)
    await call.answer()


# ── Finish ─────────────────────────────────────────────────────────────────

async def _finish(message: Message, state: FSMContext) -> None:
    """Mark onboarding complete and show main menu."""
    await set_health_field(message.chat.id, "onboarding_done", "1")
    await state.clear()
    await message.answer(
        "✅ <b>Анкета здоровья заполнена!</b>\n\n"
        "Теперь мои рекомендации будут максимально точными и безопасными для вас.\n\n"
        "<i>Обновить данные можно в любое время — кнопка «⚙️ Мой профиль» в меню.</i>",
        parse_mode="HTML",
    )
    await message.answer("Выберите действие 👇", reply_markup=main_menu())


# ── "⚙️ Мой профиль" — просмотр и обновление ─────────────────────────────

def _profile_summary(profile: dict) -> str:
    """Build a human-readable profile card."""
    def _v(key: str) -> str:
        v = (profile.get(key) or "").strip()
        return v if v and v not in ("нет", "не указано") else "—"

    gender = GENDER_LABELS.get(profile.get("gender") or "", "—")
    age    = AGE_LABELS.get(profile.get("age_range") or "", "—")
    preg   = PREGNANCY_RU.get(profile.get("pregnancy") or "", "—")
    smoke  = SMOKING_RU.get(profile.get("smoking") or "", "—")
    alc    = ALCOHOL_RU.get(profile.get("alcohol") or "", "—")
    act    = ACTIVITY_RU.get(profile.get("physical_activity") or "", "—")

    lines = [
        "👤 <b>Ваш профиль здоровья</b>\n",
        f"Пол: {gender}   Возраст: {age}",
        "",
        f"🏥 Хронические болезни:  {_v('chronic_diseases')}",
        f"⚠️ Аллергии:             {_v('allergies')}",
        f"💊 Лекарства:            {_v('medications')}",
    ]
    if profile.get("gender") == "female":
        lines.append(f"🤰 Беременность/лактация:{preg}")
    lines += [
        f"🔪 Операции:             {_v('past_surgeries')}",
        f"🧬 Наследственность:     {_v('hereditary_diseases')}",
        f"🚬 Курение:              {smoke}",
        f"🍷 Алкоголь:             {alc}",
        f"🏃 Активность:           {act}",
        f"⚖️ Рост/вес:             {_v('height_weight')}",
    ]
    return "\n".join(lines)


@router.message(F.text == "⚙️ Мой профиль")
async def cmd_my_profile(message: Message, state: FSMContext) -> None:
    await state.clear()
    profile = await get_user_profile(message.from_user.id)

    if not profile or not profile.get("onboarding_done"):
        await message.answer(
            "📋 Анкета здоровья ещё не заполнена.\n\nДавайте заполним её сейчас!",
        )
        await ask_chronic_diseases(message, state)
        return

    await message.answer(
        _profile_summary(profile),
        parse_mode="HTML",
        reply_markup=update_profile_keyboard(),
    )


@router.callback_query(F.data == "profile:update")
async def cb_profile_update(call: CallbackQuery, state: FSMContext) -> None:
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer()
    # Reset onboarding flag so questionnaire reruns
    await set_health_field(call.from_user.id, "onboarding_done", "0")
    await ask_chronic_diseases(call.message, state)
