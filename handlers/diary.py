"""
Wellbeing Diary — daily self-assessment (sleep / energy / stress / BADs taken).

Flow:
  "📔 Дневник" → check today's entry
    → already filled: show today's summary + trend chart
    → not filled: sleep rating → energy rating → stress rating → BADs taken → save
  Either path sends a chart (matplotlib, rendered off the event loop via
  asyncio.to_thread) plotting sleep/energy/stress over the last 30 days,
  plus — as the photo's caption text, not drawn on the chart itself — a
  short before/after summary per tracked course that has enough diary data
  on both sides of its start date. This pairing is the point of tying the
  diary to the tracker: without it, nothing ever showed whether a course
  actually coincided with feeling better.
"""
import asyncio
import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # headless server — no display backend available
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from data.resources import BAD_DETAILS
from database.db import (
    get_all_trackings,
    get_diary_entries,
    get_or_create_user,
    save_diary_entry,
)
from keyboards.keyboards import RATING_WORDS, bads_taken_keyboard, main_menu, rating_keyboard

router = Router()

CHART_DAYS = 30  # how many days of diary history to fetch/plot


# ── States ─────────────────────────────────────────────────────────────────

class DiaryState(StatesGroup):
    sleep  = State()
    energy = State()
    stress = State()
    bads   = State()


# ── Helpers ────────────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


_METRIC_COLORS = {"sleep": "#4C72B0", "energy": "#DD8452", "stress": "#C44E52"}
# Plain text, no emoji: matplotlib's default font (DejaVu Sans, on the VPS
# too) has no emoji glyphs — they'd render as missing-glyph boxes on the
# chart itself. The Telegram caption text below the photo can use emoji
# freely since that's rendered by the Telegram client, not matplotlib.
_METRIC_LABELS = {"sleep": "Сон", "energy": "Энергия", "stress": "Стресс"}


def _tracking_display_name(product_key: str) -> str:
    return BAD_DETAILS.get(product_key, {}).get("full_name", product_key)


def _build_diary_chart(entries: list) -> bytes:
    """Sleep/energy/stress over time. Runs in a worker thread
    (asyncio.to_thread) — this is synchronous CPU work and would otherwise
    stall the whole bot's event loop for every user while it renders.

    No course-start markers on the chart itself (dropped per user feedback —
    they cluttered the image and a garbled tracking name once ended up
    illegible rotated 90°). The before/after correlation still runs and
    ships as the photo's caption text instead — that's plain text, not
    matplotlib, so a long or malformed name there just wraps normally."""
    dates = [datetime.strptime(e[0], "%Y-%m-%d") for e in entries]
    series = {"sleep": [e[1] for e in entries], "energy": [e[2] for e in entries], "stress": [e[3] for e in entries]}

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
    for metric in ("sleep", "energy", "stress"):
        ax.plot(
            dates, series[metric], marker="o", markersize=4, linewidth=2,
            label=_METRIC_LABELS[metric], color=_METRIC_COLORS[metric],
        )

    ax.set_ylim(0.5, 5.5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_ylabel("Оценка (1–5)")
    ax.set_title("Дневник самочувствия", fontsize=12, loc="left", pad=12)
    ax.grid(True, alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    fig.autofmt_xdate(rotation=30)
    ax.legend(loc="lower left", frameon=False, fontsize=9, ncols=3)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


_MIN_SIDE_ENTRIES = 3  # need at least this many diary entries on each side of a course start to say anything


def _course_correlation_text(entries: list, trackings: list) -> str:
    """For each course with enough diary data both before and after its
    start date, compare average sleep/energy/stress. Phrased as "changed
    since", not "improved because of" — this is a correlation from the
    user's own logs, not a clinical claim of what caused it."""
    lines = []
    for _tid, product_key, start_date_str, _status, _ended_at in trackings:
        start_date = start_date_str[:10]
        before = [e for e in entries if e[0] < start_date]
        after = [e for e in entries if e[0] >= start_date]
        if len(before) < _MIN_SIDE_ENTRIES or len(after) < _MIN_SIDE_ENTRIES:
            continue

        parts = []
        for label, idx in (("сон", 1), ("энергия", 2), ("стресс", 3)):
            avg_before = sum(e[idx] for e in before) / len(before)
            avg_after = sum(e[idx] for e in after) / len(after)
            if abs(avg_after - avg_before) < 0.3:
                continue
            arrow = "📈" if avg_after > avg_before else "📉"
            parts.append(f"{label} {avg_before:.1f}→{avg_after:.1f} {arrow}")

        if parts:
            lines.append(f"<b>{_tracking_display_name(product_key)}</b>: " + ", ".join(parts))

    if not lines:
        return ""
    return (
        "📊 <b>Что изменилось с начала курса</b> <i>(по вашим же записям в дневнике, "
        "не медицинский вывод):</i>\n" + "\n".join(lines)
    )


_STATUS_SUFFIX = {"completed": "✅ завершён", "stopped": "🛑 остановлен"}


def _fmt(date_str: str) -> str:
    return datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%d.%m.%Y")


def _course_start_dates_text(entries: list, trackings: list) -> str:
    """Plain "course — start date [— finished date]" list for whichever
    courses started within the plotted window — the dates used to be drawn
    on the chart itself as vertical markers; moved to caption text instead
    (dropped from the chart per user feedback: it cluttered the image)."""
    if not trackings:
        return ""
    date_min, date_max = entries[0][0], entries[-1][0]
    lines = []
    for _tid, product_key, start_date_str, status, ended_at in trackings:
        start_date = start_date_str[:10]
        if not (date_min <= start_date <= date_max):
            continue
        line = f"• {_tracking_display_name(product_key)} — начат {_fmt(start_date)}"
        suffix = _STATUS_SUFFIX.get(status)
        if suffix:
            line += f", {suffix}"
            if ended_at:
                line += f" {_fmt(ended_at)}"
        lines.append(line)

    if not lines:
        return ""
    return "📅 <b>Начало курсов:</b>\n" + "\n".join(lines)


async def _send_trend_chart(message: Message, user_id: int) -> None:
    """Shared by both the 'already filled today' view and right after saving
    a new entry — the chart plus course start dates and any before/after
    correlation, both as caption text below the photo."""
    entries = await get_diary_entries(user_id, limit=CHART_DAYS)
    if len(entries) < 2:
        return  # a single point isn't a chart worth sending yet

    entries = list(reversed(entries))  # chronological order for plotting
    trackings = await get_all_trackings(user_id)

    chart_bytes = await asyncio.to_thread(_build_diary_chart, entries)
    caption_parts = [
        _course_start_dates_text(entries, trackings),
        _course_correlation_text(entries, trackings),
    ]
    caption = "\n\n".join(p for p in caption_parts if p) or "📈 Динамика за последние дни"
    await message.answer_photo(
        BufferedInputFile(chart_bytes, filename="diary_chart.png"),
        caption=caption,
        parse_mode="HTML",
    )


# ── Entry point ────────────────────────────────────────────────────────────

@router.message(F.text == "📔 Дневник")
async def cmd_diary(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = await get_or_create_user(message.from_user.id, message.from_user.username)
    today = _today()

    entries = await get_diary_entries(user_id, limit=1)

    # Check if today's entry already exists
    already_today = entries and entries[0][0] == today

    if already_today:
        _, sleep_val, energy_val, stress_val, bads_taken, _ = entries[0]
        bads_icon = "✅" if bads_taken else "❌"
        await message.answer(
            "📔 <b>Дневник самочувствия</b>\n\n"
            "Запись на сегодня уже есть ✅\n\n"
            f"😴 Сон: {RATING_WORDS[False][sleep_val]}\n"
            f"⚡ Энергия: {RATING_WORDS[False][energy_val]}\n"
            f"😤 Стресс: {RATING_WORDS[True][stress_val]}\n"
            f"💊 БАД: {bads_icon}",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        await _send_trend_chart(message, user_id)
        return

    # Start new entry
    await state.set_state(DiaryState.sleep)
    await state.update_data(user_id=user_id)

    await message.answer(
        "📔 <b>Новая запись в дневник</b>\n\n"
        "😴 <b>Качество сна прошлой ночью?</b>",
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
        f"😴 Сон: {RATING_WORDS[False][value]}\n\n"
        "⚡ <b>Уровень энергии сегодня?</b>",
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
        f"⚡ Энергия: {RATING_WORDS[False][value]}\n\n"
        "😤 <b>Уровень стресса сегодня?</b>",
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
        f"😤 Стресс: {RATING_WORDS[True][value]}\n\n"
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
        f"😴 Сон: {RATING_WORDS[False][sleep_val]}\n"
        f"⚡ Энергия: {RATING_WORDS[False][energy_val]}\n"
        f"😤 Стресс: {RATING_WORDS[True][stress_val]}\n"
        f"💊 БАД: {bads_icon}\n\n"
        "<i>Продолжайте вести дневник — наблюдение за динамикой поможет "
        "заметить реальный прогресс от приёма БАД!</i>",
        parse_mode="HTML",
    )
    await _send_trend_chart(call.message, user_id)
    await call.message.answer("Выберите действие 👇", reply_markup=main_menu())
    await call.answer()
