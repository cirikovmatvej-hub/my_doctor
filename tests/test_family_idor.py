"""
Regression test for the IDOR fixed in handlers/family.py: cb_family_view,
cb_family_delete, cb_family_delete_confirm and cb_family_edit used to fetch a
family member by the raw callback_data id without checking it belonged to
the calling Telegram user — any user could view/edit/delete anyone's health
profile by guessing an id. _owned_member_or_none() is the fix; these tests
drive it directly against a real (temp-file) SQLite db rather than mocking
aiogram's CallbackQuery, since the helper only touches call.from_user and
call.answer.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import database.db as db
from handlers.family import _owned_member_or_none


def _fake_call(telegram_id: int, username: str = "tester") -> MagicMock:
    call = MagicMock()
    call.from_user.id = telegram_id
    call.from_user.username = username
    call.answer = AsyncMock()
    return call


def _make_db(tmp_path, name="family_idor.db"):
    db.DATABASE_PATH = str(tmp_path / name)


def test_owner_can_access_their_own_family_member(tmp_path):
    _make_db(tmp_path)

    async def run():
        await db.init_db()
        owner_id = await db.get_or_create_user(111, "owner")
        member_id = await db.create_family_member(owner_id, "Ваня", "сын")

        call = _fake_call(111, "owner")
        member = await _owned_member_or_none(call, member_id)

        assert member is not None
        assert member["id"] == member_id
        call.answer.assert_not_called()

    asyncio.run(run())


def test_other_user_is_denied_access_to_someone_elses_family_member(tmp_path):
    _make_db(tmp_path)

    async def run():
        await db.init_db()
        owner_id = await db.get_or_create_user(111, "owner")
        member_id = await db.create_family_member(owner_id, "Ваня", "сын")

        attacker_call = _fake_call(222, "attacker")
        member = await _owned_member_or_none(attacker_call, member_id)

        assert member is None
        attacker_call.answer.assert_awaited_once()
        assert "не ваш" in attacker_call.answer.call_args.args[0]

    asyncio.run(run())


def test_nonexistent_member_id_is_reported_as_not_found(tmp_path):
    _make_db(tmp_path)

    async def run():
        await db.init_db()
        call = _fake_call(111, "someone")
        member = await _owned_member_or_none(call, 999999)

        assert member is None
        attacker_msg = call.answer.call_args.args[0]
        assert "не найден" in attacker_msg

    asyncio.run(run())
