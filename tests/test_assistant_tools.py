"""
Unit tests for ai/tools.py — the tool-calling layer that grounds
bad_recommendation in data/bad_safety.py instead of the model's own training
knowledge. No live Groq call here (see manual verification note in the plan);
this only tests execute_tool() directly against fake tool-call arguments.
"""
from ai.tools import TOOL_SCHEMAS, execute_tool
from data.resources import BAD_DETAILS

DOCTOR_PROFILE = {
    "chronic_diseases": "Тромбофилия",
    "medications": "метилфолат",
    "allergies": "",
    "pregnancy": "no",
}


def test_tool_schemas_reference_real_bad_keys():
    check_safety_schema = next(t for t in TOOL_SCHEMAS if t["function"]["name"] == "check_bad_safety")
    enum = check_safety_schema["function"]["parameters"]["properties"]["bad_key"]["enum"]
    assert set(enum) == set(BAD_DETAILS.keys())


def test_list_bads_catalog_returns_every_catalog_product():
    result = execute_tool("list_bads_catalog", {}, None)
    assert set(result.keys()) == set(BAD_DETAILS.keys())
    for key, entry in result.items():
        assert entry["name"] == BAD_DETAILS[key]["full_name"]


def test_check_bad_safety_flags_thrombophilia_on_magnesium():
    # the doctor's exact real-world case: her thrombophilia should surface as
    # a warning even though magnesium's ingredient list has no direct hit —
    # it's the CONDITIONS general_caution path (Phase 1).
    result = execute_tool("check_bad_safety", {"bad_key": "magnesium"}, DOCTOR_PROFILE)
    assert result["warnings"]
    assert any(w["kind"] == "general_caution" for w in result["warnings"])


def test_check_bad_safety_reports_safe_for_unrelated_profile():
    profile = {"chronic_diseases": "мигрень", "medications": "", "allergies": ""}
    result = execute_tool("check_bad_safety", {"bad_key": "vitamin_d3"}, profile)
    assert result["safe"] is True
    assert result["warnings"] == []


def test_check_bad_safety_unknown_bad_key_returns_error():
    result = execute_tool("check_bad_safety", {"bad_key": "unicorn_dust"}, DOCTOR_PROFILE)
    assert "error" in result


def test_execute_tool_unknown_tool_name_returns_error():
    result = execute_tool("delete_all_users", {}, None)
    assert "error" in result
