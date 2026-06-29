from aiogram import F, Router
from aiogram.types import Message

from database.db import get_or_create_user, get_user_sessions
from keyboards.keyboards import main_menu

router = Router()


@router.message(F.text == "📋 История")
async def show_history(message: Message) -> None:
    user_id = await get_or_create_user(message.from_user.id, message.from_user.username)
    sessions = await get_user_sessions(user_id, limit=5)

    if not sessions:
        await message.answer(
            "У вас пока нет истории обращений.\nНажмите «🩺 Начать консультацию».",
            reply_markup=main_menu(),
        )
        return

    lines = ["📋 <b>Последние обращения:</b>\n"]
    for i, (sid, complaint, summary, created_at) in enumerate(sessions, 1):
        date = (created_at or "")[:10] or "—"
        short = (complaint or "—")[:100]
        if complaint and len(complaint) > 100:
            short += "…"
        lines.append(f"<b>{i}. {date}</b>\n{short}\n")

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=main_menu())
