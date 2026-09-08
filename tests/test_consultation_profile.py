"""
Regression test for handlers/consultation.py:224 — when the AI ignores the
"give a recommendation now" hint and still returns type=="question" even
after question_count hit MAX_QUESTIONS, the retry call to _force_recommendation
used to be made without the patient profile, silently dropping contraindication
data (allergies, chronic diseases, pregnancy) from both the system prompt and
the check_bad_safety tool call for the final recommendation shown to the user.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import database.db as db
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from handlers.consultation import Consultation, handle_symptom


def _fake_message(telegram_id: int, text: str, username: str = "tester") -> MagicMock:
    message = MagicMock()
    message.text = text
    message.from_user.id = telegram_id
    message.from_user.username = username
    message.answer = AsyncMock()
    return message


def _make_db(tmp_path, name="consultation_profile.db"):
    db.DATABASE_PATH = str(tmp_path / name)


def test_forced_recommendation_retry_forwards_profile(tmp_path):
    _make_db(tmp_path)
    telegram_id = 111

    async def setup():
        await db.init_db()
        await db.get_or_create_user(telegram_id, "owner")
        await db.update_user_profile(telegram_id, "male", "30_45")
        await db.update_user_health_profile(
            telegram_id,
            chronic_diseases="астма",
            allergies="пенициллин",
            medications="нет",
            pregnancy="нет",
        )

    asyncio.run(setup())

    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=telegram_id, user_id=telegram_id)
    state = FSMContext(storage=storage, key=key)

    # Both calls return type=="question" — simulates the AI ignoring the
    # "give a recommendation now" hint even on the forced retry, which is
    # exactly the path that reaches the line-224 call.
    fake_ai = AsyncMock(return_value={"type": "question", "text": "Уточните ещё"})

    async def run():
        await state.set_state(Consultation.active)
        await state.update_data(
            messages=[{"role": "user", "content": "болит голова"}],
            question_count=999,  # >= MAX_QUESTIONS, forces the recommendation path
            session_id=None, user_id=None,
            gender=None, age_range=None, profile=None, profile_ready=False,
        )
        message = _fake_message(telegram_id, "ещё жалоба")
        with patch("handlers.consultation.analyze_symptoms", fake_ai):
            await handle_symptom(message, state)

    asyncio.run(run())

    real_profile = asyncio.run(db.get_user_profile(telegram_id))

    assert fake_ai.await_count == 2
    for call in fake_ai.await_args_list:
        assert call.kwargs.get("profile") == real_profile
        assert real_profile["allergies"] == "пенициллин"
