"""
Tracker — supplement tracking with custom reminder times + timezone support.

Setup flow (catalog БАД, from bad_advisor card):
  "🔔 Начать курс" → timezone (first time only) → time_1 → time_2 (if 2x/day) → confirm

Setup flow (custom, non-catalog БАД):
  "➕ Другой БАД" → name → course length → 1x/2x a day → (same time-picking as above)

Both flows converge on the same time-selection code, driven by daily_doses/
default_times/course_days stored in FSM state rather than looked up from
BAD_DETAILS — custom entries simply aren't in that dict, and the DB layer
already treats product_key as an opaque string (no catalog validation there),
so a custom entry is stored exactly like a catalog one under the hood.

Reminder loop: checks every minute (UTC), fires when user's local time matches set time.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from data.resources import BAD_DETAILS, BADS
from database.db import (
    create_tracking, get_active_trackings, get_days_taken,
    get_due_reminders, get_near_end_courses, get_or_create_user,
    get_utc_offset, log_intake, mark_end_reminder_sent,
    mark_reminder_sent, set_utc_offset,
)
from keyboards.keyboards import (
    daily_doses_keyboard, intake_keyboard, main_menu, time_keyboard,
    timezone_keyboard, tracker_menu_keyboard,
)

router = Router()

REMINDER_CHECK_INTERVAL = 60  # проверяем каждую минуту


# ── States ─────────────────────────────────────────────────────────────────

class TrackerState(StatesGroup):
    entering_custom_name        = State()
    entering_custom_course_days = State()
    selecting_daily_doses       = State()
    selecting_timezone          = State()
    selecting_time_1            = State()
    entering_custom_time_1      = State()
    selecting_time_2            = State()
    entering_custom_time_2      = State()


# ── "📊 Мой трекер" ────────────────────────────────────────────────────────

@router.message(F.text == "📊 Мой трекер")
async def cmd_tracker(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = await get_or_create_user(message.from_user.id, message.from_user.username)
    trackings = await get_active_trackings(user_id)

    if not trackings:
        await message.answer(
            "📊 <b>Мой трекер</b>\n\n"
            "У вас пока нет активных курсов.\n\n"
            "Перейдите в <b>«💊 Подбор БАД»</b> и выберите продукт, "
            "или добавьте свой БАД вручную 👇",
            parse_mode="HTML",
            reply_markup=tracker_menu_keyboard(),
        )
        return

    lines = ["📊 <b>Ваши активные курсы:</b>\n"]
    for tracking_id, product_key, start_date, course_days, rt1, rt2 in trackings:
        d = BAD_DETAILS.get(product_key, {})
        name = d.get("full_name", product_key)
        emoji = d.get("emoji", "💊")
        days_taken = await get_days_taken(tracking_id)
        days_left = max(0, course_days - days_taken)
        remind = _reminder_label(rt1, rt2)
        lines.append(
            f"{emoji} <b>{name}</b>\n"
            f"   ✅ Принято: {days_taken} / {course_days} дней\n"
            f"   ⏳ Осталось: {days_left} дней\n"
            f"   🔔 Напоминания: {remind}\n"
        )

    lines.append("Для нового курса — «💊 Подбор БАД» или добавьте свой БАД 👇")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=tracker_menu_keyboard())
    await message.answer("Выберите действие 👇", reply_markup=main_menu())


def _reminder_label(rt1: str | None, rt2: str | None) -> str:
    times = [t for t in (rt1, rt2) if t]
    return " и ".join(times) if times else "отключены"


# ── Start tracking (from bad_advisor card) ─────────────────────────────────

@router.callback_query(F.data.startswith("track:start:"))
async def cb_track_start(call: CallbackQuery, state: FSMContext) -> None:
    product_key = call.data.split(":")[2]
    if product_key not in BAD_DETAILS:
        await call.answer("Продукт не найден", show_alert=True)
        return

    d = BAD_DETAILS[product_key]
    await state.clear()
    await state.update_data(
        product_key=product_key,
        course_days=d.get("course_days", 30),
        daily_doses=d.get("daily_doses", 1),
        default_times=d.get("default_times", ["08:00"]),
    )

    await _check_timezone_then_ask_time(call.message, state, call.from_user.id)
    await call.answer()


# ── Start tracking (custom, non-catalog БАД) ───────────────────────────────

@router.callback_query(F.data == "track:custom")
async def cb_track_custom(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(TrackerState.entering_custom_name)
    await call.message.answer(
        "💊 <b>Какой БАД хотите отслеживать?</b>\n"
        "Напишите название — например, <i>«Железо хелат»</i> или «Омега-3»",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(TrackerState.entering_custom_name)
async def msg_custom_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not (1 <= len(name) <= 100):
        await message.answer("Название должно быть от 1 до 100 символов.")
        return
    await state.update_data(product_key=name)
    await state.set_state(TrackerState.entering_custom_course_days)
    await message.answer(
        "📅 <b>На сколько дней рассчитан курс?</b>\nНапример: <code>30</code>",
        parse_mode="HTML",
    )


# ── Start tracking (from a non-catalog AI recommendation) ─────────────────
# Same flow as "➕ Другой БАД", but the name is already known — skip straight
# to asking course length.

@router.callback_query(F.data.startswith("track:customstart:"))
async def cb_track_custom_start(call: CallbackQuery, state: FSMContext) -> None:
    name = call.data.split(":", 2)[2]
    await state.clear()
    await state.update_data(product_key=name)
    await state.set_state(TrackerState.entering_custom_course_days)
    await call.message.answer(
        f"📅 <b>На сколько дней рассчитан курс «{name}»?</b>\nНапример: <code>30</code>",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(TrackerState.entering_custom_course_days)
async def msg_custom_course_days(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= 365):
        await message.answer("⚠️ Введите число дней от 1 до 365, например <code>30</code>.", parse_mode="HTML")
        return
    await state.update_data(course_days=int(text))
    await state.set_state(TrackerState.selecting_daily_doses)
    await message.answer(
        "🔢 <b>Сколько раз в день принимать?</b>",
        parse_mode="HTML",
        reply_markup=daily_doses_keyboard(),
    )


@router.callback_query(TrackerState.selecting_daily_doses, F.data.startswith("dailydoses:"))
async def cb_daily_doses(call: CallbackQuery, state: FSMContext) -> None:
    daily = int(call.data.split(":")[1])
    default_times = ["08:00"] if daily == 1 else ["08:00", "20:00"]
    await state.update_data(daily_doses=daily, default_times=default_times)
    await call.message.edit_reply_markup(reply_markup=None)

    await _check_timezone_then_ask_time(call.message, state, call.from_user.id)
    await call.answer()


# ── Timezone ───────────────────────────────────────────────────────────────

async def _check_timezone_then_ask_time(message: Message, state: FSMContext, telegram_id: int) -> None:
    utc_offset = await get_utc_offset(telegram_id)
    if utc_offset is None:
        await state.set_state(TrackerState.selecting_timezone)
        await message.answer(
            "🌍 <b>Сначала укажите ваш часовой пояс</b>\n\n"
            "Это нужно, чтобы напоминания приходили в нужное время.",
            parse_mode="HTML",
            reply_markup=timezone_keyboard(),
        )
    else:
        await _ask_time_1(message, state)


@router.callback_query(TrackerState.selecting_timezone, F.data.startswith("tz:"))
async def cb_timezone(call: CallbackQuery, state: FSMContext) -> None:
    offset = int(call.data.split(":")[1])
    await set_utc_offset(call.from_user.id, offset)
    await call.message.edit_reply_markup(reply_markup=None)

    await _ask_time_1(call.message, state)
    await call.answer()


# ── Time selection ─────────────────────────────────────────────────────────

async def _ask_time_1(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    default_times = data.get("default_times", ["08:00"])
    daily = data.get("daily_doses", 1)

    await state.set_state(TrackerState.selecting_time_1)
    await message.answer(
        f"🔔 <b>Время {'первого ' if daily > 1 else ''}напоминания</b>\n\n"
        f"Рекомендуем: <b>{default_times[0]}</b>\n"
        "Выберите удобное время или напишите своё:",
        parse_mode="HTML",
        reply_markup=time_keyboard("time1"),
    )


@router.callback_query(TrackerState.selecting_time_1, F.data.startswith("time1:"))
async def cb_time_1(call: CallbackQuery, state: FSMContext) -> None:
    value = call.data.split(":", 1)[1]
    if value == "custom":
        await state.set_state(TrackerState.entering_custom_time_1)
        await call.message.edit_text(
            "✏️ Введите время в формате <b>ЧЧ:ММ</b>\nНапример: <code>08:30</code>",
            parse_mode="HTML",
        )
        await call.answer()
        return

    await state.update_data(time_1=value)
    await call.message.edit_reply_markup(reply_markup=None)
    await _after_time_1(call.message, state)
    await call.answer()


@router.message(TrackerState.entering_custom_time_1)
async def msg_custom_time_1(message: Message, state: FSMContext) -> None:
    t = _parse_time(message.text)
    if not t:
        await message.answer("⚠️ Формат не распознан. Введите время как <b>ЧЧ:ММ</b>, например <code>09:00</code>", parse_mode="HTML")
        return
    await state.update_data(time_1=t)
    await _after_time_1(message, state)


async def _after_time_1(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    daily = data.get("daily_doses", 1)

    if daily > 1:
        default_times = data.get("default_times", ["08:00", "20:00"])
        default2 = default_times[-1]
        await state.set_state(TrackerState.selecting_time_2)
        await message.answer(
            f"🔔 <b>Время второго напоминания</b>\n\n"
            f"Рекомендуем: <b>{default2}</b>\n"
            "Выберите или введите своё:",
            parse_mode="HTML",
            reply_markup=time_keyboard("time2", can_skip=True),
        )
    else:
        await _create_and_confirm(message, state, time_2=None)


@router.callback_query(TrackerState.selecting_time_2, F.data.startswith("time2:"))
async def cb_time_2(call: CallbackQuery, state: FSMContext) -> None:
    value = call.data.split(":", 1)[1]
    await call.message.edit_reply_markup(reply_markup=None)

    if value == "custom":
        await state.set_state(TrackerState.entering_custom_time_2)
        await call.message.edit_text(
            "✏️ Введите время в формате <b>ЧЧ:ММ</b>\nНапример: <code>21:00</code>",
            parse_mode="HTML",
        )
        await call.answer()
        return

    time_2 = None if value == "none" else value
    await _create_and_confirm(call.message, state, time_2=time_2)
    await call.answer()


@router.message(TrackerState.entering_custom_time_2)
async def msg_custom_time_2(message: Message, state: FSMContext) -> None:
    t = _parse_time(message.text)
    if not t:
        await message.answer("⚠️ Формат не распознан. Введите время как <b>ЧЧ:ММ</b>, например <code>21:00</code>", parse_mode="HTML")
        return
    await _create_and_confirm(message, state, time_2=t)


def _parse_time(text: str) -> str | None:
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", (text or "").strip())
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


# ── Create tracking & confirm ──────────────────────────────────────────────

async def _create_and_confirm(message: Message, state: FSMContext, time_2: str | None) -> None:
    data = await state.get_data()
    product_key = data.get("product_key", "")
    course_days = data.get("course_days", 30)
    time_1 = data.get("time_1")
    await state.clear()

    user_id = await get_or_create_user(message.chat.id, None)
    await create_tracking(user_id, product_key, course_days, time_1, time_2)

    d = BAD_DETAILS.get(product_key, {})
    remind = _reminder_label(time_1, time_2)
    emoji = d.get("emoji", "💊")
    full_name = d.get("full_name", product_key)

    await message.answer(
        f"✅ <b>Курс запущен!</b>\n\n"
        f"{emoji} {full_name}\n"
        f"📅 Длительность: {course_days} дней\n"
        f"🔔 Напоминания: {remind}\n\n"
        "Буду напоминать вам о приёме в выбранное время 💪",
        parse_mode="HTML",
    )
    await message.answer("Выберите действие 👇", reply_markup=main_menu())


# ── Intake callbacks ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("intake:"))
async def cb_intake(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) < 4:
        await call.answer()
        return

    status_str  = parts[1]
    tracking_id = int(parts[2])
    slot        = parts[3]

    today = datetime.utcnow().strftime("%Y-%m-%d")
    await log_intake(tracking_id, today, slot, status_str)

    if status_str == "taken":
        await call.message.edit_text("✅ Отлично, приём зафиксирован! Так держать 💪", reply_markup=None)
    else:
        await call.message.edit_text("⏭ Пропуск отмечен. Постарайтесь не пропускать — результат зависит от регулярности.", reply_markup=None)
    await call.answer()


# ── Background reminder loop ──────────────────────────────────────────────

async def _send_reminder(bot: Bot, tracking_id: int, telegram_id: int,
                          product_key: str, slot: str) -> None:
    d = BAD_DETAILS.get(product_key, {})
    name  = d.get("full_name", product_key)
    emoji = d.get("emoji", "💊")
    daily = d.get("daily_doses", 1)
    dosage = d.get("dosage", "по инструкции")

    if daily > 1:
        slot_label = "утреннего" if slot == "1" else "вечернего"
        dose_note = f"2 капсулы ({slot_label} приём)"
    else:
        dose_note = dosage

    text = (
        f"⏰ Время принять БАД!\n\n"
        f"{emoji} <b>{name}</b>\n"
        f"💊 {dose_note}"
    )

    try:
        await bot.send_message(
            telegram_id, text, parse_mode="HTML",
            reply_markup=intake_keyboard(tracking_id, slot),
        )
    except Exception as e:
        logging.warning(f"Cannot send reminder to {telegram_id}: {e}")


async def _send_end_reminder(bot: Bot, tracking_id: int, telegram_id: int,
                              product_key: str, days_taken: int, course_days: int) -> None:
    d = BAD_DETAILS.get(product_key, {})
    name  = d.get("full_name", product_key)
    emoji = d.get("emoji", "💊")
    b_url = BADS.get(product_key, {}).get("url", "")
    days_left = max(0, course_days - days_taken)

    text = (
        f"🎉 <b>Курс подходит к концу!</b>\n\n"
        f"{emoji} <b>{name}</b>\n"
        f"✅ Пройдено: {days_taken} из {course_days} дней\n"
        f"⏳ Осталось примерно {days_left} дн.\n\n"
        "Закажите следующую упаковку заранее, чтобы не прерывать курс 👇"
    )
    if b_url:
        text += f'\n\n🛒 <a href="{b_url}">Купить на Ozon</a>'

    try:
        await bot.send_message(telegram_id, text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logging.warning(f"Cannot send end-reminder to {telegram_id}: {e}")


async def reminder_loop(bot: Bot) -> None:
    logging.info("Tracker reminder loop started")
    while True:
        await asyncio.sleep(REMINDER_CHECK_INTERVAL)
        try:
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

            due = await get_due_reminders(now_utc)
            for tracking_id, telegram_id, product_key, _, slot, user_date in due:
                await _send_reminder(bot, tracking_id, telegram_id, product_key, slot)
                await mark_reminder_sent(tracking_id, slot, user_date)
            if due:
                logging.info(f"Sent {len(due)} reminders")

            near_end = await get_near_end_courses()
            for tracking_id, telegram_id, product_key, days_taken, course_days in near_end:
                await _send_end_reminder(bot, tracking_id, telegram_id, product_key, days_taken, course_days)
                await mark_end_reminder_sent(tracking_id)

        except Exception as e:
            logging.error(f"Reminder loop error: {e}")
