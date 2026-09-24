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
