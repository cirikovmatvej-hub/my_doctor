"""
Regression tests for QR/deep-link acquisition tracking (database/db.py's
user_exists/log_acquisition_event/get_acquisition_stats, and handlers/admin.py's
/stats). No pytest-asyncio dependency: each test drives its own asyncio.run(),
matching this suite's synchronous style (see tests/test_fsm_storage.py).
"""
import asyncio

import database.db as db
import handlers.admin as admin


def _fresh_db(tmp_path, name="acq_test.db"):
    db.DATABASE_PATH = str(tmp_path / name)


def test_scans_and_new_users_are_counted_separately(tmp_path):
    """A returning user re-scanning the same QR bumps the scan count but not
    the unique-new-user count — that distinction is the whole point."""
    _fresh_db(tmp_path)

    async def run():
        await db.init_db()
        assert await db.get_acquisition_stats() == []

        is_new = not await db.user_exists(111)
        await db.log_acquisition_event(111, "qr_magnesium", is_new)
        await db.get_or_create_user(111, "alice")

        is_new_again = not await db.user_exists(111)
        await db.log_acquisition_event(111, "qr_magnesium", is_new_again)

        stats = {s: (scans, new) for s, scans, new in await db.get_acquisition_stats()}
        assert stats["qr_magnesium"] == (2, 1)

    asyncio.run(run())


def test_different_sources_are_tracked_independently(tmp_path):
    _fresh_db(tmp_path)

    async def run():
        await db.init_db()
        for telegram_id, source in [(1, "qr_magnesium"), (2, "qr_collagen"), (3, "qr_collagen")]:
            is_new = not await db.user_exists(telegram_id)
            await db.log_acquisition_event(telegram_id, source, is_new)
            await db.get_or_create_user(telegram_id, f"user{telegram_id}")

        stats = {s: (scans, new) for s, scans, new in await db.get_acquisition_stats()}
        assert stats["qr_magnesium"] == (1, 1)
        assert stats["qr_collagen"] == (2, 2)

    asyncio.run(run())


def test_user_exists_reflects_actual_row_presence(tmp_path):
    _fresh_db(tmp_path)

    async def run():
        await db.init_db()
        assert await db.user_exists(999) is False
        await db.get_or_create_user(999, "carl")
        assert await db.user_exists(999) is True

    asyncio.run(run())


# ── /stats command ──────────────────────────────────────────────────────────

class _FakeUser:
    def __init__(self, telegram_id):
        self.id = telegram_id


class _FakeMessage:
    def __init__(self, telegram_id):
        self.from_user = _FakeUser(telegram_id)
        self.sent = []

    async def answer(self, text, **kwargs):
        self.sent.append(text)


def test_stats_command_is_silent_for_non_admins(tmp_path, monkeypatch):
    _fresh_db(tmp_path)
    monkeypatch.setattr(admin, "ADMIN_TELEGRAM_IDS", {608451729})

    async def run():
        await db.init_db()
        msg = _FakeMessage(telegram_id=12345)  # not an admin
        await admin.cmd_stats(msg)
        assert msg.sent == []

    asyncio.run(run())


def test_stats_command_shows_totals_for_admins(tmp_path, monkeypatch):
    _fresh_db(tmp_path)
    monkeypatch.setattr(admin, "ADMIN_TELEGRAM_IDS", {608451729})

    async def run():
        await db.init_db()
        await db.log_acquisition_event(1, "qr_magnesium", True)
        await db.log_acquisition_event(2, "qr_magnesium", True)
        await db.log_acquisition_event(3, "qr_collagen", True)

        msg = _FakeMessage(telegram_id=608451729)  # is an admin
        await admin.cmd_stats(msg)
        assert len(msg.sent) == 1
        text = msg.sent[0]
        assert "qr_magnesium" in text and "qr_collagen" in text
        assert "переходов: 2" in text  # magnesium row
        assert "Итого" in text

    asyncio.run(run())
