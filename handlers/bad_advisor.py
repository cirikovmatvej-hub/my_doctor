"""
BAD Advisor — goal-based supplement recommendation flow.

Flow:
  "💊 Подбор БАД" → goal selection → clarifying question (single-BAD goals only)
  → safety check → lifestyle tips → BAD card(s)
  Each BAD card has a "🔔 Начать курс" button → handled by tracker.py
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from data.bad_safety import check_bad_safety, get_bad_synergies, suggest_goal_keys
from data.resources import BAD_DETAILS, BAD_GOALS, BADS, GOAL_CLARIFY_QUESTIONS, LIFESTYLE_TIPS
from database.db import get_user_profile
from keyboards.keyboards import bad_goals_keyboard, goal_clarify_keyboard, main_menu, track_start_keyboard

router = Router()


# ── BAD card builder ──────────────────────────────────────────────────────

def _build_bad_card(bad_key: str) -> str:
    d = BAD_DETAILS[bad_key]
    b = BADS[bad_key]
    with_food = "да, принимайте с едой" if d["with_food"] else "натощак или без привязки к еде"
    parts = [
        f"{d['emoji']} <b>{d['full_name']}</b>\n"
        f"🎯 {d['goal']}\n\n"
        f"📅 Курс: <b>{d['course_days']} дней</b>\n"
        f"💊 Доза: {d['dosage']}\n"
        f"🕐 Время приёма: {d['best_time']}\n"
        f"🍽 С едой: {with_food}\n\n"
        f"📝 {d['notes']}"
    ]

    synergies = get_bad_synergies(bad_key)
    if synergies:
        parts.append(
            "\n🤝 <b>Сочетание с другими нутриентами:</b>\n"
            + "\n".join(f"• {s.message}" for s in synergies)
        )

    parts.append(f'\n🛒 <a href="{b["url"]}">Купить на Ozon</a>')
    return "\n".join(parts)


# ── Handlers ──────────────────────────────────────────────────────────────

@router.message(F.text == "💊 Подбор БАД")
async def cmd_bad_advisor(message: Message, state: FSMContext) -> None:
    await state.clear()
    profile = await get_user_profile(message.from_user.id)
    suggested = suggest_goal_keys(profile)

    intro = "🎯 <b>Подбор БАД под вашу цель</b>\n\n"
    if suggested:
        intro += "Судя по вашему профилю, вам может быть особенно актуально то, что отмечено ⭐.\n\n"
    intro += "Выберите, что сейчас важнее для вас:"

    await message.answer(
        intro,
        parse_mode="HTML",
        reply_markup=bad_goals_keyboard(suggested),
    )


@router.callback_query(F.data.startswith("badgoal:"))
async def cb_goal_selected(call: CallbackQuery, state: FSMContext) -> None:
    goal_key = call.data.split(":")[1]
    goal = BAD_GOALS.get(goal_key)
    if not goal:
        await call.answer("Неизвестная цель", show_alert=True)
        return

    await call.answer()

    clarify = GOAL_CLARIFY_QUESTIONS.get(goal_key)
    if clarify:
        await call.message.edit_text(
            f"🎯 Цель: <b>{goal['label']}</b>\n\n{clarify['question']}",
            parse_mode="HTML",
            reply_markup=goal_clarify_keyboard(goal_key, clarify["options"]),
        )
        return

    await call.message.edit_text(f"🎯 Цель: <b>{goal['label']}</b>", parse_mode="HTML")
    await _show_goal_recommendations(call, goal_key)


@router.callback_query(F.data.startswith("badclarify:"))
async def cb_clarify_answer(call: CallbackQuery, state: FSMContext) -> None:
    _, goal_key, option_key = call.data.split(":")
    goal = BAD_GOALS.get(goal_key)
    clarify = GOAL_CLARIFY_QUESTIONS.get(goal_key)
    if not goal or not clarify:
        await call.answer("Неизвестная цель", show_alert=True)
        return

    await call.answer()
    await call.message.edit_text(f"🎯 Цель: <b>{goal['label']}</b>", parse_mode="HTML")

    extra_note = clarify["notes"].get(option_key)
    await _show_goal_recommendations(call, goal_key, extra_note)


async def _show_goal_recommendations(
    call: CallbackQuery, goal_key: str, extra_note: str | None = None,
) -> None:
    goal = BAD_GOALS[goal_key]

    # Load health profile for safety check
    profile = await get_user_profile(call.from_user.id)

    # ── Safety warnings ────────────────────────────────────────────────────
    all_warnings = []
    for bad_key in goal["bads"]:
        all_warnings.extend(f"⚠️ {w.message}" for w in check_bad_safety(bad_key, profile))

    if all_warnings:
        warning_text = (
            "🔍 <b>Важно!</b> Исходя из вашего профиля здоровья:\n\n"
            + "\n\n".join(all_warnings)
            + "\n\n<i>Вы можете продолжить ознакомление с БАД, но при наличии сомнений "
            "лучше проконсультироваться с врачом.</i>"
        )
        await call.message.answer(warning_text, parse_mode="HTML")

    if extra_note:
        await call.message.answer(f"💬 {extra_note}", parse_mode="HTML")

    # ── Lifestyle tips first ───────────────────────────────────────────────
    tips = LIFESTYLE_TIPS.get(goal_key, "")
    if tips:
        await call.message.answer(
            f"🌿 <b>Рекомендации по образу жизни</b>\n\n{tips}\n\n"
            "Эти привычки усилят эффект от БАД. Переходим к добавкам 👇",
            parse_mode="HTML",
        )

    # ── BAD card(s) ────────────────────────────────────────────────────────
    for bad_key in goal["bads"]:
        card_text = _build_bad_card(bad_key)
        await call.message.answer(
            card_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=track_start_keyboard(bad_key),
        )

    await call.message.answer(
        "Нажмите <b>«🔔 Начать курс»</b> под нужным БАД, чтобы я напоминал вам о приёме.\n\n"
        "Или вернитесь в главное меню 👇",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )
