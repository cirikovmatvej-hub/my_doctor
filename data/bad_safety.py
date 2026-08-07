"""
Shared safety/relevance knowledge for БАД recommendations — the single source
of truth used by the bot, the API, and the AI tool-calling path (Phase 4).

Conditions/allergens/medications are matched against the free-text profile
fields the user typed during onboarding (chronic_diseases, allergies,
medications) — there's no controlled vocabulary yet, so matching has to
tolerate case, common suffixes, and typos (see _term_matches).

Interaction rules are keyed by ingredient_id, not by product — any BAD that
lists an ingredient in BAD_DETAILS[key]["ingredient_ids"] automatically
inherits every rule that references it. Adding a new product never requires
duplicating another product's contraindication data.
"""
import difflib
from typing import NamedTuple

from data.resources import BAD_DETAILS

# ── Canonical conditions/allergens/medications ──────────────────────────────
# match_terms are canonical stems (e.g. "тромбофил" catches тромбофилия,
# тромбофилии, тромбофилией...) — write stems, not every inflected form.

CONDITIONS: dict[str, dict] = {
    "clotting_disorder": {
        "label": "нарушение свёртываемости крови / тромбофилия",
        "match_terms": ["тромбофил", "склонность к тромбоз", "гиперкоагуляц", "варикоз"],
        "general_caution": True,  # fires on every BAD check, not just ingredient-specific rules
    },
    "kidney_disease": {
        "label": "заболевания почек",
        "match_terms": ["почечн", "нефрит", "почки"],
        "general_caution": False,
    },
    "bradycardia": {
        "label": "брадикардия (замедленный пульс)",
        "match_terms": ["брадикард"],
        "general_caution": False,
    },
    "hypotension": {
        "label": "пониженное давление / гипотония",
        "match_terms": ["гипотони", "гипотон", "низкое давление"],
        "general_caution": False,
    },
    "myasthenia": {
        "label": "миастения",
        "match_terms": ["миастени"],
        "general_caution": False,
    },
    "hypercalcemia": {
        "label": "гиперкальциемия / избыток кальция",
        "match_terms": ["гиперкальциеми"],
        "general_caution": False,
    },
    "sarcoidosis": {
        "label": "саркоидоз",
        "match_terms": ["саркоидоз"],
        "general_caution": False,
    },
    "hypervitaminosis_d": {
        "label": "гипервитаминоз D",
        "match_terms": ["гипервитаминоз"],
        "general_caution": False,
    },
}

ALLERGENS: dict[str, dict] = {
    "shellfish": {
        "label": "аллергия на морепродукты/ракообразных",
        "match_terms": ["морепродукт", "креветк", "ракообразн", "панцир"],
    },
}

MEDICATIONS: dict[str, dict] = {
    "methylfolate": {
        "label": "метилфолат (активная форма фолиевой кислоты)",
        "match_terms": ["метилфолат", "метафолин", "l-метилфолат"],
    },
    "anticoagulant": {
        "label": "антикоагулянты/антиагреганты",
        "match_terms": ["варфарин", "антикоагулянт", "клопидогрел", "аспирин кардио"],
    },
    "tetracycline": {"label": "тетрациклины", "match_terms": ["тетрациклин"]},
    "bisphosphonate": {"label": "бисфосфонаты", "match_terms": ["бисфосфонат"]},
    "levothyroxine": {"label": "левотироксин", "match_terms": ["левотироксин"]},
    "thiazide": {"label": "тиазидные диуретики", "match_terms": ["тиазидн"]},
}

# ── Reused citations ─────────────────────────────────────────────────────────

RAE_VITAMIN_D_GUIDELINE = (
    "Клинические рекомендации Российской ассоциации эндокринологов по диагностике, лечению и "
    "профилактике дефицита витамина D у взрослых (Пигарова и др., Проблемы Эндокринологии, 2016): "
    "https://rae-org.ru/system/files/documents/pdf/kr342_deficit_vitamina_d_u_vzroslyh.pdf"
)

# ── Ingredient-level interaction rules ──────────────────────────────────────

INTERACTION_RULES: list[dict] = [
    {
        "rule_id": "magnesium_kidney",
        "ingredient_id": "magnesium",
        "trigger_type": "condition",
        "trigger_id": "kidney_disease",
        "severity": "contraindication",
        "message": "{bad_name}: при заболеваниях почек возможно накопление магния — уточните у врача.",
        "source": "NIH Office of Dietary Supplements — Magnesium (Health Professional Fact Sheet): "
                   "https://ods.od.nih.gov/factsheets/Magnesium-HealthProfessional/",
    },
    {
        "rule_id": "magnesium_bradycardia",
        "ingredient_id": "magnesium",
        "trigger_type": "condition",
        "trigger_id": "bradycardia",
        "severity": "contraindication",
        "message": "{bad_name}: магний может дополнительно замедлять пульс — при брадикардии принимайте только по согласованию с врачом.",
        "source": "Механизм действия (избыток магния вызывает аритмию/замедление ритма), общая "
                   "клиническая фармакология магния — см. NIH ODS Magnesium fact sheet, раздел "
                   "о симптомах избытка: https://ods.od.nih.gov/factsheets/Magnesium-HealthProfessional/",
    },
    {
        "rule_id": "magnesium_hypotension",
        "ingredient_id": "magnesium",
        "trigger_type": "condition",
        "trigger_id": "hypotension",
        "severity": "contraindication",
        "message": "{bad_name}: магний способен снижать давление — при гипотонии принимайте только по согласованию с врачом.",
        "source": "Механизм действия (магний как антагонист кальциевых каналов, сосудорасширяющий "
                   "эффект) — см. NIH ODS Magnesium fact sheet: "
                   "https://ods.od.nih.gov/factsheets/Magnesium-HealthProfessional/",
    },
    {
        "rule_id": "magnesium_myasthenia",
        "ingredient_id": "magnesium",
        "trigger_type": "condition",
        "trigger_id": "myasthenia",
        "severity": "contraindication",
        "message": "{bad_name}: магний может усиливать мышечную слабость при миастении — обязательно уточните у врача.",
        "source": "Задокументированный механизм: магний блокирует вход кальция в нервные "
                   "окончания, снижая высвобождение ацетилхолина — стандартное противопоказание "
                   "в клинической фармакологии при миастении гравис.",
    },
    {
        "rule_id": "magnesium_tetracycline",
        "ingredient_id": "magnesium",
        "trigger_type": "medication",
        "trigger_id": "tetracycline",
        "severity": "interaction",
        "message": "{bad_name}: магний снижает всасывание тетрациклинов — разнесите приём минимум на 2–3 часа.",
        "source": "NIH Office of Dietary Supplements — Magnesium (Health Professional Fact Sheet), "
                   "раздел Interactions with Medications: "
                   "https://ods.od.nih.gov/factsheets/Magnesium-HealthProfessional/",
    },
    {
        "rule_id": "magnesium_bisphosphonate",
        "ingredient_id": "magnesium",
        "trigger_type": "medication",
        "trigger_id": "bisphosphonate",
        "severity": "interaction",
        "message": "{bad_name}: магний снижает всасывание бисфосфонатов — разнесите приём по времени, уточните у врача.",
        "source": "NIH Office of Dietary Supplements — Magnesium (Health Professional Fact Sheet): "
                   "рекомендован интервал минимум 2 часа между приёмом магния и бисфосфонатов. "
                   "https://ods.od.nih.gov/factsheets/Magnesium-HealthProfessional/",
    },
    {
        "rule_id": "magnesium_levothyroxine",
        "ingredient_id": "magnesium",
        "trigger_type": "medication",
        "trigger_id": "levothyroxine",
        "severity": "interaction",
        "message": "{bad_name}: магний может снижать всасывание левотироксина — разнесите приём минимум на 4 часа.",
        "source": "Drugs.com Interaction Checker — Levothyroxine + Magnesium: "
                   "https://www.drugs.com/drug-interactions/levothyroxine-with-magnesium-glycinate-1463-0-3906-0.html",
    },
    {
        "rule_id": "vitamin_d3_kidney",
        "ingredient_id": "vitamin_d3",
        "trigger_type": "condition",
        "trigger_id": "kidney_disease",
        "severity": "caution",
        "message": "{bad_name}: при заболеваниях почек нарушен обмен витамина D — приём только под контролем врача.",
        "source": "NIH Office of Dietary Supplements — Vitamin D (Health Professional Fact Sheet), "
                   "почечная гидроксилаза — ключевой фермент активации витамина D: "
                   "https://ods.od.nih.gov/factsheets/VitaminD-HealthProfessional/ ; "
                   f"{RAE_VITAMIN_D_GUIDELINE}",
    },
    {
        "rule_id": "vitamin_d3_hypercalcemia",
        "ingredient_id": "vitamin_d3",
        "trigger_type": "condition",
        "trigger_id": "hypercalcemia",
        "severity": "contraindication",
        "message": "{bad_name}: при избытке кальция в крови приём витамина D3 противопоказан — обязательно обсудите с врачом.",
        "source": "NIH Office of Dietary Supplements — Vitamin D (Health Professional Fact Sheet), "
                   "раздел о токсичности/гиперкальциемии: "
                   f"https://ods.od.nih.gov/factsheets/VitaminD-HealthProfessional/ ; {RAE_VITAMIN_D_GUIDELINE}",
    },
    {
        "rule_id": "vitamin_d3_sarcoidosis",
        "ingredient_id": "vitamin_d3",
        "trigger_type": "condition",
        "trigger_id": "sarcoidosis",
        "severity": "contraindication",
        "message": "{bad_name}: при саркоидозе витамин D3 может провоцировать опасный избыток кальция — принимайте только по назначению врача.",
        "source": "Механизм: при саркоидозе гранулёмы вырабатывают избыток активной формы "
                   "витамина D (1,25(OH)2D), что усиливает риск гиперкальциемии — см. NIH ODS "
                   f"Vitamin D fact sheet: https://ods.od.nih.gov/factsheets/VitaminD-HealthProfessional/ ; "
                   f"{RAE_VITAMIN_D_GUIDELINE}",
    },
    {
        "rule_id": "vitamin_d3_hypervitaminosis",
        "ingredient_id": "vitamin_d3",
        "trigger_type": "condition",
        "trigger_id": "hypervitaminosis_d",
        "severity": "contraindication",
        "message": "{bad_name}: при уже диагностированном гипервитаминозе D дополнительный приём противопоказан.",
        "source": "NIH Office of Dietary Supplements — Vitamin D (Health Professional Fact Sheet), "
                   "раздел Safety/Toxicity: https://ods.od.nih.gov/factsheets/VitaminD-HealthProfessional/ ; "
                   f"{RAE_VITAMIN_D_GUIDELINE}",
    },
    {
        "rule_id": "vitamin_d3_thiazide",
        "ingredient_id": "vitamin_d3",
        "trigger_type": "medication",
        "trigger_id": "thiazide",
        "severity": "interaction",
        "message": "{bad_name}: витамин D3 с тиазидными диуретиками может повышать риск избытка кальция в крови — уточните у врача.",
        "source": "NIH Office of Dietary Supplements — Vitamin D (Consumer Fact Sheet): тиазидные "
                   "диуретики в сочетании с витамином D могут повышать кальций крови до опасного "
                   f"уровня. https://ods.od.nih.gov/factsheets/VitaminD-Consumer/ ; {RAE_VITAMIN_D_GUIDELINE}",
    },
]


# ── Indication grounding for bad_recommendation ─────────────────────────────
# A deterministic backstop against the model inventing a match (e.g. "magnesium
# helps digestion") that isn't actually one of the product's real indications —
# checked against the user's own words, not the model's paraphrase of them.
# Generous/loose on purpose: a false negative here silently drops a valid
# recommendation, which is a much smaller harm than a false positive
# (force-fitting an unrelated product), so terms err toward over-inclusion.

# Product/ingredient names — a user asking about the product by name (e.g.
# "какой магний лучше, хелат или цитрат") is always grounded, even more so
# than a symptom-term match. Also used to force tool-calling in ai/assistant.py
# for informational questions, since the model doesn't reliably call
# list_bads_catalog on prompt instruction alone (verified live).
PRODUCT_NAME_TERMS: dict[str, list[str]] = {
    "magnesium": ["магний", "хелат"],
    "vitamin_d3": ["витамин d", "витамин д", "д3"],
    "collagen": ["коллаген"],
}

_SYMPTOM_TERMS: dict[str, list[str]] = {
    "magnesium": [
        "сон", "сплю", "спать", "уснуть", "бессонниц", "стресс", "тревож",
        "раздражит", "нервн", "мышечн", "спазм", "судорог", "напряжен",
        "расслаб",
    ],
    "vitamin_d3": [
        "иммунит", "устал", "слаб", "простуд", "простужа", "болею", "тонус",
        "энерги", "настроен", "депресс", "кост", "апати",
    ],
    "collagen": [
        "кожа", "кожи", "кож", "волос", "ногт", "сустав", "морщин", "упруг",
        "колен", "локт",
    ],
}

INDICATION_TERMS: dict[str, list[str]] = {
    key: PRODUCT_NAME_TERMS[key] + _SYMPTOM_TERMS[key] for key in _SYMPTOM_TERMS
}


# Deliberately exact-substring only, no fuzzy fallback — unlike the rare
# medical stems in CONDITIONS/MEDICATIONS (where typo-tolerance is worth the
# risk), these are common everyday words, and fuzzy matching on short common
# words kept producing false positives ("со" ~ "сон" at 0.8, "стала" ~ "устал"
# at 0.8) that let an ungrounded BAD recommendation slip through.
def _indication_term_matches(term: str, haystack: str) -> bool:
    return term in haystack


def count_matched_indication_categories(complaint_text: str) -> int:
    """How many DIFFERENT products' indication terms appear in this complaint?
    A precise proxy for "touches several unrelated body systems" — unlike raw
    word count, this doesn't false-positive on a long but single-topic
    complaint (e.g. a detailed description of only sleep/stress), and doesn't
    require guessing at symptoms outside our own three products' domains."""
    haystack = _normalize(complaint_text)
    return sum(
        1
        for terms in INDICATION_TERMS.values()
        if any(_indication_term_matches(term, haystack) for term in terms)
    )


def mentions_a_product_by_name(complaint_text: str) -> bool:
    """Does the text name one of our products/ingredients directly? Used to
    force tool-calling for informational questions ("когда лучше принимать d3")
    that a prompt instruction alone doesn't reliably trigger."""
    haystack = _normalize(complaint_text)
    return any(
        _indication_term_matches(term, haystack)
        for terms in PRODUCT_NAME_TERMS.values()
        for term in terms
    )


def is_bad_recommendation_grounded(bad_key: str, complaint_text: str) -> bool:
    """Does the user's own complaint plausibly mention one of bad_key's real
    indications? True (pass-through) for unknown keys — nothing to validate."""
    terms = INDICATION_TERMS.get(bad_key)
    if not terms:
        return True
    haystack = _normalize(complaint_text)
    return any(_indication_term_matches(term, haystack) for term in terms)


# ── Synergy rules ────────────────────────────────────────────────────────────
# Positive complementary-nutrient notes — separate from INTERACTION_RULES
# because these are "works better together" facts, not safety concerns.
# suggested_bad_key points back into our own catalog when we sell the partner
# ingredient too (so the bot can note it's already available), and stays None
# when the partner isn't something we sell (still worth mentioning honestly).

SYNERGY_RULES: list[dict] = [
    {
        "rule_id": "vitamin_d3_needs_magnesium",
        "ingredient_id": "vitamin_d3",
        "message": (
            "магний — необходимый кофактор для превращения витамина D в активную форму. "
            "При его нехватке приём D3 может быть менее эффективным."
        ),
        "suggested_bad_key": "magnesium",
        "source": "NIH ODS Vitamin D (Health Professional Fact Sheet): "
                   "https://ods.od.nih.gov/factsheets/VitaminD-HealthProfessional/ ; "
                   "PMC6693398 (Magnesium status and supplementation influence vitamin D status): "
                   "https://pmc.ncbi.nlm.nih.gov/articles/PMC6693398/",
    },
    {
        "rule_id": "vitamin_d3_pairs_with_k2",
        "ingredient_id": "vitamin_d3",
        "message": (
            "теоретически витамин K2 помогает направлять кальций в кости, а не в сосуды, и его "
            "иногда сочетают с D3 — но крупные рандомизированные исследования пока не показали "
            "однозначной клинической пользы такой комбинации, поэтому не считайте это обязательным."
        ),
        "suggested_bad_key": None,
        "source": "Механизм (правдоподобный, но не окончательно доказанный на практике): PMC11313760 "
                   "— The Importance of Vitamin K and the Combination of Vitamins K and D for "
                   "Calcium Metabolism and Bone Health: A Review: "
                   "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11313760/. "
                   "ОДНАКО реальные РКИ дают смешанный результат: AVADEC trial (JACC: Advances, "
                   "PMC11198368, https://pmc.ncbi.nlm.nih.gov/articles/PMC11198368/) не показал "
                   "значимого эффекта по основной конечной точке (прогрессирование кальцификации "
                   "аортального клапана) за 2 года, и в одной из подгрупп кальцификация аорты даже "
                   "могла усиливаться при снижении коронарной. Формулировка правила намеренно "
                   "смягчена — это НЕ подтверждённая исследованиями синергия, а лишь правдоподобная "
                   "гипотеза.",
    },
    {
        "rule_id": "collagen_needs_vitamin_c",
        "ingredient_id": "collagen",
        "message": (
            "витамин C необходим для синтеза собственного коллагена в организме — "
            "в нашем продукте он уже включён в состав."
        ),
        "suggested_bad_key": None,
        "source": "NCBI StatPearls — Biochemistry, Collagen Synthesis (NBK507709): "
                   "https://www.ncbi.nlm.nih.gov/books/NBK507709/",
    },
]


# ── Goal suggestion signals ──────────────────────────────────────────────────
# Separate from CONDITIONS: these are free-text symptom/complaint signals in
# chronic_diseases that hint which BAD_GOALS entry fits the person, not safety
# risks. Presentation-only — suggest_goal_keys() never hides a goal, it only
# tells the keyboard which one(s) to highlight/reorder first.

GOAL_SUGGESTION_SIGNALS: dict[str, dict] = {
    "sleep_stress": {
        "match_terms": [
            "бессонниц", "плохо сплю", "не могу уснуть", "стресс", "тревожн",
            "депресси", "нервн", "паническ",
        ],
    },
    "energy_immunity": {
        "match_terms": [
            "хроническая усталост", "упадок сил", "снижен иммунитет",
            "часто болею", "частые простуд", "низкий тонус", "утомляемост",
        ],
    },
    "beauty": {
        "match_terms": [
            "выпадение волос", "выпадают волос", "ломк ногт", "ломкост",
            "проблемы с кожей", "тусклая кожа", "акне", "угр",
        ],
    },
}


def suggest_goal_keys(profile: dict | None) -> list[str]:
    """Which BAD_GOALS entries fit this person's free-text chronic_diseases
    complaints — presentation hint only, never used to hide other goals."""
    if not profile:
        return []
    chronic_text = _normalize(profile.get("chronic_diseases") or "")
    if not chronic_text:
        return []
    return [
        goal_key
        for goal_key, signal in GOAL_SUGGESTION_SIGNALS.items()
        if _entry_matches(signal, chronic_text)
    ]


class SynergyNote(NamedTuple):
    bad_key: str
    message: str
    suggested_bad_key: str | None
    rule_id: str
    source: str | None


def get_bad_synergies(bad_key: str) -> list[SynergyNote]:
    """Known complementary-nutrient notes for this product — independent of
    the user's health profile, unlike check_bad_safety."""
    bad = BAD_DETAILS.get(bad_key, {})
    ingredient_ids = bad.get("ingredient_ids", [])
    return [
        SynergyNote(
            bad_key=bad_key, message=rule["message"],
            suggested_bad_key=rule["suggested_bad_key"], rule_id=rule["rule_id"],
            source=rule.get("source"),
        )
        for rule in SYNERGY_RULES
        if rule["ingredient_id"] in ingredient_ids
    ]


class SafetyWarning(NamedTuple):
    kind: str  # "pregnancy" | "contraindication" | "interaction" | "caution" | "general_caution"
    bad_key: str
    message: str
    rule_id: str | None
    source: str | None = None


# ── Matching ─────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return text.lower().replace("ё", "е").strip()


_FUZZY_MIN_TERM_LEN = 5  # below this, fuzzy matching false-positives on short/common
                          # words (e.g. "сон" ~ "со") became more likely than typos


def _term_matches(term: str, haystack_text: str) -> bool:
    if not haystack_text:
        return False
    if term in haystack_text:
        return True
    if len(term) < _FUZZY_MIN_TERM_LEN:
        return False
    words = haystack_text.split()
    return any(difflib.SequenceMatcher(None, term, w).ratio() > 0.75 for w in words)


def _entry_matches(entry: dict, haystack_text: str) -> bool:
    return any(_term_matches(term, haystack_text) for term in entry["match_terms"])


# ── Public API ───────────────────────────────────────────────────────────────

def check_bad_safety(bad_key: str, profile: dict | None) -> list[SafetyWarning]:
    """Single source of truth for БАД safety checks — used by the bot, the API,
    and (Phase 4) the AI's tool-calling path."""
    if not profile:
        return []

    bad = BAD_DETAILS[bad_key]
    name = bad["full_name"]
    ingredient_ids = bad.get("ingredient_ids", [])
    warnings: list[SafetyWarning] = []

    chronic_text = _normalize(profile.get("chronic_diseases") or "")
    allergies_text = _normalize(profile.get("allergies") or "")
    meds_text = _normalize(profile.get("medications") or "")
    pregnancy = profile.get("pregnancy") or "no"

    if pregnancy in ("pregnant", "lactating") and not bad.get("pregnancy_safe", False):
        warnings.append(SafetyWarning(
            kind="pregnancy", bad_key=bad_key, rule_id=None,
            message=(
                f"{name}: не подтверждена безопасность при беременности/лактации — "
                "перед приёмом проконсультируйтесь с врачом."
            ),
        ))

    for cond_id, cond in CONDITIONS.items():
        if cond.get("general_caution") and _entry_matches(cond, chronic_text):
            warnings.append(SafetyWarning(
                kind="general_caution", bad_key=bad_key, rule_id=f"general:{cond_id}",
                message=(
                    f"{name}: в вашем профиле указано «{cond['label']}» — это существенная "
                    "особенность здоровья, перед приёмом любых БАД проконсультируйтесь с врачом."
                ),
            ))

    for rule in INTERACTION_RULES:
        if rule["ingredient_id"] not in ingredient_ids:
            continue

        trigger_type = rule["trigger_type"]
        trigger_id = rule["trigger_id"]
        if trigger_type == "condition":
            matched = _entry_matches(CONDITIONS[trigger_id], chronic_text)
        elif trigger_type == "allergen":
            matched = _entry_matches(ALLERGENS[trigger_id], allergies_text)
        elif trigger_type == "medication":
            matched = _entry_matches(MEDICATIONS[trigger_id], meds_text)
        else:
            matched = False

        if matched:
            warnings.append(SafetyWarning(
                kind=rule["severity"], bad_key=bad_key, rule_id=rule["rule_id"],
                message=rule["message"].format(bad_name=name),
                source=rule.get("source"),
            ))

    return warnings
