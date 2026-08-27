from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database.db import get_or_create_user, get_user_profile
from handlers.profile import ask_gender, ask_chronic_diseases
from keyboards.keyboards import main_menu

router = Router()

WELCOME = (
    "👋 Привет! Я <b>Мой Доктор</b> — ваш персональный помощник по здоровью.\n\n"
    "Что я умею:\n"
    "🤖 <b>Консультация с ИИ</b> — отвечу на вопросы о здоровье и помогу разобраться\n"
    "💊 <b>Подбор БАД</b> — безопасные рекомендации под вашу цель\n"
    "📊 <b>Трекер курса</b> — напомню принять добавки утром и вечером\n"
    "📔 <b>Дневник</b> — слежу за вашим самочувствием в динамике\n\n"
    "⚠️ <i>Важно: я не ставлю диагнозы и не заменяю очного врача.</i>"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await get_or_create_user(message.from_user.id, message.from_user.username)

    profile = await get_user_profile(message.from_user.id)

    await message.answer(WELCOME, parse_mode="HTML")

    if not profile or not profile["gender"] or not profile["age_range"]:
        # First-time user — full onboarding
        await ask_gender(message, state)
    elif not profile.get("onboarding_done"):
        # Has gender/age but health questionnaire not completed
        await ask_chronic_diseases(message, state)
    else:
        await message.answer("Выберите действие 👇", reply_markup=main_menu())
