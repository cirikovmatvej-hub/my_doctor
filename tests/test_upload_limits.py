"""
Regression tests for the file-size cap and per-user cooldown on photo/PDF
uploads in handlers/consultation.py: previously any authenticated user could
send unlimited full-resolution photos/PDFs back to back, each one triggering
a Groq vision/text call against a shared free-tier daily token quota that's
already noted elsewhere in this codebase as easy to exhaust.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import handlers.consultation as consultation
from handlers.consultation import (
    MAX_UPLOAD_SIZE_BYTES, _process_pdf, _process_photo,
)


def _fake_message(telegram_id: int, *, photo_size: int | None = None,
                   doc_size: int | None = None, mime: str = "application/pdf") -> MagicMock:
    message = MagicMock()
    message.from_user.id = telegram_id
    message.answer = AsyncMock()
    if photo_size is not None:
        photo = MagicMock()
        photo.file_size = photo_size
        message.photo = [photo]
    if doc_size is not None:
        message.document.file_size = doc_size
        message.document.mime_type = mime
    return message


def setup_function():
    # This module-level state is exactly what's under test — reset it between
    # tests so cooldowns from one test don't leak into the next.
    consultation._last_upload_at.clear()


def test_oversized_photo_is_rejected_without_calling_the_ai():
    message = _fake_message(111, photo_size=MAX_UPLOAD_SIZE_BYTES + 1)
    with patch("handlers.consultation.analyze_photo", AsyncMock(side_effect=AssertionError("should not be called"))):
        asyncio.run(_process_photo(message, state=None))
    message.answer.assert_awaited_once()
    assert "большой" in message.answer.call_args.args[0]


def test_oversized_pdf_is_rejected_without_calling_the_ai():
    message = _fake_message(111, doc_size=MAX_UPLOAD_SIZE_BYTES + 1)
    with patch("handlers.consultation.analyze_lab_text", AsyncMock(side_effect=AssertionError("should not be called"))):
        asyncio.run(_process_pdf(message, state=None))
    message.answer.assert_awaited_once()
    assert "большой" in message.answer.call_args.args[0]


def test_second_upload_within_cooldown_is_rejected():
    consultation._mark_upload(222)
    message = _fake_message(222, photo_size=1000)
    with patch("handlers.consultation.analyze_photo", AsyncMock(side_effect=AssertionError("should not be called"))):
        asyncio.run(_process_photo(message, state=None))
    message.answer.assert_awaited_once()
    assert "Подождите" in message.answer.call_args.args[0]


def test_upload_allowed_again_after_cooldown_elapses():
    consultation._mark_upload(333)
    # Simulate the cooldown having already elapsed instead of sleeping in the test.
    consultation._last_upload_at[333] -= 9999

    message = _fake_message(333, photo_size=1000)
    fake_bot = AsyncMock()
    fake_bot.get_file = AsyncMock(return_value=MagicMock(file_path="x"))
    message.bot = fake_bot

    async def run():
        with patch("handlers.consultation.analyze_photo", AsyncMock(return_value={
            "text": "ok", "doctor_specialty": None,
            "bad_recommendation": None, "general_supplement_suggestion": None,
        })), patch("handlers.consultation.get_user_profile", AsyncMock(return_value=None)), \
             patch("handlers.consultation.get_or_create_user", AsyncMock(return_value=1)), \
             patch("handlers.consultation.schedule_appointment_followup", AsyncMock()):
            await _process_photo(message, state=MagicMock(
                get_data=AsyncMock(return_value={}), clear=AsyncMock(),
            ))

    asyncio.run(run())
    # Cooldown rejection message never sent — the upload went through to the
    # download step instead (get_file was called).
    fake_bot.get_file.assert_awaited_once()
