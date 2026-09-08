"""
Regression test for the IDOR fixed in handlers/appointment.py: cb_appt_booked,
cb_appt_not_booked, cb_appt_reason and cb_appt_remind used to act on a
followup_id taken straight from callback_data without checking it belonged
to the calling user. _owned_followup_or_none() is the fix.
"""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import database.db as db
from handlers.appointment import _owned_followup_or_none


def _fake_call(telegram_id: int, username: str = "tester") -> MagicMock:
    call = MagicMock()
    call.from_user.id = telegram_id
    call.from_user.username = username
    call.answer = AsyncMock()
    return call


def _make_db(tmp_path, name="appointment_idor.db"):
    db.DATABASE_PATH = str(tmp_path / name)


def test_owner_can_access_their_own_followup(tmp_path):
    _make_db(tmp_path)

    async def run():
        await db.init_db()
        owner_id = await db.get_or_create_user(111, "owner")
        followup_id = await db.create_appointment_followup(owner_id, "therapist", datetime.now())

        call = _fake_call(111, "owner")
        followup = await _owned_followup_or_none(call, followup_id)

        assert followup is not None
        assert followup["id"] == followup_id
        call.answer.assert_not_called()

    asyncio.run(run())


def test_other_user_is_denied_access_to_someone_elses_followup(tmp_path):
    _make_db(tmp_path)

    async def run():
        await db.init_db()
        owner_id = await db.get_or_create_user(111, "owner")
        followup_id = await db.create_appointment_followup(owner_id, "therapist", datetime.now())

        attacker_call = _fake_call(222, "attacker")
        followup = await _owned_followup_or_none(attacker_call, followup_id)

        assert followup is None
        attacker_call.answer.assert_awaited_once()
        assert "не ваша" in attacker_call.answer.call_args.args[0]

    asyncio.run(run())
