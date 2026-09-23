"""
DELETE /me — App Store review requires in-app account deletion. It has to
erase every table that hangs off the user, leave other users untouched, and
make the deleted account's (180-day) session token stop working.
"""
import asyncio
from datetime import datetime

import aiosqlite
from fastapi.testclient import TestClient

import api.security as security
import database.db as db
from api.main import app

# (table, column holding the user's id) — for tables reached through a parent, see _rows_for
USER_TABLES = [
    ("sessions", "user_id"),
    ("product_tracking", "user_id"),
    ("appointment_followups", "user_id"),
    ("family_members", "owner_user_id"),
    ("diary_entries", "user_id"),
    ("users", "id"),
]


async def _seed(apple_sub: str) -> int:
    """One of everything the app can create for a user."""
    uid = await db.get_or_create_user_by_apple_sub(apple_sub)
    session_id = await db.create_session(uid, "болит голова")
    await db.add_message(session_id, "user", "болит голова")
    await db.add_message(session_id, "assistant", "как давно?")
    tracking_id = await db.create_tracking(uid, "magnesium", 30, "09:00", None)
    await db.log_intake(tracking_id, "2026-09-23", "1", "taken")
    await db.create_appointment_followup(uid, "therapist", datetime.now())
    await db.create_family_member(uid, "Мама", "мама")
    await db.save_diary_entry(uid, "2026-09-23", 3, 3, 3, 0, None)
    return uid


async def _counts(uid: int) -> dict[str, int]:
    async with aiosqlite.connect(db.DATABASE_PATH) as conn:
        counts = {}
        for table, column in USER_TABLES:
            async with conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (uid,)) as cur:
                counts[table] = (await cur.fetchone())[0]
        async with conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id IN (SELECT id FROM sessions WHERE user_id=?)", (uid,)
        ) as cur:
            counts["messages"] = (await cur.fetchone())[0]
        async with conn.execute(
            "SELECT COUNT(*) FROM intake_logs WHERE tracking_id IN "
            "(SELECT id FROM product_tracking WHERE user_id=?)", (uid,)
        ) as cur:
            counts["intake_logs"] = (await cur.fetchone())[0]
        return counts


def _setup(tmp_path, monkeypatch):
    db.DATABASE_PATH = str(tmp_path / "delete.db")
    monkeypatch.setattr(security, "API_JWT_SECRET", "test-secret-test-secret-test-secret-32b")

    async def make():
        await db.init_db()
        return await _seed("apple-a"), await _seed("apple-b")

    return asyncio.run(make())


def _auth(uid: int) -> dict:
    return {"Authorization": f"Bearer {security.issue_session_token(uid)}"}


def test_delete_erases_everything_for_that_user_only(tmp_path, monkeypatch):
    victim, bystander = _setup(tmp_path, monkeypatch)
    before = asyncio.run(_counts(bystander))
    assert all(n >= 1 for n in asyncio.run(_counts(victim)).values())   # the seed really covers every table

    resp = TestClient(app).delete("/me", headers=_auth(victim))
    assert resp.status_code == 200

    assert asyncio.run(_counts(victim)) == {table: 0 for table in [*(t for t, _ in USER_TABLES), "messages", "intake_logs"]}
    assert asyncio.run(_counts(bystander)) == before


def test_deleted_accounts_token_stops_working(tmp_path, monkeypatch):
    victim, bystander = _setup(tmp_path, monkeypatch)
    client = TestClient(app)
    headers = _auth(victim)
    assert client.get("/me", headers=headers).status_code == 200

    client.delete("/me", headers=headers)

    # Would otherwise succeed and write rows for a user that no longer exists.
    assert client.get("/me", headers=headers).status_code == 401
    assert client.post("/tracker", headers=headers, json={"product_key": "magnesium"}).status_code == 401
    assert client.delete("/me", headers=headers).status_code == 401
    assert client.get("/me", headers=_auth(bystander)).status_code == 200


def test_signing_in_again_after_deletion_starts_a_fresh_account(tmp_path, monkeypatch):
    victim, _ = _setup(tmp_path, monkeypatch)
    TestClient(app).delete("/me", headers=_auth(victim))

    async def sign_in_again():
        uid = await db.get_or_create_user_by_apple_sub("apple-a")
        return uid, await db.get_user_profile_by_id(uid)

    new_uid, profile = asyncio.run(sign_in_again())
    assert new_uid != victim
    assert not profile["onboarding_done"]
    assert asyncio.run(_counts(new_uid))["sessions"] == 0


def test_a_deleted_users_id_is_never_handed_to_someone_else(tmp_path, monkeypatch):
    """Session tokens carry the user id. If the newest account is deleted and
    SQLite reused its id, the old token would sign the next new user in."""
    _, newest = _setup(tmp_path, monkeypatch)
    old_token_headers = _auth(newest)
    TestClient(app).delete("/me", headers=old_token_headers)

    async def sign_up():
        return await db.get_or_create_user_by_apple_sub("apple-c")

    newcomer = asyncio.run(sign_up())
    assert newcomer > newest
    assert TestClient(app).get("/me", headers=old_token_headers).status_code == 401
