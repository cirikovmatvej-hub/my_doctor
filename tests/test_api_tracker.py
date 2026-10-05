"""
Tracker API parity with the bot: custom (non-catalog) courses, stopping a
course, past-course history, and courses that finish themselves once the last
intake is logged. Intake dates come from the client (its local calendar day).
"""
import asyncio
from datetime import date, timedelta

import database.db as db
from api.deps import get_current_user
from api.main import app
from fastapi.testclient import TestClient


def _client_as(user_id: int) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(app)


def _make_users(tmp_path, count=1):
    db.DATABASE_PATH = str(tmp_path / "tracker.db")

    async def setup():
        await db.init_db()
        return [await db.get_or_create_user(100 + i, f"u{i}") for i in range(count)]

    return asyncio.run(setup())


def test_custom_supplement_needs_a_course_length(tmp_path):
    (uid,) = _make_users(tmp_path)
    client = _client_as(uid)
    try:
        assert client.post("/tracker", json={"product_key": "Железо хелат"}).status_code == 422
        assert client.post("/tracker", json={"product_key": "Железо хелат", "course_days": 0}).status_code == 422
        assert client.post("/tracker", json={"product_key": "Железо хелат", "course_days": 366}).status_code == 422
        assert client.post("/tracker", json={"product_key": "x" * 101, "course_days": 30}).status_code == 422

        resp = client.post("/tracker", json={
            "product_key": "  Железо хелат ", "course_days": 30, "reminder_time_1": "09:00",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["full_name"] == "Железо хелат"       # stored trimmed, shown as typed
        assert body["emoji"] == "💊"
        assert body["course_days"] == 30

        listed = client.get("/tracker").json()
        assert [c["full_name"] for c in listed] == ["Железо хелат"]
    finally:
        app.dependency_overrides.clear()


def test_catalog_course_length_comes_from_the_catalog(tmp_path):
    (uid,) = _make_users(tmp_path)
    client = _client_as(uid)
    try:
        body = client.post("/tracker", json={"product_key": "magnesium", "course_days": 3}).json()
    finally:
        app.dependency_overrides.clear()

    assert body["course_days"] != 3
    assert body["full_name"] != "magnesium"


def test_stop_course_moves_it_to_history_and_only_for_the_owner(tmp_path):
    owner, attacker = _make_users(tmp_path, 2)
    try:
        owner_client = _client_as(owner)
        tid = owner_client.post("/tracker", json={"product_key": "magnesium"}).json()["id"]

        attacker_client = _client_as(attacker)
        assert attacker_client.delete(f"/tracker/{tid}").status_code == 404

        owner_client = _client_as(owner)
        assert owner_client.delete(f"/tracker/{tid}").status_code == 200
        assert owner_client.get("/tracker").json() == []
        history = owner_client.get("/tracker/history").json()
        assert [(h["id"], h["status"]) for h in history] == [(tid, "stopped")]

        # stopping twice must not rewrite the recorded outcome
        assert owner_client.delete(f"/tracker/{tid}").status_code == 409
        assert owner_client.delete("/tracker/99999").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_last_intake_completes_the_course(tmp_path):
    (uid,) = _make_users(tmp_path)
    client = _client_as(uid)
    try:
        today = date.today()
        # The course starts yesterday (the client's day), so yesterday's intake counts.
        tid = client.post("/tracker", json={
            "product_key": "Омега-3", "course_days": 2,
            "date": (today - timedelta(days=1)).isoformat(),
        }).json()["id"]

        first = client.post(f"/tracker/{tid}/intake", json={
            "status": "taken", "slot": "1", "date": (today - timedelta(days=1)).isoformat(),
        }).json()
        assert (first["days_taken"], first["course_days"], first["course_completed"]) == (1, 2, False)
        assert len(client.get("/tracker").json()) == 1

        second = client.post(f"/tracker/{tid}/intake", json={
            "status": "taken", "slot": "1", "date": today.isoformat(),
        }).json()
        assert (second["days_taken"], second["course_completed"]) == (2, True)

        assert client.get("/tracker").json() == []
        history = client.get("/tracker/history").json()
        assert [(h["full_name"], h["status"], h["days_taken"]) for h in history] == [("Омега-3", "completed", 2)]
    finally:
        app.dependency_overrides.clear()


def test_skipped_intake_does_not_count_toward_the_course(tmp_path):
    (uid,) = _make_users(tmp_path)
    client = _client_as(uid)
    try:
        tid = client.post("/tracker", json={"product_key": "Омега-3", "course_days": 1}).json()["id"]
        skipped = client.post(f"/tracker/{tid}/intake", json={"status": "skip", "slot": "1"}).json()
    finally:
        app.dependency_overrides.clear()

    assert (skipped["days_taken"], skipped["course_completed"]) == (0, False)


def test_intake_date_is_the_clients_day_and_sanity_checked(tmp_path):
    (uid,) = _make_users(tmp_path)
    client = _client_as(uid)
    try:
        tid = client.post("/tracker", json={"product_key": "magnesium"}).json()["id"]
        url = f"/tracker/{tid}/intake"
        assert client.post(url, json={"status": "taken", "slot": "1", "date": "not-a-date"}).status_code == 422
        far = (date.today() - timedelta(days=30)).isoformat()
        assert client.post(url, json={"status": "taken", "slot": "1", "date": far}).status_code == 400
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert client.post(url, json={"status": "taken", "slot": "1", "date": yesterday}).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_course_starts_on_the_clients_day(tmp_path):
    (uid,) = _make_users(tmp_path)
    client = _client_as(uid)
    try:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        started = client.post("/tracker", json={"product_key": "magnesium", "date": yesterday}).json()
        assert started["start_date"] == yesterday
        assert client.get("/tracker").json()[0]["start_date"] == yesterday
        # Without a client date the server's day is used; a wild one is rejected.
        assert client.post("/tracker", json={"product_key": "collagen"}).json()["start_date"] == date.today().isoformat()
        far = (date.today() - timedelta(days=30)).isoformat()
        assert client.post("/tracker", json={"product_key": "magnesium", "date": far}).status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_an_intake_before_the_course_started_does_not_count(tmp_path):
    (uid,) = _make_users(tmp_path)
    client = _client_as(uid)
    try:
        tid = client.post("/tracker", json={"product_key": "Омега-3", "course_days": 5}).json()["id"]
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        out = client.post(f"/tracker/{tid}/intake", json={"status": "taken", "slot": "1", "date": yesterday}).json()
    finally:
        app.dependency_overrides.clear()
    assert out["days_taken"] == 0


def test_intake_input_is_validated(tmp_path):
    (uid,) = _make_users(tmp_path)
    client = _client_as(uid)
    try:
        tid = client.post("/tracker", json={"product_key": "magnesium"}).json()["id"]
        url = f"/tracker/{tid}/intake"
        assert client.post(url, json={"status": "maybe", "slot": "1"}).status_code == 422
        assert client.post(url, json={"status": "taken", "slot": "3"}).status_code == 422
        assert client.post(url, json={"status": "taken", "slot": "2"}).status_code == 200
        for bad_time in ("9:00", "25:00", "09:60", "morning"):
            resp = client.post("/tracker", json={"product_key": "collagen", "reminder_time_1": bad_time})
            assert resp.status_code == 422, bad_time
        assert client.post("/tracker", json={"product_key": "collagen", "reminder_time_1": "21:30"}).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_toggling_an_intake_overwrites_it_instead_of_stacking(tmp_path):
    (uid,) = _make_users(tmp_path)
    client = _client_as(uid)
    try:
        tid = client.post("/tracker", json={"product_key": "Омега-3", "course_days": 5}).json()["id"]
        url = f"/tracker/{tid}/intake"
        body = {"status": "taken", "slot": "1"}
        assert client.post(url, json=body).json()["days_taken"] == 1
        assert client.post(url, json=body).json()["days_taken"] == 1  # same slot, same day
        assert client.post(url, json={**body, "status": "skip"}).json()["days_taken"] == 0
        assert client.post(url, json=body).json()["days_taken"] == 1
    finally:
        app.dependency_overrides.clear()


def test_stopped_course_records_the_clients_day_and_rejects_further_intakes(tmp_path):
    (uid,) = _make_users(tmp_path)
    client = _client_as(uid)
    try:
        tid = client.post("/tracker", json={"product_key": "Омега-3", "course_days": 5}).json()["id"]
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert client.delete(f"/tracker/{tid}", params={"date": yesterday}).json() == {"status": "ok"}
        assert client.delete(f"/tracker/{tid}", params={"date": "garbage"}).status_code == 422
        resp = client.post(f"/tracker/{tid}/intake", json={"status": "taken", "slot": "1"})
        assert resp.status_code == 409
        assert client.delete(f"/tracker/{tid}").status_code == 409
    finally:
        app.dependency_overrides.clear()

    async def ended_at():
        async with db._connect() as conn:
            async with conn.execute("SELECT ended_at FROM product_tracking WHERE id=?", (tid,)) as cur:
                return (await cur.fetchone())[0]

    assert asyncio.run(ended_at()) == yesterday
