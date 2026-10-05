"""
Users who signed in through the iOS app have no telegram_id. The bot's
background loops used to pick their rows up and try to message None — the
follow-up was never marked sent, so it was retried (and logged) every cycle
forever. Those queries must skip app-only users; the app schedules its own
notifications locally.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import aiosqlite

import database.db as db


def _make_db(tmp_path):
    db.DATABASE_PATH = str(tmp_path / "loops.db")


async def _app_and_telegram_user():
    await db.init_db()
    app_user = await db.get_or_create_user_by_apple_sub("apple-sub-1")
    tg_user = await db.get_or_create_user(555, "tg")
    return app_user, tg_user


def test_followups_skip_app_only_users(tmp_path):
    _make_db(tmp_path)

    async def run():
        app_user, tg_user = await _app_and_telegram_user()
        for uid in (app_user, tg_user):
            sid = await db.create_session(uid, "болит голова")
            await db.update_session_summary(sid, "ok")
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            await conn.execute("UPDATE sessions SET follow_up_at=?", ((datetime.now() - timedelta(hours=1)).isoformat(),))
            await conn.commit()
        return await db.get_pending_followups()

    pending = asyncio.run(run())
    assert [row[1] for row in pending] == [555]


def test_tracker_reminders_skip_app_only_users(tmp_path):
    _make_db(tmp_path)

    async def run():
        app_user, tg_user = await _app_and_telegram_user()
        for uid in (app_user, tg_user):
            # 3-day course: inside the "ending soon" window straight away, so
            # the near-end query has rows for both users to (not) return.
            await db.create_tracking(uid, "magnesium", 3, "09:00", None)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        # make "now" land exactly on the reminder time in each user's (default UTC+3) local day
        local = now_utc + timedelta(hours=3)
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            await conn.execute("UPDATE product_tracking SET reminder_time_1=?", (local.strftime("%H:%M"),))
            await conn.commit()
        return await db.get_due_reminders(now_utc), await db.get_near_end_courses()

    due, near_end = asyncio.run(run())
    assert [row[1] for row in due] == [555]
    assert [row[1] for row in near_end] == [555]


def test_appointment_loops_skip_app_only_users(tmp_path):
    _make_db(tmp_path)

    async def run():
        app_user, tg_user = await _app_and_telegram_user()
        past = datetime.now() - timedelta(hours=1)
        for uid in (app_user, tg_user):
            fid = await db.create_appointment_followup(uid, "therapist", past)
            await db.set_appointment_reminder(fid, past)
        now = datetime.now()
        return await db.get_due_appointment_asks(now), await db.get_due_appointment_reminders(now)

    asks, reminders = asyncio.run(run())
    assert [row[1] for row in asks] == [555]
    assert [row[1] for row in reminders] == [555]


def test_reminder_loop_does_not_message_app_only_users(tmp_path, monkeypatch):
    """A finished app-only course comes back from complete_finished_trackings
    with telegram_id None; the loop must skip it, not call send_message(None)."""
    import handlers.tracker as tracker_handlers

    _make_db(tmp_path)
    monkeypatch.setattr(tracker_handlers, "REMINDER_CHECK_INTERVAL", 0)

    class FakeBot:
        def __init__(self):
            self.chat_ids = []

        async def send_message(self, chat_id, *args, **kwargs):
            self.chat_ids.append(chat_id)

    async def run():
        app_user, tg_user = await _app_and_telegram_user()
        today = datetime.now().strftime("%Y-%m-%d")
        for uid in (app_user, tg_user):
            tid = await db.create_tracking(uid, "magnesium", 1, None, None)
            await db.log_intake(tid, today, "1", "taken")
        bot = FakeBot()
        try:
            await asyncio.wait_for(tracker_handlers.reminder_loop(bot), timeout=1.0)
        except asyncio.TimeoutError:
            pass  # the loop never returns on its own
        return bot.chat_ids

    assert asyncio.run(run()) == [555]
