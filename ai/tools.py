"""
Tool schemas + executor grounding ai/assistant.py's BAD recommendations in the
real catalog and safety data (data/bad_safety.py, Phase 1) instead of letting
the model free-associate a bad_recommendation from its own training data.

The model only ever supplies `bad_key` — the executor closes over the real
`profile` dict already loaded by the caller, so the model can never supply or
hallucinate health data itself (mirrors the existing _build_system pattern).

list_general_supplements/check_general_supplement_safety extend the same
grounding to general_supplement_suggestion — supplements the bot names but
doesn't sell (data/general_supplements.py) — which previously had zero
grounding and zero safety-checking.
"""
from data.bad_safety import check_bad_safety, get_bad_sources
from data.general_supplements import (
    GENERAL_SUPPLEMENTS, check_general_supplement_safety, get_general_sources, list_general_supplements,
)
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
    {
        "type": "function",
        "function": {
            "name": "list_general_supplements",
            "description": (
                "Возвращает справочник добавок, которые бот НЕ продаёт, но может честно "
                "назвать в general_supplement_suggestion (название, назначение, заметки). "
                "Вызови это перед тем, как заполнить general_supplement_suggestion — "
                "используй ТОЛЬКО название из этого списка (поле name), не придумывай "
                "своё название и не предлагай то, чего здесь нет."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_general_supplement_safety",
            "description": (
                "Проверяет конкретную добавку из list_general_supplements на противопоказания "
                "и взаимодействия с лекарствами для ТЕКУЩЕГО пациента. Профиль здоровья "
                "подставляется автоматически — тебе не нужно и нельзя передавать данные о "
                "здоровье, только general_key. Вызови это перед тем, как указать "
                "general_supplement_suggestion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "general_key": {
                        "type": "string",
                        "enum": list(GENERAL_SUPPLEMENTS.keys()),
                        "description": "Ключ добавки из справочника (см. list_general_supplements).",
                    }
                },
                "required": ["general_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sources",
            "description": (
                "Возвращает реальные источники (названия организаций/изданий и ссылки), на "
                "которых основаны данные о показаниях и безопасности БАД. Вызови это, если "
                "пользователь спрашивает, на какие источники/журналы/исследования ты "
                "опираешься — НЕ отвечай общими фразами вроде 'принципы доказательной "
                "медицины', а процитируй 2-4 конкретных названия и ссылки из результата этого "
                "инструмента. Передай topic (ключ конкретного БАД/добавки), если вопрос про "
                "конкретное вещество — тогда получишь источники именно по нему; не передавай "
                "topic вовсе, если вопрос общий про методологию."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "enum": list(BAD_DETAILS.keys()) + list(GENERAL_SUPPLEMENTS.keys()),
                        "description": "Ключ конкретного БАД/добавки. Не передавай для общего вопроса.",
                    }
                },
                "required": [],
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

    if name == "list_general_supplements":
        return list_general_supplements()

    if name == "check_general_supplement_safety":
        general_key = arguments.get("general_key")
        if general_key not in GENERAL_SUPPLEMENTS:
            return {"error": f"unknown general_key: {general_key}"}
        warnings = check_general_supplement_safety(general_key, profile)
        return {
            "general_key": general_key,
            "safe": not any(w.kind == "contraindication" for w in warnings),
            "warnings": [{"kind": w.kind, "message": w.message} for w in warnings],
        }

    if name == "list_sources":
        topic = arguments.get("topic")
        if topic in BAD_DETAILS:
            sources = get_bad_sources(topic)
        elif topic in GENERAL_SUPPLEMENTS:
            sources = get_general_sources(topic)
        else:
            # General methodology question — a representative sample across
            # both domains, deduplicated, capped so the model gets a few
            # concrete examples rather than a wall of citations to skim.
            # Prefer entries that are an actual named/linked source over the
            # few "source" fields that are really just a mechanism
            # explanation with no citation (e.g. myasthenia's magnesium
            # rule) — those read oddly if quoted back as "a journal".
            combined = get_bad_sources() + get_general_sources()
            seen: set[str] = set()
            deduped = []
            for s in combined:
                if s not in seen:
                    seen.add(s)
                    deduped.append(s)
            linked = [s for s in deduped if "http" in s]
            sources = (linked or deduped)[:8]
        return {"sources": sources}

    return {"error": f"unknown tool: {name}"}
