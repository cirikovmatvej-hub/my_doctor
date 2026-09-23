"""
The app's BAD-advisor endpoints must apply the same safety split as the bot's
handlers/bad_advisor.py: a product contraindicated for this profile is left out
of the cards (its reason goes in blocked_notes), non-blocking cautions stay as
warnings, and goals with no catalog product still return their non-catalog
supplements instead of an empty screen.
"""
import asyncio

import database.db as db
from api.deps import get_current_user
from api.main import app
from data.resources import BAD_GOALS
from fastapi.testclient import TestClient


def _client(tmp_path, profile: dict | None = None) -> TestClient:
    db.DATABASE_PATH = str(tmp_path / "advisor.db")

    async def setup():
        await db.init_db()
        user_id = await db.get_or_create_user(111, "owner")
        for field, value in (profile or {}).items():
            await db.set_health_field_by_id(user_id, field, value)
        return user_id

    user_id = asyncio.run(setup())
    app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(app)


def _check(client, goal_key, **extra):
    resp = client.post("/bad-advisor/check", json={"goal_key": goal_key, **extra})
    assert resp.status_code == 200
    return resp.json()


def test_contraindicated_product_is_not_shown_but_explained(tmp_path):
    client = _client(tmp_path, {"chronic_diseases": "болезнь почек"})
    try:
        result = _check(client, "sleep_stress")
    finally:
        app.dependency_overrides.clear()

    assert [b["key"] for b in result["bads"]] == []   # both magnesium products blocked
    assert any("почек" in note for note in result["blocked_notes"])
    assert not any("почек" in w for w in result["warnings"])


def test_no_profile_shows_everything(tmp_path):
    client = _client(tmp_path)
    try:
        result = _check(client, "sleep_stress")
    finally:
        app.dependency_overrides.clear()

    assert {b["key"] for b in result["bads"]} == set(BAD_GOALS["sleep_stress"]["bads"])
    assert result["blocked_notes"] == []


def test_non_blocking_caution_keeps_the_card(tmp_path):
    # vitamin D3 has only a "caution" rule for kidney disease
    client = _client(tmp_path, {"chronic_diseases": "болезнь почек"})
    try:
        result = _check(client, "energy_immunity")
    finally:
        app.dependency_overrides.clear()

    assert [b["key"] for b in result["bads"]] == ["vitamin_d3"]
    assert result["warnings"]
    assert result["blocked_notes"] == []


def test_goal_without_catalog_product_returns_general_supplements(tmp_path):
    client = _client(tmp_path)
    try:
        result = _check(client, "digestion")
    finally:
        app.dependency_overrides.clear()

    assert result["bads"] == []
    assert [g["key"] for g in result["general_supplements"]] == ["probiotics"]
    assert result["general_supplements"][0]["label"] == "пробиотики"


def test_contraindicated_general_supplement_is_blocked(tmp_path):
    client = _client(tmp_path, {"chronic_diseases": "иммунодефицит"})
    try:
        result = _check(client, "digestion")
    finally:
        app.dependency_overrides.clear()

    assert result["general_supplements"] == []
    assert result["blocked_notes"]


def test_catalog_card_includes_synergies(tmp_path):
    client = _client(tmp_path)
    try:
        (d3,) = _check(client, "energy_immunity")["bads"]
        (mg, mg_b6) = _check(client, "sleep_stress")["bads"]
    finally:
        app.dependency_overrides.clear()

    assert len(d3["synergies"]) == 2      # vitamin D3 pairs with magnesium and K2
    assert mg["synergies"] == mg_b6["synergies"] == []


def test_clarify_option_returns_its_note_and_rejects_unknown(tmp_path):
    client = _client(tmp_path)
    try:
        goals = {g["key"]: g for g in client.get("/bad-goals").json()}
        assert goals["sleep_stress"]["clarify"]["options"][0]["key"] == "recent"
        assert goals["complex"]["clarify"] is None

        result = _check(client, "sleep_stress", clarify_option="chronic")
        assert "больше месяца" in result["extra_note"]

        bad = client.post("/bad-advisor/check", json={"goal_key": "sleep_stress", "clarify_option": "nope"})
        assert bad.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_goals_matching_the_profile_are_listed_first(tmp_path):
    client = _client(tmp_path, {"chronic_diseases": "выпадение волос"})
    try:
        goals = client.get("/bad-goals").json()
    finally:
        app.dependency_overrides.clear()

    assert goals[0]["key"] == "beauty" and goals[0]["suggested"] is True
    assert {g["key"] for g in goals} == set(BAD_GOALS)   # nothing hidden
