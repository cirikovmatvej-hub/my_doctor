"""
Regression tests for data/general_supplements.py — the knowledge base for
supplements the bot names but doesn't sell. Mirrors tests/test_bad_safety.py's
structure and intent: lock in data integrity (every rule sourced, every
trigger real) and the key behaviors (grounding, safety-checking, resolving
free text back to a known substance).
"""
from data.bad_safety import ALLERGENS, CONDITIONS, MEDICATIONS
from data.general_supplements import (
    GENERAL_INTERACTION_RULES,
    GENERAL_SUPPLEMENTS,
    check_general_supplement_safety,
    is_general_supplement_grounded,
    list_general_supplements,
    mentions_a_general_supplement_by_name,
    resolve_general_supplement_key,
)


# ── Data integrity: every rule must be sourced and reference real entries ──

def test_every_rule_has_a_source():
    missing = [r["rule_id"] for r in GENERAL_INTERACTION_RULES if not r.get("source")]
    assert missing == []


def test_every_rule_references_a_known_ingredient():
    unknown = [r["rule_id"] for r in GENERAL_INTERACTION_RULES if r["ingredient_id"] not in GENERAL_SUPPLEMENTS]
    assert unknown == []


def test_every_rule_trigger_exists():
    lookup = {"condition": CONDITIONS, "allergen": ALLERGENS, "medication": MEDICATIONS}
    for rule in GENERAL_INTERACTION_RULES:
        trigger_type, trigger_id = rule["trigger_type"], rule["trigger_id"]
        assert trigger_id in lookup[trigger_type], (
            f"{rule['rule_id']} references unknown {trigger_type} '{trigger_id}'"
        )


def test_every_supplement_has_indication_terms_and_goal():
    for key, entry in GENERAL_SUPPLEMENTS.items():
        assert entry.get("indication_terms"), f"{key} has no indication_terms"
        assert entry.get("goal"), f"{key} has no goal"
        assert entry.get("label"), f"{key} has no label"


def test_rule_ingredient_ids_do_not_collide_with_catalog():
    """The whole point of keeping this a separate list from BAD_DETAILS is
    that these are NOT sold products — the key namespaces must not overlap."""
    from data.resources import BAD_DETAILS
    assert set(GENERAL_SUPPLEMENTS.keys()).isdisjoint(BAD_DETAILS.keys())


# ── list_general_supplements ────────────────────────────────────────────────

def test_list_general_supplements_covers_every_entry():
    listed = list_general_supplements()
    assert set(listed.keys()) == set(GENERAL_SUPPLEMENTS.keys())
    assert all("name" in v and "goal" in v for v in listed.values())


# ── resolve_general_supplement_key ──────────────────────────────────────────

def test_resolve_matches_known_label_in_free_text():
    assert resolve_general_supplement_key("стоит ли пить омега-3 зимой") == "omega3"
    assert resolve_general_supplement_key("может, попробовать зверобой?") == "st_johns_wort"


def test_resolve_returns_none_for_unrelated_text():
    assert resolve_general_supplement_key("у меня болит живот после еды") is None
    assert resolve_general_supplement_key(None) is None


def test_mentions_a_general_supplement_by_name():
    assert mentions_a_general_supplement_by_name("какая разница между формами цинка") is True
    assert mentions_a_general_supplement_by_name("у меня болит голова") is False


# ── is_general_supplement_grounded ──────────────────────────────────────────

def test_grounded_for_matching_symptom():
    assert is_general_supplement_grounded("zinc", "пропало обоняние и вкус еды, выпадают волосы")


def test_not_grounded_for_unrelated_complaint():
    assert not is_general_supplement_grounded("zinc", "постоянно болит живот после еды")


def test_grounded_is_permissive_for_unknown_key():
    assert is_general_supplement_grounded("not_a_real_key", "что угодно")


# ── check_general_supplement_safety ─────────────────────────────────────────

def test_potassium_kidney_disease_is_contraindication():
    profile = {"chronic_diseases": "хроническая болезнь почек", "medications": "", "allergies": ""}
    warnings = check_general_supplement_safety("potassium", profile)
    assert any(w.kind == "contraindication" and w.rule_id == "potassium_kidney" for w in warnings)


def test_st_johns_wort_with_ssri_is_contraindication():
    profile = {"chronic_diseases": "", "medications": "принимаю сертралин", "allergies": ""}
    warnings = check_general_supplement_safety("st_johns_wort", profile)
    assert any(w.kind == "contraindication" and w.rule_id == "sjw_ssri" for w in warnings)


def test_glucosamine_shellfish_allergy_flags_caution():
    profile = {"chronic_diseases": "", "medications": "", "allergies": "аллергия на креветки"}
    warnings = check_general_supplement_safety("glucosamine_chondroitin", profile)
    assert any(w.rule_id == "glucosamine_shellfish" for w in warnings)


def test_pregnancy_flags_non_pregnancy_safe_supplement_only():
    profile = {"chronic_diseases": "", "medications": "", "allergies": "", "pregnancy": "pregnant"}
    assert any(w.kind == "pregnancy" for w in check_general_supplement_safety("ashwagandha", profile))
    assert not any(w.kind == "pregnancy" for w in check_general_supplement_safety("folate", profile))


def test_unrelated_profile_produces_no_warnings():
    profile = {"chronic_diseases": "мигрень", "medications": "ибупрофен", "allergies": "", "pregnancy": "no"}
    assert check_general_supplement_safety("omega3", profile) == []


def test_no_profile_produces_no_warnings():
    assert check_general_supplement_safety("iron", None) == []


def test_unknown_key_produces_no_warnings():
    assert check_general_supplement_safety("not_a_real_key", {"chronic_diseases": "тромбофилия"}) == []
