"""Diary API: validation, client-supplied date, and the per-course insights."""
import asyncio
from datetime import date, timedelta

import database.db as db
from api.deps import get_current_user
from api.main import app
from data.diary_insights import course_correlations
from fastapi.testclient import TestClient


def _client(tmp_path):
    db.DATABASE_PATH = str(tmp_path / "diary.db")

    async def setup():
        await db.init_db()
        return await db.get_or_create_user(111, "owner")

    uid = asyncio.run(setup())
    app.dependency_overrides[get_current_user] = lambda: uid
    return uid, TestClient(app)


def _entry(**over):
    return {"sleep_quality": 3, "energy_level": 3, "stress_level": 3, "bads_taken": False, **over}


def test_rejects_out_of_range_ratings(tmp_path):
    _, client = _client(tmp_path)
    try:
        assert client.put("/diary/today", json=_entry(sleep_quality=0)).status_code == 422
        assert client.put("/diary/today", json=_entry(stress_level=6)).status_code == 422
        assert client.put("/diary/today", json=_entry()).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_entry_is_saved_under_the_clients_date(tmp_path):
    _, client = _client(tmp_path)
    try:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        saved = client.put("/diary/today", json=_entry(date=yesterday)).json()
        assert saved["entry_date"] == yesterday
        assert client.get("/diary").json()[0]["entry_date"] == yesterday
        assert client.put("/diary/today", json=_entry(date="2000-01-01")).status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_history_can_span_thirty_days(tmp_path):
    uid, client = _client(tmp_path)

    async def seed():
        for i in range(40):
            d = (date.today() - timedelta(days=i)).isoformat()
            await db.save_diary_entry(uid, d, 3, 3, 3, 0, None)

    asyncio.run(seed())
    try:
        assert len(client.get("/diary").json()) == 7
        assert len(client.get("/diary?limit=30").json()) == 30
        assert len(client.get("/diary?limit=100000").json()) == 40   # capped, not unbounded
    finally:
        app.dependency_overrides.clear()


def test_insights_report_what_changed_since_a_course_started(tmp_path):
    uid, client = _client(tmp_path)
    start = date.today() - timedelta(days=5)

    async def seed():
        # 5 days before the course: poor sleep; 6 days from its start on: good sleep
        for i in range(10, 5, -1):
            await db.save_diary_entry(uid, (date.today() - timedelta(days=i)).isoformat(), 2, 3, 3, 0, None)
        for i in range(5, -1, -1):
            await db.save_diary_entry(uid, (date.today() - timedelta(days=i)).isoformat(), 4, 3, 3, 0, None)
        await db.create_tracking(uid, "magnesium", 30)
        import aiosqlite
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            await conn.execute("UPDATE product_tracking SET start_date=?", (start.isoformat(),))
            await conn.commit()

    asyncio.run(seed())
    try:
        body = client.get("/diary/insights").json()
    finally:
        app.dependency_overrides.clear()

    assert [c["start_date"] for c in body["courses"]] == [start.isoformat()]
    (corr,) = body["correlations"]
    assert [(c["metric"], c["before"], c["after"]) for c in corr["changes"]] == [("sleep", 2.0, 4.0)]


def test_correlations_need_enough_data_on_both_sides_and_a_real_change():
    def row(d, sleep, energy=3, stress=3):
        return (d, sleep, energy, stress, 0, None)

    trackings = [(1, "magnesium", "2026-01-10", "active", None)]
    too_few_after = [row(f"2026-01-0{i}", 2) for i in range(1, 6)] + [row("2026-01-10", 5), row("2026-01-11", 5)]
    assert course_correlations(too_few_after, trackings) == []

    no_change = [row(f"2026-01-0{i}", 3) for i in range(1, 6)] + [row(f"2026-01-1{i}", 3) for i in range(0, 4)]
    assert course_correlations(no_change, trackings) == []

    small_shift = [row(f"2026-01-0{i}", 3) for i in range(1, 6)] + [row(f"2026-01-1{i}", 3.2) for i in range(0, 4)]
    assert course_correlations(small_shift, trackings) == []
