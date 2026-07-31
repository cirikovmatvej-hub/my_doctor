"""
Regression tests for data/bad_safety.py — locks in the behavior the beta-testing
doctor is reviewing (docs/bad_safety_review.md) so future edits to the rules
can't silently break what she already confirmed.

Cases B/D/F from the original plan (joint-complex-specific scenarios) are
deferred until a real joint product exists in the catalog.
"""
import pytest

from data.bad_safety import (
    ALLERGENS,
    CONDITIONS,
    INTERACTION_RULES,
    MEDICATIONS,
    SYNERGY_RULES,
    check_bad_safety,
    get_bad_synergies,
    suggest_goal_keys,
)

DOCTOR_PROFILE = {
    "chronic_diseases": "Тромбофилия",
    "medications": "метилфолат",
    "allergies": "",
    "pregnancy": "no",
}


# ── Case A: the doctor's exact profile must trigger a general caution ──────

@pytest.mark.parametrize("bad_key", ["magnesium", "collagen", "vitamin_d3"])
def test_thrombophilia_triggers_general_caution_on_every_product(bad_key):
    warnings = check_bad_safety(bad_key, DOCTOR_PROFILE)
    assert any(w.kind == "general_caution" for w in warnings)


# ── Case C: typos/case/synonyms must match the same way ────────────────────

@pytest.mark.parametrize(
    "chronic_diseases",
    [
        "тромбофилия",
        "ТРОМБОФИЛИЯ",
        "тромбофелия",  # typo
        "склонность к тромбозам",
        "Тромбофилия, диагностирована в 2019",
    ],
)
def test_clotting_disorder_matches_variants(chronic_diseases):
    profile = {**DOCTOR_PROFILE, "chronic_diseases": chronic_diseases}
    warnings = check_bad_safety("magnesium", profile)
    assert any(w.kind == "general_caution" for w in warnings)


# ── Case E: unrelated conditions must not produce false positives ──────────

@pytest.mark.parametrize(
    "profile",
    [
        {"chronic_diseases": "аллергия на пыльцу", "medications": "", "allergies": ""},
        {"chronic_diseases": "", "medications": "", "allergies": ""},
        {"chronic_diseases": "мигрень", "medications": "ибупрофен", "allergies": ""},
    ],
)
def test_unrelated_profile_produces_no_warnings(profile):
    for bad_key in ["magnesium", "collagen", "vitamin_d3"]:
        assert check_bad_safety(bad_key, profile) == []


def test_no_profile_produces_no_warnings():
    assert check_bad_safety("magnesium", None) == []
    assert check_bad_safety("magnesium", {}) == []


# ── Ingredient-specific interaction rules actually fire ─────────────────────

def test_kidney_disease_flags_magnesium_and_vitamin_d3():
    profile = {"chronic_diseases": "хроническая болезнь почек", "medications": "", "allergies": ""}
    mg_rule_ids = {w.rule_id for w in check_bad_safety("magnesium", profile)}
    d3_rule_ids = {w.rule_id for w in check_bad_safety("vitamin_d3", profile)}
    assert "magnesium_kidney" in mg_rule_ids
    assert "vitamin_d3_kidney" in d3_rule_ids


def test_pregnancy_flags_non_pregnancy_safe_products_only():
    profile = {"chronic_diseases": "", "medications": "", "allergies": "", "pregnancy": "pregnant"}
    assert any(w.kind == "pregnancy" for w in check_bad_safety("magnesium", profile))
    assert any(w.kind == "pregnancy" for w in check_bad_safety("collagen", profile))
    # vitamin_d3 is marked pregnancy_safe=True in BAD_DETAILS
    assert not any(w.kind == "pregnancy" for w in check_bad_safety("vitamin_d3", profile))


# ── Data integrity: every rule must be sourced and reference real entries ──

def test_every_interaction_rule_has_a_source():
    missing = [r["rule_id"] for r in INTERACTION_RULES if not r.get("source")]
    assert missing == []


def test_every_synergy_rule_has_a_source():
    missing = [r["rule_id"] for r in SYNERGY_RULES if not r.get("source")]
    assert missing == []


def test_every_interaction_rule_trigger_exists():
    for rule in INTERACTION_RULES:
        trigger_type, trigger_id = rule["trigger_type"], rule["trigger_id"]
        lookup = {"condition": CONDITIONS, "allergen": ALLERGENS, "medication": MEDICATIONS}[trigger_type]
        assert trigger_id in lookup, f"{rule['rule_id']} references unknown {trigger_type} '{trigger_id}'"


# ── Synergy notes ────────────────────────────────────────────────────────────

def test_vitamin_d3_synergies_include_magnesium_and_k2():
    rule_ids = {s.rule_id for s in get_bad_synergies("vitamin_d3")}
    assert "vitamin_d3_needs_magnesium" in rule_ids
    assert "vitamin_d3_pairs_with_k2" in rule_ids


def test_magnesium_has_no_synergy_notes_of_its_own():
    assert get_bad_synergies("magnesium") == []


# ── Case F: profile-aware goal suggestions (Phase 3) ────────────────────────

def test_weight_and_depression_suggests_sleep_stress():
    # the exact real-world case from the doctor's feedback that the bot's
    # specialty routing handled poorly — the BAD advisor should at least
    # point toward sleep_stress rather than staying silent.
    profile = {"chronic_diseases": "депрессия, лишний вес"}
    assert suggest_goal_keys(profile) == ["sleep_stress"]


def test_fatigue_and_frequent_colds_suggests_energy_immunity():
    profile = {"chronic_diseases": "хроническая усталость, частые простуды"}
    assert suggest_goal_keys(profile) == ["energy_immunity"]


def test_hair_loss_suggests_beauty():
    profile = {"chronic_diseases": "выпадение волос"}
    assert suggest_goal_keys(profile) == ["beauty"]


def test_unrelated_condition_suggests_nothing():
    profile = {"chronic_diseases": "сахарный диабет"}
    assert suggest_goal_keys(profile) == []


def test_empty_or_missing_profile_suggests_nothing():
    assert suggest_goal_keys(None) == []
    assert suggest_goal_keys({}) == []
