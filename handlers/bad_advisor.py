"""
BAD Advisor — goal-based supplement recommendation flow.

Flow:
  "💊 Подбор БАД" → goal selection → clarifying question (single-BAD goals only)
  → safety check → lifestyle tips → BAD card(s) → general-supplement card(s)
  Catalog cards have a "🔔 Начать курс" button (with Ozon link) → tracker.py.
  General-supplement cards (data/general_supplements.py — honest info about
  things we don't sell) have a "🔔 Отслеживать приём" button instead, which
  starts the same custom-tracker flow the AI path already uses for
  general_supplement_suggestion — no purchase link, we don't sell these.

  Either kind is skipped entirely (not just warned) when check_*_safety finds
  a kind="contraindication" for this patient's profile — same hard rule the
  AI consultation path enforces, previously this flow only showed a warning
  above an otherwise-unconditional card.
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from data.bad_safety import check_bad_safety, get_bad_synergies, suggest_goal_keys
from data.general_supplements import GENERAL_SUPPLEMENTS, check_general_supplement_safety
from data.resources import BAD_DETAILS, BAD_GOALS, BADS, GOAL_CLARIFY_QUESTIONS, LIFESTYLE_TIPS
from database.db import get_user_profile
from keyboards.keyboards import (
    bad_goals_keyboard, general_supplement_keyboard, goal_clarify_keyboard,
    main_menu, track_start_keyboard,
)

router = Router()


# ── Card builders ────────────────────────────────────────────────────────

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


def _build_general_card(general_key: str) -> str:
    """Same spirit as _build_bad_card but for something we don't sell — no
    dosage/course/buy link (there's no preset product to point at), just
    honest goal/notes from the knowledge base and a course-tracking option."""
    d = GENERAL_SUPPLEMENTS[general_key]
    parts = [
        f"💊 <b>{d['label']}</b>\n"
        f"🎯 {d['goal']}"
    ]
    if d.get("notes"):
        parts.append(f"\n📝 {d['notes']}")
    parts.append(
        "\n<i>Мы не продаём этот БАД, но можем помочь не забывать о приёме, "
        "если решите его пить — просто выберите свою дозировку и время.</i>"
    )
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
    general_keys = goal.get("general_supplements", [])

    # Load health profile for safety check
    profile = await get_user_profile(call.from_user.id)

    # ── Safety check — split into blocking (contraindication: skip the card
    # entirely) vs. non-blocking (show a warning above the card) ───────────
    blocked_bad_keys: set[str] = set()
    blocked_general_keys: set[str] = set()
    non_blocking_warnings: list[str] = []
    blocked_notes: list[str] = []

    for bad_key in goal["bads"]:
        warnings = check_bad_safety(bad_key, profile)
        if any(w.kind == "contraindication" for w in warnings):
            blocked_bad_keys.add(bad_key)
            blocked_notes.extend(f"⛔ {w.message}" for w in warnings if w.kind == "contraindication")
        else:
            non_blocking_warnings.extend(f"⚠️ {w.message}" for w in warnings)

    for general_key in general_keys:
        warnings = check_general_supplement_safety(general_key, profile)
        if any(w.kind == "contraindication" for w in warnings):
            blocked_general_keys.add(general_key)
            blocked_notes.extend(f"⛔ {w.message}" for w in warnings if w.kind == "contraindication")
        else:
            non_blocking_warnings.extend(f"⚠️ {w.message}" for w in warnings)

    if blocked_notes:
        await call.message.answer(
            "🔍 <b>Важно!</b> Исходя из вашего профиля здоровья, не показываю "
            "часть вариантов:\n\n" + "\n\n".join(blocked_notes)
            + "\n\n<i>При наличии сомнений проконсультируйтесь с врачом.</i>",
            parse_mode="HTML",
        )

    if non_blocking_warnings:
        await call.message.answer(
            "🔍 <b>Обратите внимание</b> — исходя из вашего профиля здоровья:\n\n"
            + "\n\n".join(non_blocking_warnings)
            + "\n\n<i>Это не противопоказание, но при наличии сомнений лучше "
            "проконсультироваться с врачом.</i>",
            parse_mode="HTML",
        )

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

    # ── Catalog BAD card(s) ─────────────────────────────────────────────────
    shown_bad_keys = [k for k in goal["bads"] if k not in blocked_bad_keys]
    for bad_key in shown_bad_keys:
        card_text = _build_bad_card(bad_key)
        await call.message.answer(
            card_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=track_start_keyboard(bad_key),
        )

    # ── General (non-catalog) supplement card(s) ────────────────────────────
    shown_general_keys = [k for k in general_keys if k not in blocked_general_keys]
    if shown_general_keys:
        if shown_bad_keys:
            intro = (
                "🧪 <b>Ещё варианты, которых нет в нашем каталоге</b>\n\n"
                "Мы их не продаём, но можем честно рассказать и помочь не забывать о приёме:"
            )
        else:
            intro = (
                "🧪 <b>Вот что можно рассмотреть</b>\n\n"
                "В нашем каталоге для этой цели готового продукта нет, но по этим веществам "
                "есть данные — честно расскажем и поможем не забывать о приёме:"
            )
        await call.message.answer(intro, parse_mode="HTML")
    for general_key in shown_general_keys:
        d = GENERAL_SUPPLEMENTS[general_key]
        card_text = _build_general_card(general_key)
        await call.message.answer(
            card_text,
            parse_mode="HTML",
            reply_markup=general_supplement_keyboard(d["label"]),
        )

    # Every option for this goal was contraindicated — no cards were shown at
    # all, so the usual "нажмите кнопку" closing would be misleading.
    if not shown_bad_keys and not shown_general_keys:
        await call.message.answer(
            "По вашему профилю здоровья ни один из вариантов для этой цели "
            "показать нельзя — пожалуйста, обсудите подходящую поддержку с врачом.",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        return

    button_labels = []
    if shown_bad_keys:
        button_labels.append("«🔔 Начать курс»")
    if shown_general_keys:
        button_labels.append("«🔔 Отслеживать приём»")
    closing = (
        f"Нажмите {' или '.join(button_labels)} под нужным вариантом, чтобы я напоминал "
        "вам о приёме.\n\nИли вернитесь в главное меню 👇"
    )
    await call.message.answer(closing, parse_mode="HTML", reply_markup=main_menu())
