"""
Web sign-in: email + one-time 6-digit code. Covers the happy path, that a code
is single-use / expires / locks after too many wrong guesses (including
concurrent ones), the resend cooldown and hourly cap, the per-IP limiter, and
the "mail not configured" behaviour. Sending is stubbed — the code is captured
in-process instead.
"""
import asyncio
import logging

import aiosqlite
import jwt
import pytest
from fastapi.testclient import TestClient

import api.routers.auth as auth
import api.security as security
import database.db as db
from api.main import app

SECRET = "test-secret-for-web-login"


@pytest.fixture
def web(tmp_path, monkeypatch):
    db.DATABASE_PATH = str(tmp_path / "web.db")
    asyncio.run(db.init_db())
    monkeypatch.setattr(auth, "API_JWT_SECRET", SECRET)
    monkeypatch.setattr(security, "API_JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "_request_limiter", auth._IpLimiter(max_hits=10, window=3600))
    monkeypatch.setattr(auth, "_verify_limiter", auth._IpLimiter(max_hits=60, window=3600))

    sent: list[tuple[str, str]] = []

    async def fake_send(to, code, ttl_minutes=10):
        sent.append((to, code))

    monkeypatch.setattr(auth, "send_login_code", fake_send)
    client = TestClient(app)
    client.sent = sent
    return client


def _sql(query, params=()):
    async def run():
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            await conn.execute(query, params)
            await conn.commit()
    asyncio.run(run())


def _login(client, email="user@example.com"):
    assert client.post("/auth/email/request", json={"email": email}).status_code == 200
    return client.sent[-1][1]


def test_code_logs_in_and_token_identifies_the_account(web):
    code = _login(web, "User@Example.COM")
    assert web.sent[-1][0] == "user@example.com"          # stored/sent lower-cased

    resp = web.post("/auth/email/verify", json={"email": " user@example.com ", "code": code})
    assert resp.status_code == 200
    body = resp.json()
    assert body["onboarding_done"] is False
    assert jwt.decode(body["access_token"], SECRET, algorithms=["HS256"])["sub"] == str(body["user_id"])

    # The token works against a protected endpoint.
    me = web.get("/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["user_id"] == body["user_id"]


def test_the_same_address_is_the_same_account(web):
    first = web.post("/auth/email/verify", json={"email": "a@example.com", "code": _login(web, "a@example.com")}).json()
    second_code = _login(web, "A@example.com") if _expire_cooldown() else None
    second = web.post("/auth/email/verify", json={"email": "A@example.com", "code": second_code}).json()
    other = web.post("/auth/email/verify", json={"email": "b@example.com", "code": _login(web, "b@example.com")}).json()
    assert first["user_id"] == second["user_id"] != other["user_id"]


def _expire_cooldown() -> bool:
    _sql("UPDATE email_login_codes SET last_sent_at = last_sent_at - 120")
    return True


def test_a_code_works_once(web):
    code = _login(web)
    assert web.post("/auth/email/verify", json={"email": "user@example.com", "code": code}).status_code == 200
    assert web.post("/auth/email/verify", json={"email": "user@example.com", "code": code}).status_code == 401


def test_wrong_codes_lock_the_code_even_for_the_right_answer(web):
    code = _login(web)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(db.CODE_MAX_ATTEMPTS):
        assert web.post("/auth/email/verify", json={"email": "user@example.com", "code": wrong}).status_code == 401
    assert web.post("/auth/email/verify", json={"email": "user@example.com", "code": code}).status_code == 401


def test_concurrent_guesses_cannot_exceed_the_attempt_limit(web):
    code = _login(web)
    wrong_hash = auth._code_hash("user@example.com", "000000" if code != "000000" else "111111")
    _sql("UPDATE email_login_codes SET expires_at = 2e12")

    async def burst():
        return await asyncio.gather(*[
            db.consume_email_code("user@example.com", wrong_hash, 1e12) for _ in range(20)
        ])

    assert not any(asyncio.run(burst()))

    async def attempts():
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            async with conn.execute("SELECT attempts FROM email_login_codes") as cur:
                return (await cur.fetchone())[0]

    assert asyncio.run(attempts()) == db.CODE_MAX_ATTEMPTS      # 20 racing guesses burned only 5
    assert web.post("/auth/email/verify", json={"email": "user@example.com", "code": code}).status_code == 401


def test_an_expired_code_is_rejected(web):
    code = _login(web)
    _sql("UPDATE email_login_codes SET expires_at = 1")
    assert web.post("/auth/email/verify", json={"email": "user@example.com", "code": code}).status_code == 401


def test_a_new_code_replaces_the_old_one(web):
    old = _login(web)
    _expire_cooldown()
    new = _login(web)
    if old != new:
        assert web.post("/auth/email/verify", json={"email": "user@example.com", "code": old}).status_code == 401
    assert web.post("/auth/email/verify", json={"email": "user@example.com", "code": new}).status_code == 200


def test_resend_cooldown_and_hourly_cap(web):
    assert web.post("/auth/email/request", json={"email": "user@example.com"}).status_code == 200
    again = web.post("/auth/email/request", json={"email": "user@example.com"})
    assert again.status_code == 429

    for _ in range(db.CODE_MAX_SENDS_PER_HOUR - 1):
        _expire_cooldown()
        assert web.post("/auth/email/request", json={"email": "user@example.com"}).status_code == 200
    _expire_cooldown()
    capped = web.post("/auth/email/request", json={"email": "user@example.com"})
    assert capped.status_code == 429 and "час" in capped.json()["detail"]


def test_malformed_input_is_rejected(web):
    for bad in ("nope", "a@b", "@example.com", "a b@example.com", "x" * 250 + "@example.com"):
        assert web.post("/auth/email/request", json={"email": bad}).status_code == 422, bad
    for bad_code in ("12345", "1234567", "abcdef", ""):
        assert web.post("/auth/email/verify", json={"email": "a@example.com", "code": bad_code}).status_code == 422, bad_code
    assert web.sent == []


def test_per_ip_limit_blocks_mail_spraying(web):
    for i in range(10):
        assert web.post("/auth/email/request", json={"email": f"user{i}@example.com"}).status_code == 200
    assert web.post("/auth/email/request", json={"email": "user99@example.com"}).status_code == 429


def test_forwarded_header_is_only_trusted_when_configured(web, monkeypatch):
    for i in range(10):
        assert web.post("/auth/email/request", json={"email": f"u{i}@example.com"}).status_code == 200
    spoofed = {"X-Forwarded-For": "203.0.113.9"}
    # Not trusted: the spoofed header doesn't buy a fresh quota.
    assert web.post("/auth/email/request", json={"email": "z1@example.com"}, headers=spoofed).status_code == 429
    # Behind our proxy the last entry is the real client, which has its own quota.
    monkeypatch.setattr(auth, "TRUST_PROXY_HEADERS", True)
    assert web.post("/auth/email/request", json={"email": "z2@example.com"}, headers=spoofed).status_code == 200


def test_without_smtp_the_endpoint_says_so(tmp_path, monkeypatch):
    db.DATABASE_PATH = str(tmp_path / "nomail.db")
    asyncio.run(db.init_db())
    monkeypatch.setattr(auth, "API_JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "_request_limiter", auth._IpLimiter(max_hits=10, window=3600))
    import api.mailer as mailer
    monkeypatch.setattr(mailer.config, "SMTP_HOST", "")
    monkeypatch.setattr(mailer.config, "WEB_DEV_PRINT_CODES", False)
    resp = TestClient(app).post("/auth/email/request", json={"email": "a@example.com"})
    assert resp.status_code == 503


def test_dev_mode_logs_the_code_instead_of_sending(tmp_path, monkeypatch, caplog):
    db.DATABASE_PATH = str(tmp_path / "devmail.db")
    asyncio.run(db.init_db())
    monkeypatch.setattr(auth, "API_JWT_SECRET", SECRET)
    monkeypatch.setattr(security, "API_JWT_SECRET", SECRET)
    monkeypatch.setattr(auth, "_request_limiter", auth._IpLimiter(max_hits=10, window=3600))
    import api.mailer as mailer
    monkeypatch.setattr(mailer.config, "SMTP_HOST", "")
    monkeypatch.setattr(mailer.config, "WEB_DEV_PRINT_CODES", True)
    client = TestClient(app)
    with caplog.at_level(logging.WARNING):
        assert client.post("/auth/email/request", json={"email": "a@example.com"}).status_code == 200
    code = next(r.getMessage().rsplit(": ", 1)[1] for r in caplog.records if "DEV sign-in code" in r.getMessage())
    assert client.post("/auth/email/verify", json={"email": "a@example.com", "code": code}).status_code == 200


def test_no_server_secret_means_no_login(web, monkeypatch):
    monkeypatch.setattr(auth, "API_JWT_SECRET", "")
    assert web.post("/auth/email/request", json={"email": "a@example.com"}).status_code == 503
    assert web.post("/auth/email/verify", json={"email": "a@example.com", "code": "123456"}).status_code == 503


def test_deleting_the_account_drops_a_pending_code(web):
    uid = web.post("/auth/email/verify", json={"email": "a@example.com", "code": _login(web, "a@example.com")}).json()["user_id"]
    _login(web, "a@example.com")  # a new pending code for the same address
    asyncio.run(db.delete_user_account(uid))

    async def codes():
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            async with conn.execute("SELECT COUNT(*) FROM email_login_codes") as cur:
                return (await cur.fetchone())[0]

    assert asyncio.run(codes()) == 0
