"""
Wellbeing Diary — daily self-assessment (sleep / energy / stress / BADs taken).

Flow:
  "📔 Дневник" → check today's entry
    → already filled: show today's summary + last 7 days chart
    → not filled: sleep rating → energy rating → stress rating → BADs taken → save
"""
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database.db import (
    get_diary_entries,
    get_or_create_user,
    save_diary_entry,
)
from keyboards.keyboards import bads_taken_keyboard, main_menu, rating_keyboard

router = Router()


# ── States ─────────────────────────────────────────────────────────────────

class DiaryState(StatesGroup):
    sleep  = State()
    energy = State()
    stress = State()
    bads   = State()


# ── Helpers ────────────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _bar(value: int, max_val: int = 5) -> str:
    filled = round(value / max_val * 5)
    return "█" * filled + "░" * (5 - filled)


def _entry_summary(entries: list) -> str:
    if not entries:
        return ""
    lines = ["📊 <b>Последние записи:</b>\n"]
    for entry_date, sleep, energy, stress, bads, _ in entries:
        bads_icon = "✅" if bads else "❌"
        lines.append(
            f"<b>{entry_date}</b>  "
            f"😴{_bar(sleep)} ⚡{_bar(energy)} 😤{_bar(stress)}  БАД:{bads_icon}"
        )
    return "\n".join(lines)


# ── Entry point ────────────────────────────────────────────────────────────

@router.message(F.text == "📔 Дневник")
async def cmd_diary(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = await get_or_create_user(message.from_user.id, message.from_user.username)
    today = _today()

    entries = await get_diary_entries(user_id, limit=7)

    # Check if today's entry already exists
    already_today = entries and entries[0][0] == today

    if already_today:
        summary = _entry_summary(entries)
        await message.answer(
            f"📔 <b>Дневник самочувствия</b>\n\n"
            f"Запись на сегодня уже есть ✅\n\n{summary}",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        return

    # Start new entry
    await state.set_state(DiaryState.sleep)
    await state.update_data(user_id=user_id)

    # Show last 7 days if available
    intro = ""
    if entries:
        intro = _entry_summary(entries) + "\n\n"

    await message.answer(
        f"{intro}"
        "📔 <b>Новая запись в дневник</b>\n\n"
        "😴 <b>Качество сна прошлой ночью?</b>\n"
        "<i>1 — очень плохо, 5 — отлично</i>",
        parse_mode="HTML",
        reply_markup=rating_keyboard("diary:sleep"),
    )


# ── Sleep rating ───────────────────────────────────────────────────────────

@router.callback_query(DiaryState.sleep, F.data.startswith("diary:sleep:"))
async def cb_sleep(call: CallbackQuery, state: FSMContext) -> None:
    value = int(call.data.split(":")[2])
    await state.update_data(sleep=value)
    await state.set_state(DiaryState.energy)

    await call.message.edit_text(
        f"😴 Сон: {_bar(value)} ({value}/5)\n\n"
        "⚡ <b>Уровень энергии сегодня?</b>\n"
        "<i>1 — нет сил совсем, 5 — полон энергии</i>",
        parse_mode="HTML",
        reply_markup=rating_keyboard("diary:energy"),
    )
    await call.answer()


# ── Energy rating ──────────────────────────────────────────────────────────

@router.callback_query(DiaryState.energy, F.data.startswith("diary:energy:"))
async def cb_energy(call: CallbackQuery, state: FSMContext) -> None:
    value = int(call.data.split(":")[2])
    await state.update_data(energy=value)
    await state.set_state(DiaryState.stress)

    await call.message.edit_text(
        f"⚡ Энергия: {_bar(value)} ({value}/5)\n\n"
        "😤 <b>Уровень стресса сегодня?</b>\n"
        "<i>1 — полный покой, 5 — очень высокий стресс</i>",
        parse_mode="HTML",
        reply_markup=rating_keyboard("diary:stress", reverse=True),
    )
    await call.answer()


# ── Stress rating ──────────────────────────────────────────────────────────

@router.callback_query(DiaryState.stress, F.data.startswith("diary:stress:"))
async def cb_stress(call: CallbackQuery, state: FSMContext) -> None:
    value = int(call.data.split(":")[2])
    await state.update_data(stress=value)
    await state.set_state(DiaryState.bads)

    await call.message.edit_text(
        f"😤 Стресс: {_bar(value)} ({value}/5)\n\n"
        "💊 <b>Принимали ли вы БАД сегодня?</b>",
        parse_mode="HTML",
        reply_markup=bads_taken_keyboard(),
    )
    await call.answer()


# ── BADs taken ─────────────────────────────────────────────────────────────

@router.callback_query(DiaryState.bads, F.data.startswith("diary:bads:"))
async def cb_bads(call: CallbackQuery, state: FSMContext) -> None:
    bads_taken = call.data.split(":")[2] == "yes"
    data = await state.get_data()

    user_id     = data["user_id"]
    sleep_val   = data["sleep"]
    energy_val  = data["energy"]
    stress_val  = data["stress"]

    today = _today()
    await save_diary_entry(
        user_id=user_id,
        entry_date=today,
        sleep_quality=sleep_val,
        energy_level=energy_val,
        stress_level=stress_val,
        bads_taken=int(bads_taken),
        notes=None,
    )

    await state.clear()

    bads_icon = "✅ Да" if bads_taken else "❌ Нет"
    await call.message.edit_text(
        "✅ <b>Запись сохранена!</b>\n\n"
        f"😴 Сон:    {_bar(sleep_val)} {sleep_val}/5\n"
        f"⚡ Энергия: {_bar(energy_val)} {energy_val}/5\n"
        f"😤 Стресс:  {_bar(stress_val)} {stress_val}/5\n"
        f"💊 БАД: {bads_icon}\n\n"
        "<i>Продолжайте вести дневник — наблюдение за динамикой поможет "
        "заметить реальный прогресс от приёма БАД!</i>",
        parse_mode="HTML",
    )
    await call.message.answer("Выберите действие 👇", reply_markup=main_menu())
    await call.answer()
