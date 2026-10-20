"""
The app's consultation endpoint must carry everything the bot's
build_recommendation_message() adds around the model's text — the mandatory
disclaimer, grounded safety warnings, the non-catalog supplement suggestion —
and must honor the same switches the bot does (doctor recommendations off,
follow-up only when the model asks for one). The model call itself is stubbed.
"""
import asyncio

import aiosqlite

import api.routers.consultation as consultation
import database.db as db
from api.deps import get_current_user
from api.main import app
from fastapi.testclient import TestClient


def _setup(tmp_path, monkeypatch, ai_reply: dict):
    db.DATABASE_PATH = str(tmp_path / "consult.db")

    async def fake_analyze(*args, **kwargs):
        return dict(ai_reply)

    monkeypatch.setattr(consultation, "analyze_symptoms", fake_analyze)

    async def make_user():
        await db.init_db()
        return await db.get_or_create_user(111, "owner")

    user_id = asyncio.run(make_user())
    app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(app)


def _send(client: TestClient, text="болит голова") -> dict:
    session_id = client.post("/consultations", json={}).json()["session_id"]
    resp = client.post(f"/consultations/{session_id}/messages", json={"text": text})
    assert resp.status_code == 200
    return {"session_id": session_id, **resp.json()}


def _follow_up_at(session_id: int):
    async def q():
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            async with conn.execute("SELECT follow_up_at FROM sessions WHERE id=?", (session_id,)) as cur:
                return (await cur.fetchone())[0]
    return asyncio.run(q())


RECOMMENDATION = {
    "type": "recommendation",
    "text": "Похоже на напряжение.",
    "doctor_specialty": "neurologist",
    "bad_recommendation": "magnesium",
    "general_supplement_suggestion": "омега-3",
    "is_lifestyle": False,
    "needs_followup": True,
    "_grounded_safety_warnings": ["магний: предупреждение А"],
    "_grounded_general_safety_warnings": ["омега-3: предупреждение Б"],
}


def test_recommendation_carries_disclaimer_warnings_and_general_supplement(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, RECOMMENDATION)
    try:
        body = _send(client)
    finally:
        app.dependency_overrides.clear()

    assert body["session_status"] == "completed"
    assert "не диагноз" in body["disclaimer"]
    assert "<i>" not in body["disclaimer"]  # the app renders plain text, not Telegram HTML
    assert body["general_supplement"] == "омега-3"
    assert body["safety_warnings"] == ["магний: предупреждение А", "омега-3: предупреждение Б"]
    assert body["bad"]["key"] == "magnesium"
    assert body["bad"]["default_times"] and body["bad"]["daily_doses"] >= 1   # enough to start a course from it


def test_warnings_only_ride_along_with_the_supplement_they_are_about(tmp_path, monkeypatch):
    reply = {**RECOMMENDATION, "bad_recommendation": None, "general_supplement_suggestion": None}
    client = _setup(tmp_path, monkeypatch, reply)
    try:
        body = _send(client)
    finally:
        app.dependency_overrides.clear()

    assert body["safety_warnings"] == []
    assert body["general_supplement"] is None


def test_question_turn_has_no_disclaimer(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, {"type": "question", "text": "Как давно?"})
    try:
        body = _send(client)
    finally:
        app.dependency_overrides.clear()

    assert body["session_status"] == "active"
    assert body["disclaimer"] is None


def test_doctor_hidden_while_doctor_recommendations_are_off(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, RECOMMENDATION)
    try:
        monkeypatch.setattr(consultation, "SHOW_DOCTOR_RECOMMENDATIONS", False)
        assert _send(client)["doctor"] is None

        monkeypatch.setattr(consultation, "SHOW_DOCTOR_RECOMMENDATIONS", True)
        assert _send(client)["doctor"]["specialty"] == "neurologist"
    finally:
        app.dependency_overrides.clear()


def test_followup_scheduled_only_when_model_asks(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, RECOMMENDATION)
    try:
        with_followup = _send(client)
        monkeypatch.setattr(consultation, "analyze_symptoms", _stub({**RECOMMENDATION, "needs_followup": False}))
        without_followup = _send(client)
    finally:
        app.dependency_overrides.clear()

    assert _follow_up_at(with_followup["session_id"]) is not None
    assert _follow_up_at(without_followup["session_id"]) is None


def test_emergency_shows_the_fixed_message_and_never_schedules_followup(tmp_path, monkeypatch):
    # Whatever the model wrote (here: nothing, as with the keyword backstop, or
    # chatter) the user always gets the same clear instructions.
    for model_text in ("", "Возможно, это просто мышечная боль."):
        client = _setup(tmp_path, monkeypatch, {"type": "emergency", "text": model_text, "needs_followup": True})
        try:
            body = _send(client, "боль в груди")
            transcript = client.get(f"/consultations/{body['session_id']}").json()
        finally:
            app.dependency_overrides.clear()

        assert body["type"] == "emergency"
        assert body["text"] == consultation.EMERGENCY_TEXT
        assert not body["text"].startswith("\n") and "112" in body["text"] and "103" in body["text"]
        assert body["disclaimer"] is None
        assert _follow_up_at(body["session_id"]) is None
        # history shows the same instructions, not an empty turn
        assert transcript["turns"][-1]["text"] == consultation.EMERGENCY_TEXT
        assert _summary(body["session_id"]) == consultation.EMERGENCY_SUMMARY


def _summary(session_id: int):
    async def q():
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            async with conn.execute("SELECT summary FROM sessions WHERE id=?", (session_id,)) as cur:
                return (await cur.fetchone())[0]
    return asyncio.run(q())


def _stub(reply: dict):
    async def fake_analyze(*args, **kwargs):
        return dict(reply)
    return fake_analyze


def test_a_failed_model_call_is_retryable_not_a_finished_consultation(tmp_path, monkeypatch):
    """When the model call fails the AI layer returns a canned "technical error,
    see a therapist" recommendation. The app must get an error instead — the
    session stays open, nothing is saved, and sending the same text again works
    (without a duplicate of it in the transcript)."""
    failed = {
        "type": "recommendation", "text": "Произошла техническая ошибка. Рекомендую обратиться к терапевту.",
        "doctor_specialty": "therapist", "bad_recommendation": None, "general_supplement_suggestion": None,
        "is_lifestyle": False, "needs_followup": False, "_technical_error": True,
    }
    client = _setup(tmp_path, monkeypatch, failed)
    try:
        session_id = client.post("/consultations", json={}).json()["session_id"]
        first = client.post(f"/consultations/{session_id}/messages", json={"text": "болит голова"})
        assert first.status_code == 503

        transcript = client.get(f"/consultations/{session_id}").json()
        assert transcript["status"] == "active" and transcript["turns"] == []

        monkeypatch.setattr(consultation, "analyze_symptoms", _stub({"type": "question", "text": "Как давно?"}))
        retry = client.post(f"/consultations/{session_id}/messages", json={"text": "болит голова"})
        assert retry.status_code == 200 and retry.json()["type"] == "question"

        turns = client.get(f"/consultations/{session_id}").json()["turns"]
        assert [(t["role"], t["text"]) for t in turns] == [("user", "болит голова"), ("assistant", "Как давно?")]
    finally:
        app.dependency_overrides.clear()


def test_concurrent_messages_to_one_session_run_the_model_one_at_a_time(tmp_path, monkeypatch):
    """A double-tap/retry used to run two model calls over the same history and
    store two replies. Turns for one session are now serialized: the second
    waits, then sees the first's turn in its history."""
    import httpx

    client = _setup(tmp_path, monkeypatch, {"type": "question", "text": "Как давно?"})
    session_id = client.post("/consultations", json={}).json()["session_id"]

    in_flight = 0
    peak = 0
    histories = []

    async def slow_analyze(transcript, *args, **kwargs):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        histories.append(len(transcript))
        await asyncio.sleep(0.05)
        in_flight -= 1
        return {"type": "question", "text": "Как давно?"}

    monkeypatch.setattr(consultation, "analyze_symptoms", slow_analyze)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            url = f"/consultations/{session_id}/messages"
            return await asyncio.gather(
                ac.post(url, json={"text": "первое"}), ac.post(url, json={"text": "второе"}),
            )

    try:
        responses = asyncio.run(run())
        turns = client.get(f"/consultations/{session_id}").json()["turns"]
    finally:
        app.dependency_overrides.clear()

    assert [r.status_code for r in responses] == [200, 200]
    assert peak == 1
    assert sorted(histories) == [1, 3]   # the later turn saw the earlier one
    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant"]
    assert consultation._session_locks == {} and not consultation._session_lock_users


def test_account_deleted_mid_turn_is_a_404_and_leaves_no_orphan_messages(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, {"type": "question", "text": "Как давно?"})
    session_id = client.post("/consultations", json={}).json()["session_id"]

    async def delete_during_call(*args, **kwargs):
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            async with conn.execute("SELECT user_id FROM sessions WHERE id=?", (session_id,)) as cur:
                (uid,) = await cur.fetchone()
        await db.delete_user_account(uid)
        return {"type": "question", "text": "Как давно?"}

    monkeypatch.setattr(consultation, "analyze_symptoms", delete_during_call)
    try:
        resp = client.post(f"/consultations/{session_id}/messages", json={"text": "болит голова"})
    finally:
        app.dependency_overrides.clear()

    async def message_count():
        async with aiosqlite.connect(db.DATABASE_PATH) as conn:
            async with conn.execute("SELECT COUNT(*) FROM messages") as cur:
                return (await cur.fetchone())[0]

    assert resp.status_code == 404
    assert asyncio.run(message_count()) == 0


def test_a_stored_reply_that_is_not_a_json_object_does_not_break_the_transcript(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, {"type": "question", "text": "?"})
    session_id = client.post("/consultations", json={}).json()["session_id"]

    async def seed():
        for content in ("null", "[1, 2]", "просто текст"):
            await db.add_message(session_id, "assistant", content)

    asyncio.run(seed())
    try:
        resp = client.get(f"/consultations/{session_id}")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert [t["text"] for t in resp.json()["turns"]] == ["null", "[1, 2]", "просто текст"]


def test_empty_or_oversized_message_is_rejected(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, {"type": "question", "text": "?"})
    session_id = client.post("/consultations", json={}).json()["session_id"]
    try:
        url = f"/consultations/{session_id}/messages"
        assert client.post(url, json={"text": ""}).status_code == 422
        assert client.post(url, json={"text": "а" * 4001}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_daily_message_limit_stops_further_model_calls(tmp_path, monkeypatch):
    """The web app is public and every turn costs a model call, so an account
    gets a rolling-24h cap. Over the cap: 429 and the model is never called."""
    client = _setup(tmp_path, monkeypatch, {"type": "question", "text": "Как давно?"})
    monkeypatch.setattr(consultation, "WEB_DAILY_MESSAGE_LIMIT", 2)
    calls = []
    original = consultation.analyze_symptoms

    async def counting(*args, **kwargs):
        calls.append(1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(consultation, "analyze_symptoms", counting)
    try:
        session_id = client.post("/consultations", json={}).json()["session_id"]
        url = f"/consultations/{session_id}/messages"
        assert client.post(url, json={"text": "раз"}).status_code == 200
        assert client.post(url, json={"text": "два"}).status_code == 200
        blocked = client.post(url, json={"text": "три"})
        assert blocked.status_code == 429 and "лимит" in blocked.json()["detail"]
        assert len(calls) == 2
    finally:
        app.dependency_overrides.clear()


def test_messages_older_than_a_day_do_not_count_toward_the_limit(tmp_path, monkeypatch):
    client = _setup(tmp_path, monkeypatch, {"type": "question", "text": "Как давно?"})
    monkeypatch.setattr(consultation, "WEB_DAILY_MESSAGE_LIMIT", 1)
    try:
        session_id = client.post("/consultations", json={}).json()["session_id"]
        url = f"/consultations/{session_id}/messages"
        assert client.post(url, json={"text": "раз"}).status_code == 200
        assert client.post(url, json={"text": "два"}).status_code == 429

        async def age_messages():
            async with aiosqlite.connect(db.DATABASE_PATH) as conn:
                await conn.execute("UPDATE messages SET created_at = datetime('now', '-25 hours')")
                await conn.commit()

        asyncio.run(age_messages())
        assert client.post(url, json={"text": "два"}).status_code == 200
    finally:
        app.dependency_overrides.clear()
