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

async def follow_up_loop(bot: Bot) -> None:
    """Runs forever; sends follow-up messages when their time comes."""
    logging.info("Follow-up loop started")
    while True:
        await asyncio.sleep(FOLLOWUP_CHECK_INTERVAL)
        try:
            pending = await get_pending_followups()
            for session_id, telegram_id, complaint, created_at in pending:
                date_str = (created_at or "")[:10]
                short_complaint = (complaint or "ваша жалоба")[:80]
                if complaint and len(complaint) > 80:
                    short_complaint += "…"

                text = (
                    "👋 Добрый день!\n\n"
                    f"Недавно ({date_str}) вы обращались ко мне с жалобой:\n"
                    f"<i>«{short_complaint}»</i>\n\n"
                    "Как вы себя чувствуете сейчас? Помогли ли рекомендации?"
                )
                try:
                    await bot.send_message(
                        telegram_id,
                        text,
                        parse_mode="HTML",
                        reply_markup=followup_keyboard(session_id),
                    )
                    await mark_followup_sent(session_id)
                    logging.info(f"Follow-up sent to {telegram_id} (session {session_id})")
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
