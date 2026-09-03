import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from database.db import get_pending_followups, mark_followup_sent
from keyboards.keyboards import followup_keyboard, main_menu

router = Router()

FOLLOWUP_CHECK_INTERVAL = 1800  # проверяем каждые 30 минут


# ── Background loop ────────────────────────────────────────────────────────

def _short(complaint: str | None) -> str:
    text = (complaint or "ваша жалоба")[:80]
    if complaint and len(complaint) > 80:
        text += "…"
    return text


async def follow_up_loop(bot: Bot) -> None:
    """Runs forever; sends follow-up messages when their time comes.

    Grouped by telegram_id: a user can rack up several completed sessions
    due for a check-in around the same time (e.g. a few test consultations
    run close together) — that used to fire one near-identical "как
    самочувствие?" message per session (verified live: 4 in a row). One
    combined message per user instead, listing every pending complaint."""
    logging.info("Follow-up loop started")
    while True:
        await asyncio.sleep(FOLLOWUP_CHECK_INTERVAL)
        try:
            pending = await get_pending_followups()

            by_user: dict[int, list[tuple[int, str, str]]] = {}
            for session_id, telegram_id, complaint, created_at in pending:
                by_user.setdefault(telegram_id, []).append((session_id, complaint, created_at))

            for telegram_id, sessions in by_user.items():
                session_ids = [s[0] for s in sessions]

                if len(sessions) == 1:
                    _, complaint, created_at = sessions[0]
                    date_str = (created_at or "")[:10]
                    text = (
                        "👋 Добрый день!\n\n"
                        f"Недавно ({date_str}) вы обращались ко мне с жалобой:\n"
                        f"<i>«{_short(complaint)}»</i>\n\n"
                        "Как вы себя чувствуете сейчас? Помогли ли рекомендации?"
                    )
                else:
                    items = "\n".join(
                        f"• ({(created_at or '')[:10]}) «{_short(complaint)}»"
                        for _, complaint, created_at in sessions
                    )
                    text = (
                        "👋 Добрый день!\n\n"
                        "Недавно вы обращались ко мне с несколькими жалобами:\n"
                        f"{items}\n\n"
                        "Как вы себя чувствуете сейчас? Помогли ли рекомендации?"
                    )

                try:
                    await bot.send_message(
                        telegram_id,
                        text,
                        parse_mode="HTML",
                        reply_markup=followup_keyboard(session_ids),
                    )
                    for session_id in session_ids:
                        await mark_followup_sent(session_id)
                    logging.info(f"Follow-up sent to {telegram_id} (sessions {session_ids})")
                except Exception as e:
                    logging.warning(f"Could not send follow-up to {telegram_id}: {e}")
        except Exception as e:
            logging.error(f"Follow-up loop error: {e}")


# ── Callback handlers ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("fu:better:"))
async def cb_feeling_better(call: CallbackQuery) -> None:
    await call.message.edit_text(
        "😊 Очень рад слышать, что вам лучше!\n\n"
        "Если что-то снова побеспокоит — просто напишите, я всегда здесь.",
        reply_markup=None,
    )
    await call.message.answer("Выберите действие 👇", reply_markup=main_menu())
    await call.answer()


@router.callback_query(F.data.startswith("fu:new:"))
async def cb_need_consultation(call: CallbackQuery, state: FSMContext) -> None:
    await call.message.edit_text(
        "Понял, давайте разберёмся 🩺\n\nРасскажите, что сейчас беспокоит?",
        reply_markup=None,
    )
    # Запускаем новую консультацию
    from aiogram.fsm.state import State, StatesGroup
    from handlers.consultation import Consultation
    await state.set_state(Consultation.active)
    await state.update_data(
        messages=[], question_count=0,
        session_id=None, user_id=None,
        gender=None, age_range=None,
    )
    await call.answer()
