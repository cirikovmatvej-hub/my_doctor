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
            await db.create_tracking(uid, "magnesium", 30, "09:00", None)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        # make "now" land exactly on the reminder time in each user's (default UTC+3) local day
        local = now_utc + timedelta(hours=3)
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            await conn.execute("UPDATE product_tracking SET reminder_time_1=?", (local.strftime("%H:%M"),))
            await conn.commit()
        return await db.get_due_reminders(now_utc), await db.get_near_end_courses()

    due, near_end = asyncio.run(run())
    assert [row[1] for row in due] == [555]
    assert all(row[1] == 555 for row in near_end)


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
