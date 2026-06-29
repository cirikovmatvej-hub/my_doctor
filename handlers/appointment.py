"""Doctor appointment follow-up: ask if user booked, why not, and schedule a reminder."""
import asyncio
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import APPOINTMENT_ASK_HOURS
from data.resources import DOCTORS
from database.db import (
    create_appointment_followup, get_due_appointment_asks, get_due_appointment_reminders,
    mark_appointment_ask_sent, mark_appointment_reminder_sent,
    set_appointment_reason, set_appointment_reminder, set_appointment_status,
)
from keyboards.keyboards import (
    appointment_booked_keyboard, appointment_reason_keyboard,
    appointment_remind_keyboard, main_menu,
)

router = Router()

APPOINTMENT_CHECK_INTERVAL = 1800  # 30 минут — как в followup.py


class AppointmentState(StatesGroup):
    entering_custom_date = State()


# ── Public helper: call this right after sending a doctor link ─────────────

async def schedule_appointment_followup(user_id: int, doctor_specialty: str) -> None:
    ask_at = datetime.now() + timedelta(hours=APPOINTMENT_ASK_HOURS)
    await create_appointment_followup(user_id, doctor_specialty, ask_at)


def _doctor_name(doctor_specialty: str) -> str:
    return DOCTORS.get(doctor_specialty, {}).get("name", "врачу")


# ── Background loop ─────────────────────────────────────────────────────────

async def appointment_loop(bot: Bot) -> None:
    logging.info("Appointment follow-up loop started")
    while True:
        await asyncio.sleep(APPOINTMENT_CHECK_INTERVAL)
        try:
            now = datetime.now()

            for followup_id, telegram_id, doctor_specialty in await get_due_appointment_asks(now):
                try:
                    await bot.send_message(
                        telegram_id,
                        f"👨‍⚕️ Вы записались на приём к врачу ({_doctor_name(doctor_specialty)})?",
                        reply_markup=appointment_booked_keyboard(followup_id),
                    )
                    await mark_appointment_ask_sent(followup_id)
                except Exception as e:
                    logging.warning(f"Could not send appointment ask to {telegram_id}: {e}")

            for followup_id, telegram_id, doctor_specialty in await get_due_appointment_reminders(now):
                try:
                    await bot.send_message(
                        telegram_id,
                        f"🔔 Напоминание: не забудьте про визит к врачу "
                        f"({_doctor_name(doctor_specialty)}) 🤍",
                    )
                    await mark_appointment_reminder_sent(followup_id)
                except Exception as e:
                    logging.warning(f"Could not send appointment reminder to {telegram_id}: {e}")
        except Exception as e:
            logging.error(f"Appointment loop error: {e}")


# ── Callbacks: booked? ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("appt:booked:"))
async def cb_appt_booked(call: CallbackQuery) -> None:
    followup_id = int(call.data.split(":")[2])
    await set_appointment_status(followup_id, "booked")
    await call.message.edit_text(
        "Отлично! 🎉 Когда напомнить вам про визит?",
        reply_markup=appointment_remind_keyboard(followup_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("appt:notbooked:"))
async def cb_appt_not_booked(call: CallbackQuery) -> None:
    followup_id = int(call.data.split(":")[2])
    await set_appointment_status(followup_id, "not_booked")
    await call.message.edit_text(
        "Понял. Что помешало записаться?",
        reply_markup=appointment_reason_keyboard(followup_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("appt:reason:"))
async def cb_appt_reason(call: CallbackQuery) -> None:
    _, _, followup_id_str, reason = call.data.split(":")
    await set_appointment_reason(int(followup_id_str), reason)
    await call.message.edit_text(
        "Спасибо, что поделились! Если самочувствие не улучшится — "
        "ссылка на запись всегда доступна в истории консультаций 🤍",
        reply_markup=None,
    )
    await call.answer()


# ── Callbacks: when to remind ───────────────────────────────────────────────

_OFFSET_LABELS = {"tomorrow": "завтра", "3days": "через 3 дня", "week": "через неделю"}


@router.callback_query(F.data.startswith("appt:remind:"))
async def cb_appt_remind(call: CallbackQuery, state: FSMContext) -> None:
    _, _, followup_id_str, option = call.data.split(":")
    followup_id = int(followup_id_str)

    if option == "custom":
        await state.set_state(AppointmentState.entering_custom_date)
        await state.update_data(followup_id=followup_id)
        await call.message.edit_text(
            "✏️ Введите дату и время напоминания\nНапример: <code>15.07 10:00</code>",
            parse_mode="HTML",
        )
        await call.answer()
        return

    if option == "none":
        await set_appointment_reminder(followup_id, None)
        await call.message.edit_text("Хорошо, без напоминания. Удачи на приёме! 🤍", reply_markup=None)
        await call.answer()
        return

    now = datetime.now()
    offsets = {
        "tomorrow": now + timedelta(days=1),
        "3days":    now + timedelta(days=3),
        "week":     now + timedelta(days=7),
    }
    reminder_at = offsets.get(option)
    await set_appointment_reminder(followup_id, reminder_at)

    await call.message.edit_text(
        f"Хорошо, напомню {_OFFSET_LABELS.get(option, '')}! Удачи на приёме 🤍",
        reply_markup=None,
    )
    await call.answer()


_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s*(?:(\d{1,2}):(\d{2}))?")


def _parse_custom_date(text: str) -> datetime | None:
    m = _DATE_RE.search((text or "").strip())
    if not m:
        return None
    day, month, year, hour, minute = m.groups()
    now = datetime.now()
    year = int(year) if year else now.year
    if year < 100:
        year += 2000
    hour = int(hour) if hour else 9
    minute = int(minute) if minute else 0
    try:
        dt = datetime(year, int(month), int(day), hour, minute)
    except ValueError:
        return None
    if dt < now:
        dt = dt.replace(year=dt.year + 1)
    return dt


@router.message(AppointmentState.entering_custom_date)
async def msg_custom_date(message: Message, state: FSMContext) -> None:
    dt = _parse_custom_date(message.text)
    if not dt:
        await message.answer(
            "⚠️ Формат не распознан. Введите дату как <b>ДД.MM</b> или <b>ДД.MM ЧЧ:MM</b>, "
            "например: <code>15.07 10:00</code>",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    await set_appointment_reminder(data["followup_id"], dt)
    await state.clear()

    await message.answer(
        f"Хорошо, напомню {dt.strftime('%d.%m в %H:%M')}! Удачи на приёме 🤍",
        reply_markup=main_menu(),
    )
