"""
Tool schemas + executor grounding ai/assistant.py's BAD recommendations in the
real catalog and safety data (data/bad_safety.py, Phase 1) instead of letting
the model free-associate a bad_recommendation from its own training data.

The model only ever supplies `bad_key` — the executor closes over the real
`profile` dict already loaded by the caller, so the model can never supply or
hallucinate health data itself (mirrors the existing _build_system pattern).
"""
from data.bad_safety import check_bad_safety
from data.resources import BAD_DETAILS

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_bads_catalog",
            "description": (
                "Возвращает актуальный каталог БАД, которые реально продаёт бот "
                "(название, цель, инструкция по приёму). Вызови это перед тем, как "
                "заполнить bad_recommendation — не полагайся на список из системного "
                "промпта, каталог может измениться."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_bad_safety",
            "description": (
                "Проверяет конкретный БАД из каталога на противопоказания и "
                "взаимодействия с лекарствами для ТЕКУЩЕГО пациента. Профиль "
                "здоровья подставляется автоматически — тебе не нужно и нельзя "
                "передавать данные о здоровье, только bad_key. Вызови это перед "
                "тем, как указать bad_recommendation, чтобы не пропустить опасное "
                "сочетание (например, тромбофилию)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "bad_key": {
                        "type": "string",
                        "enum": list(BAD_DETAILS.keys()),
                        "description": "Ключ БАД из каталога (см. list_bads_catalog).",
                    }
                },
                "required": ["bad_key"],
            },
        },
    },
]


def _list_bads_catalog() -> dict:
    return {
        key: {"name": d["full_name"], "goal": d["goal"], "notes": d["notes"]}
        for key, d in BAD_DETAILS.items()
    }


def execute_tool(name: str, arguments: dict, profile: dict | None) -> dict:
    """Dispatch a single tool call requested by the model."""
    if name == "list_bads_catalog":
        return _list_bads_catalog()

    if name == "check_bad_safety":
        bad_key = arguments.get("bad_key")
        if bad_key not in BAD_DETAILS:
            return {"error": f"unknown bad_key: {bad_key}"}
        warnings = check_bad_safety(bad_key, profile)
        return {
            "bad_key": bad_key,
            "safe": not any(w.kind == "contraindication" for w in warnings),
            "warnings": [{"kind": w.kind, "message": w.message} for w in warnings],
        }

    return {"error": f"unknown tool: {name}"}
