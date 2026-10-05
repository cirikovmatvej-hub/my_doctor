"""
Data-integrity guarantees of the shared DB layer: INSERT OR REPLACE only
upserts when a UNIQUE index exists, so the diary/intake tables carry one (and
the startup migration dedupes legacy rows first, keeping a VACUUM INTO backup);
writes for a user/session/course that no longer exists must report failure
instead of leaving orphan rows.
"""
import asyncio
import glob

import aiosqlite

import database.db as db


def _use_db(tmp_path, name="integrity.db"):
    db.DATABASE_PATH = str(tmp_path / name)


async def _count(table: str) -> int:
    async with aiosqlite.connect(db.DATABASE_PATH) as conn:
        async with conn.execute(f"SELECT COUNT(*) FROM {table}") as cur:
            return (await cur.fetchone())[0]


def test_saving_the_diary_twice_for_a_day_keeps_one_row_with_the_latest_values(tmp_path):
    _use_db(tmp_path)

    async def run():
        await db.init_db()
        uid = await db.get_or_create_user(1, "a")
        assert await db.save_diary_entry(uid, "2026-10-01", 2, 2, 2, 0, None)
        assert await db.save_diary_entry(uid, "2026-10-01", 5, 4, 1, 1, "лучше")
        rows = await db.get_diary_entries(uid, limit=10)
        return rows, await _count("diary_entries")

    rows, count = asyncio.run(run())
    assert count == 1
    assert [(r[0], r[1], r[2], r[3], r[4]) for r in rows] == [("2026-10-01", 5, 4, 1, 1)]


def test_logging_the_same_slot_twice_keeps_one_row(tmp_path):
    _use_db(tmp_path)

    async def run():
        await db.init_db()
        uid = await db.get_or_create_user(1, "a")
        tid = await db.create_tracking(uid, "magnesium", 30)
        assert await db.log_intake(tid, "2026-10-01", "1", "taken")
        assert await db.log_intake(tid, "2026-10-01", "1", "skip")
        assert await db.log_intake(tid, "2026-10-01", "2", "taken")
        return await _count("intake_logs")

    assert asyncio.run(run()) == 2


def test_writes_for_things_that_no_longer_exist_report_failure_and_leave_no_rows(tmp_path):
    _use_db(tmp_path)

    async def run():
        await db.init_db()
        uid = await db.get_or_create_user(1, "a")
        sid = await db.create_session(uid, "x")
        tid = await db.create_tracking(uid, "magnesium", 30)
        await db.delete_user_account(uid)
        results = (
            await db.add_message(sid, "user", "hi"),
            await db.add_messages(sid, [("user", "hi"), ("assistant", "{}")]),
            await db.log_intake(tid, "2026-10-01", "1", "taken"),
            await db.save_diary_entry(uid, "2026-10-01", 3, 3, 3, 0, None),
        )
        counts = [await _count(t) for t in ("messages", "intake_logs", "diary_entries")]
        return results, counts

    results, counts = asyncio.run(run())
    assert results == (False, False, False, False)
    assert counts == [0, 0, 0]


def test_add_messages_stores_the_whole_turn_together(tmp_path):
    _use_db(tmp_path)

    async def run():
        await db.init_db()
        uid = await db.get_or_create_user(1, "a")
        sid = await db.create_session(uid, "x")
        assert await db.add_messages(sid, [("user", "q"), ("assistant", "a")])
        return await _count("messages")

    assert asyncio.run(run()) == 2


def test_startup_migration_dedupes_legacy_rows_and_backs_up_first(tmp_path):
    """A DB created before the unique indexes existed may hold duplicates; the
    index creation would fail on them, so init_db keeps the newest row per key
    (and snapshots the file with VACUUM INTO before deleting anything)."""
    _use_db(tmp_path)

    async def legacy():
        await db.init_db()
        uid = await db.get_or_create_user(1, "a")
        tid = await db.create_tracking(uid, "magnesium", 30)
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            await conn.execute("DROP INDEX uq_diary_user_date")
            await conn.execute("DROP INDEX uq_intake_tracking_date_slot")
            for sleep in (1, 2, 3):
                await conn.execute(
                    "INSERT INTO diary_entries (user_id, entry_date, sleep_quality, energy_level, stress_level, bads_taken) "
                    "VALUES (?, '2026-10-01', ?, 3, 3, 0)", (uid, sleep),
                )
            for status in ("taken", "skip"):
                await conn.execute(
                    "INSERT INTO intake_logs (tracking_id, log_date, time_of_day, status) VALUES (?, '2026-10-01', '1', ?)",
                    (tid, status),
                )
            await conn.commit()
        assert await _count("diary_entries") == 3
        await db.init_db()  # the "restart"
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            async with conn.execute("SELECT sleep_quality FROM diary_entries") as cur:
                diary = await cur.fetchall()
            async with conn.execute("SELECT status FROM intake_logs") as cur:
                intake = await cur.fetchall()
        return diary, intake

    diary, intake = asyncio.run(legacy())
    assert diary == [(3,)]            # newest wins
    assert intake == [("skip",)]
    backups = glob.glob(f"{db.DATABASE_PATH}.backup_dedupe_*")
    assert len(backups) == 1


def test_clean_database_makes_no_backup(tmp_path):
    _use_db(tmp_path)

    async def run():
        await db.init_db()
        await db.init_db()

    asyncio.run(run())
    assert glob.glob(f"{db.DATABASE_PATH}.backup_dedupe_*") == []


def test_a_bot_style_course_counts_an_intake_logged_the_same_day(tmp_path):
    """The bot starts a course with the server's date and logs intakes with the
    same clock — the intake on day one must count toward the course."""
    from datetime import datetime

    _use_db(tmp_path)

    async def run():
        await db.init_db()
        uid = await db.get_or_create_user(1, "a")
        tid = await db.create_tracking(uid, "magnesium", 30)
        await db.log_intake(tid, datetime.now().strftime("%Y-%m-%d"), "1", "taken")
        return await db.get_days_taken(tid)

    assert asyncio.run(run()) == 1
