"""
Regression tests for the IDOR fixed in api/routers/tracker.py (POST
/tracker/{id}/intake) and api/routers/appointment.py (PUT
/appointments/{id}/status): both used to act on a resource id from the URL
without checking it belonged to the authenticated user_id. Auth itself
(api/security.py's Apple/JWT flow) is bypassed here via a dependency
override, same as FastAPI's own recommended testing pattern — this suite is
only exercising the ownership check added on top.

get_current_user resolves to the internal users.id (not a Telegram id), so
the dependency override must return that same internal id — these tests
create the owner via get_or_create_user() first and reuse its return value,
rather than a made-up id, to avoid conflating the two.
"""
import asyncio
from datetime import datetime

import database.db as db
from api.deps import get_current_user
from api.main import app
from fastapi.testclient import TestClient


def _client_as(user_id: int) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(app)


def _make_db(tmp_path, name="api_idor.db"):
    db.DATABASE_PATH = str(tmp_path / name)


def test_cannot_log_intake_on_someone_elses_tracking(tmp_path):
    _make_db(tmp_path)

    async def setup():
        await db.init_db()
        owner_id = await db.get_or_create_user(111, "owner")
        attacker_id = await db.get_or_create_user(222, "attacker")
        tracking_id = await db.create_tracking(owner_id, "magnesium", 30, "09:00", None)
        return owner_id, attacker_id, tracking_id

    owner_id, attacker_id, tracking_id = asyncio.run(setup())

    try:
        attacker_client = _client_as(attacker_id)
        resp = attacker_client.post(
            f"/tracker/{tracking_id}/intake", json={"status": "taken", "slot": "1"}
        )
        assert resp.status_code == 404

        owner_client = _client_as(owner_id)
        resp_owner = owner_client.post(
            f"/tracker/{tracking_id}/intake", json={"status": "taken", "slot": "1"}
        )
        assert resp_owner.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_cannot_update_status_on_someone_elses_appointment(tmp_path):
    _make_db(tmp_path)

    async def setup():
        await db.init_db()
        owner_id = await db.get_or_create_user(111, "owner")
        attacker_id = await db.get_or_create_user(222, "attacker")
        followup_id = await db.create_appointment_followup(owner_id, "therapist", datetime.now())
        return owner_id, attacker_id, followup_id

    owner_id, attacker_id, followup_id = asyncio.run(setup())

    try:
        attacker_client = _client_as(attacker_id)
        resp = attacker_client.put(
            f"/appointments/{followup_id}/status", json={"status": "booked"}
        )
        assert resp.status_code == 404

        owner_client = _client_as(owner_id)
        resp_owner = owner_client.put(
            f"/appointments/{followup_id}/status", json={"status": "booked"}
        )
        assert resp_owner.status_code == 200
    finally:
        app.dependency_overrides.clear()
