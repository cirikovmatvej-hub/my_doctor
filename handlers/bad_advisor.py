"""
BAD Advisor — goal-based supplement recommendation flow.

Flow:
  "💊 Подбор БАД" → goal selection → safety check → lifestyle tips → BAD card(s)
  Each BAD card has a "🔔 Начать курс" button → handled by tracker.py
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from data.resources import BAD_DETAILS, BAD_GOALS, BADS, LIFESTYLE_TIPS
from database.db import get_user_profile
from keyboards.keyboards import bad_goals_keyboard, main_menu, track_start_keyboard

router = Router()


# ── Safety check ──────────────────────────────────────────────────────────

def _check_safety(bad_key: str, profile: dict | None) -> list[str]:
    """Return list of warning strings for this BAD given the user's health profile."""
    if not profile:
        return []
    bad = BAD_DETAILS[bad_key]
    warnings = []

    chronic   = (profile.get("chronic_diseases") or "").lower()
    allergies = (profile.get("allergies") or "").lower()
    meds      = (profile.get("medications")      or "").lower()
    pregnancy = profile.get("pregnancy") or "no"

    name = bad["full_name"]

    # Pregnancy / lactation
    if pregnancy in ("pregnant", "lactating") and not bad.get("pregnancy_safe", False):
        warnings.append(
            f"⚠️ <b>{name}</b>: не подтверждена безопасность при беременности/лактации "
            "— перед приёмом проконсультируйтесь с врачом."
        )

    # Contraindication keywords
    combined = chronic + " " + allergies
    for kw in bad.get("contraindication_keywords", []):
        if kw in combined:
            warnings.append(
                f"⚠️ <b>{name}</b>: обнаружено возможное противопоказание "
                f"(«{kw}» в вашем профиле) — уточните у врача."
            )
            break

    # Drug interaction keywords
    for kw in bad.get("drug_interaction_keywords", []):
        if kw in meds:
            warnings.append(
                f"⚠️ <b>{name}</b>: возможно взаимодействие с вашими препаратами "
                f"(«{kw}») — уточните у врача перед приёмом."
            )
            break

    return warnings


# ── BAD card builder ──────────────────────────────────────────────────────

def _build_bad_card(bad_key: str) -> str:
    d = BAD_DETAILS[bad_key]
    b = BADS[bad_key]
    with_food = "да, принимайте с едой" if d["with_food"] else "натощак или без привязки к еде"
    return (
        f"{d['emoji']} <b>{d['full_name']}</b>\n"
        f"🎯 {d['goal']}\n\n"
        f"📅 Курс: <b>{d['course_days']} дней</b>\n"
        f"💊 Доза: {d['dosage']}\n"
        f"🕐 Время приёма: {d['best_time']}\n"
        f"🍽 С едой: {with_food}\n\n"
        f"📝 {d['notes']}\n\n"
        f'🛒 <a href="{b["url"]}">Купить на Ozon</a>'
    )


# ── Handlers ──────────────────────────────────────────────────────────────

@router.message(F.text == "💊 Подбор БАД")
async def cmd_bad_advisor(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🎯 <b>Подбор БАД под вашу цель</b>\n\n"
        "Выберите, что сейчас важнее для вас:",
        parse_mode="HTML",
        reply_markup=bad_goals_keyboard(),
    )


@router.callback_query(F.data.startswith("badgoal:"))
async def cb_goal_selected(call: CallbackQuery, state: FSMContext) -> None:
    goal_key = call.data.split(":")[1]
    goal = BAD_GOALS.get(goal_key)
    if not goal:
        await call.answer("Неизвестная цель", show_alert=True)
        return

    await call.message.edit_text(
        f"🎯 Цель: <b>{goal['label']}</b>",
        parse_mode="HTML",
    )
    await call.answer()

    # Load health profile for safety check
    profile = await get_user_profile(call.from_user.id)

    # ── Safety warnings ────────────────────────────────────────────────────
    all_warnings = []
    for bad_key in goal["bads"]:
        all_warnings.extend(_check_safety(bad_key, profile))

    if all_warnings:
        warning_text = (
            "🔍 <b>Важно!</b> Исходя из вашего профиля здоровья:\n\n"
            + "\n\n".join(all_warnings)
            + "\n\n<i>Вы можете продолжить ознакомление с БАД, но при наличии сомнений "
            "лучше проконсультироваться с врачом.</i>"
        )
        await call.message.answer(warning_text, parse_mode="HTML")

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
