"""
Knowledge base for supplements we do NOT sell (no catalog card, no Ozon link,
no course tracking) but can honestly name via `general_supplement_suggestion`
when a lifestyle complaint doesn't fit magnesium/collagen/vitamin_d3.

Before this existed, `general_supplement_suggestion` was pure free text the
model invented with zero grounding and zero safety-checking (see ai/assistant.py
system prompt history) — the whole point of this module is to give that field
the same treatment BAD_DETAILS/bad_safety.py already gives the 3 catalog
products: a real indication check against the user's own wording, and a real
contraindication/interaction check against their health profile, backed by
NIH ODS / NCCIH / Mayo Clinic sources.

Reuses CONDITIONS/ALLERGENS/MEDICATIONS from data.bad_safety — same matching
logic, same "stems not full words" style, same generous-on-grounding/
conservative-on-safety philosophy documented there.
"""
from typing import NamedTuple

from data.bad_safety import ALLERGENS, CONDITIONS, MEDICATIONS, SafetyWarning, _entry_matches, _normalize

# ── Knowledge base ───────────────────────────────────────────────────────────
# indication_terms: for grounding — is the user's own wording actually about
# this substance? (name + typical complaint words, same pattern as
# PRODUCT_NAME_TERMS + _SYMPTOM_TERMS in bad_safety.py, just not split in two
# since there's no separate "force tool call" feature for this domain yet.)
# pregnancy_safe: same conservative default as BAD_DETAILS — False unless
# there's a clear, specific basis to call it safe at typical supplemental doses.

GENERAL_SUPPLEMENTS: dict[str, dict] = {
    "iron": {
        "label": "железо",
        "indication_terms": ["железо", "ферритин", "анеми", "бледност"],
        "goal": "коррекция подтверждённого анализом дефицита железа (низкий ферритин) — бледность, слабость, повышенная утомляемость",
        "notes": None,
        "pregnancy_safe": True,
    },
    "omega3": {
        "label": "омега-3",
        "indication_terms": ["омега-3", "омега 3", "рыбий жир", "рыбьего жира"],
        "goal": "поддержка сердечно-сосудистой системы и общего противовоспалительного фона",
        "notes": None,
        "pregnancy_safe": True,
    },
    "vitamin_b12": {
        "label": "витамин B12",
        "indication_terms": ["витамин b12", "витамин в12", "б12", "в12"],
        "goal": "коррекция дефицита B12 — утомляемость, покалывание в конечностях, особенно на фоне метформина или веганского питания",
        "notes": None,
        "pregnancy_safe": True,
    },
    "zinc": {
        "label": "цинк",
        "indication_terms": ["цинк", "вкус", "запах", "заживлен", "выпадение волос"],
        "goal": "поддержка иммунитета и заживления; классическая гипотеза при сочетании изменения вкуса/запаха, выпадения волос, плохого заживления ран и кожных высыпаний",
        "notes": "Постоянные высокие дозы цинка (выше рекомендованных) могут приводить к дефициту меди — не превышайте дозировку без назначения врача.",
        "pregnancy_safe": True,
    },
    "probiotics": {
        "label": "пробиотики",
        "indication_terms": ["пробиотик", "микрофлор", "дисбактериоз", "вздутие"],
        "goal": "поддержка микрофлоры кишечника, часто после курса антибиотиков или при нарушениях пищеварения",
        "notes": None,
        "pregnancy_safe": False,
    },
    "glucosamine_chondroitin": {
        "label": "глюкозамин и хондроитин",
        "indication_terms": ["глюкозамин", "хондроитин", "сустав"],
        "goal": "поддержка суставов при дискомфорте/скованности — доказательная база умеренная",
        "notes": None,
        "pregnancy_safe": False,
    },
    "vitamin_c": {
        "label": "витамин C",
        "indication_terms": ["витамин c", "витамин с", "аскорбин"],
        "goal": "поддержка иммунитета, антиоксидантная защита",
        "notes": None,
        "pregnancy_safe": True,
    },
    "calcium": {
        "label": "кальций",
        "indication_terms": ["кальций", "кости", "остеопороз"],
        "goal": "поддержка костей, особенно при риске остеопороза",
        "notes": None,
        "pregnancy_safe": True,
    },
    "selenium": {
        "label": "селен",
        "indication_terms": ["селен"],
        "goal": "антиоксидантная поддержка, иногда при заболеваниях щитовидной железы — по назначению врача",
        "notes": None,
        "pregnancy_safe": False,
    },
    "iodine": {
        "label": "йод",
        "indication_terms": ["йод", "щитовидн"],
        "goal": "поддержка функции щитовидной железы — избыток так же вреден, как и недостаток",
        "notes": None,
        "pregnancy_safe": False,
    },
    "folate": {
        "label": "фолиевая кислота",
        "indication_terms": ["фолиев", "фолат", "b9", "в9"],
        "goal": "профилактика дефицита фолиевой кислоты, особенно важна при планировании беременности",
        "notes": None,
        "pregnancy_safe": True,
    },
    "vitamin_b6": {
        "label": "витамин B6",
        "indication_terms": ["витамин b6", "витамин в6", "пиридоксин"],
        "goal": "иногда используется при ПМС, тошноте при беременности — по назначению врача",
        "notes": "Длительный приём высоких доз (от 1000 мг/сут, изредка меньше) может вызывать периферическую невропатию — не превышайте рекомендованную дозировку.",
        "pregnancy_safe": True,
    },
    "vitamin_a": {
        "label": "витамин A",
        "indication_terms": ["витамин a", "витамин а", "ретинол"],
        "goal": "используется при дефиците витамина A — редко актуально при обычном питании, важна умеренность дозы",
        "notes": "При беременности высокие дозы (от 3000 мкг РЭ / 10000 МЕ в сутки) связаны с риском врождённых пороков развития — используйте формы с бета-каротином или только по назначению врача.",
        "pregnancy_safe": False,
    },
    "vitamin_e": {
        "label": "витамин E",
        "indication_terms": ["витамин e", "витамин е", "токоферол"],
        "goal": "антиоксидантная поддержка",
        "notes": None,
        "pregnancy_safe": True,
    },
    "potassium": {
        "label": "калий",
        "indication_terms": ["калий", "судорог в ногах"],
        "goal": "коррекция дефицита калия — обычно только по назначению врача после анализа крови",
        "notes": None,
        "pregnancy_safe": True,
    },
    "melatonin": {
        "label": "мелатонин",
        "indication_terms": ["мелатонин", "джетлаг", "смена часовых поясов"],
        "goal": "коротким курсом при нарушении засыпания или смене часовых поясов",
        "notes": None,
        "pregnancy_safe": False,
    },
    "coq10": {
        "label": "коэнзим Q10",
        "indication_terms": ["коэнзим q10", "коq10", "убихинон"],
        "goal": "иногда используется для поддержки энергетического обмена, в т.ч. на фоне приёма статинов — по согласованию с врачом",
        "notes": None,
        "pregnancy_safe": False,
    },
    "ashwagandha": {
        "label": "ашваганда",
        "indication_terms": ["ашваганда", "витания"],
        "goal": "адаптоген, иногда используется при стрессе — доказательная база ограниченная",
        "notes": "В традиционной медицине упоминается как средство с абортивным потенциалом — не рекомендуется при беременности.",
        "pregnancy_safe": False,
    },
    "alpha_lipoic_acid": {
        "label": "альфа-липоевая кислота",
        "indication_terms": ["альфа-липоев", "липоевая кислота"],
        "goal": "иногда используется при диабетической нейропатии — по назначению врача",
        "notes": "Может снижать всасывание биотина и связывать тиреоидные гормоны в кишечнике — принимайте с интервалом от других добавок и препаратов щитовидной железы.",
        "pregnancy_safe": False,
    },
    "l_carnitine": {
        "label": "L-карнитин",
        "indication_terms": ["карнитин"],
        "goal": "иногда используется для поддержки при физических нагрузках — доказательная база ограниченная",
        "notes": None,
        "pregnancy_safe": False,
    },
    "creatine": {
        "label": "креатин",
        "indication_terms": ["креатин"],
        "goal": "поддержка силовых показателей при физических нагрузках",
        "notes": "Временно повышает креатинин в крови, что может имитировать проблему с почками на анализах — предупредите врача, если сдаёте такой анализ.",
        "pregnancy_safe": False,
    },
    "curcumin": {
        "label": "куркумин",
        "indication_terms": ["куркумин", "куркума"],
        "goal": "противовоспалительная поддержка в виде концентрированной добавки (не как специя в еде)",
        "notes": None,
        "pregnancy_safe": False,
    },
    "st_johns_wort": {
        "label": "зверобой",
        "indication_terms": ["зверобо"],
        "goal": "иногда используется при лёгком сниженном настроении — имеет много серьёзных лекарственных взаимодействий",
        "notes": None,
        "pregnancy_safe": False,
    },
    "ginkgo_biloba": {
        "label": "гинкго билоба",
        "indication_terms": ["гинкго"],
        "goal": "иногда используется для поддержки памяти и концентрации — доказательная база ограниченная",
        "notes": None,
        "pregnancy_safe": False,
    },
    "biotin": {
        "label": "биотин",
        "indication_terms": ["биотин", "витамин b7", "витамин н"],
        "goal": "часто используется для волос и ногтей — доказательства пользы при отсутствии дефицита слабые",
        "notes": "Высокие дозы (от 5 мг/сут) искажают результаты некоторых лабораторных анализов, включая гормоны щитовидной железы — предупредите врача перед сдачей анализов.",
        "pregnancy_safe": True,
    },
    "valerian": {
        "label": "валериана",
        "indication_terms": ["валериан"],
        "goal": "мягкое успокоительное при лёгких нарушениях сна — курсом, не постоянно",
        "notes": None,
        "pregnancy_safe": False,
    },
    "5htp": {
        "label": "5-HTP",
        "indication_terms": ["5-htp", "5 htp", "гидрокситриптофан"],
        "goal": "иногда используется при сниженном настроении и нарушениях сна — требует осторожности из-за лекарственных взаимодействий",
        "notes": None,
        "pregnancy_safe": False,
    },
}

for _key, _entry in GENERAL_SUPPLEMENTS.items():
    _entry["ingredient_ids"] = [_key]


# ── Interaction rules ─────────────────────────────────────────────────────
# Same shape as data.bad_safety.INTERACTION_RULES — kept in a separate list
# (not merged into it) so the two knowledge domains — sold products vs. named-
# but-not-sold supplements — stay independently auditable.

GENERAL_INTERACTION_RULES: list[dict] = [
    {
        "rule_id": "iron_hemochromatosis",
        "ingredient_id": "iron",
        "trigger_type": "condition",
        "trigger_id": "hemochromatosis",
        "severity": "contraindication",
        "message": "{name}: при гемохроматозе/избытке железа дополнительный приём противопоказан — может усугубить перегрузку железом.",
        "source": "NIH ODS — Iron (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Iron-HealthProfessional/",
    },
    {
        "rule_id": "iron_levothyroxine",
        "ingredient_id": "iron",
        "trigger_type": "medication",
        "trigger_id": "levothyroxine",
        "severity": "interaction",
        "message": "{name}: снижает всасывание левотироксина — разнесите приём минимум на 4 часа.",
        "source": "NIH ODS — Iron (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Iron-HealthProfessional/",
    },
    {
        "rule_id": "omega3_anticoagulant",
        "ingredient_id": "omega3",
        "trigger_type": "medication",
        "trigger_id": "anticoagulant",
        "severity": "interaction",
        "message": "{name}: высокие дозы в сочетании с антикоагулянтами/антиагрегантами могут повышать риск кровотечения — обсудите дозу с врачом.",
        "source": "NIH ODS — Omega-3 Fatty Acids (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Omega3FattyAcids-HealthProfessional/",
    },
    {
        "rule_id": "b12_antidiabetic",
        "ingredient_id": "vitamin_b12",
        "trigger_type": "medication",
        "trigger_id": "antidiabetic",
        "severity": "caution",
        "message": "{name}: длительный приём метформина может снижать уровень B12 — на этом фоне стоит периодически проверять его уровень.",
        "source": "NIH ODS — Vitamin B12 (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/VitaminB12-HealthProfessional/",
    },
    {
        "rule_id": "zinc_quinolone",
        "ingredient_id": "zinc",
        "trigger_type": "medication",
        "trigger_id": "quinolone",
        "severity": "interaction",
        "message": "{name}: снижает всасывание фторхинолоновых антибиотиков — разнесите приём минимум на 2 часа.",
        "source": "NIH ODS — Zinc (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Zinc-HealthProfessional/",
    },
    {
        "rule_id": "zinc_tetracycline",
        "ingredient_id": "zinc",
        "trigger_type": "medication",
        "trigger_id": "tetracycline",
        "severity": "interaction",
        "message": "{name}: снижает всасывание тетрациклинов — разнесите приём минимум на 2 часа.",
        "source": "NIH ODS — Zinc (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Zinc-HealthProfessional/",
    },
    {
        "rule_id": "probiotics_immunocompromised",
        "ingredient_id": "probiotics",
        "trigger_type": "condition",
        "trigger_id": "immunocompromised",
        "severity": "contraindication",
        "message": "{name}: при иммунодефиците или на фоне химиотерапии живые бактериальные культуры в редких случаях вызывали системную инфекцию — приём только по согласованию с врачом.",
        "source": "NIH NCCIH — Probiotics: Usefulness and Safety: https://www.nccih.nih.gov/health/probiotics-usefulness-and-safety",
    },
    {
        "rule_id": "glucosamine_shellfish",
        "ingredient_id": "glucosamine_chondroitin",
        "trigger_type": "allergen",
        "trigger_id": "shellfish",
        "severity": "caution",
        "message": "{name}: часто производится из панцирей ракообразных — при аллергии на морепродукты уточните состав или выберите синтетический аналог.",
        "source": "Mayo Clinic — Glucosamine: https://www.mayoclinic.org/drugs-supplements-glucosamine/art-20362874",
    },
    {
        "rule_id": "glucosamine_anticoagulant",
        "ingredient_id": "glucosamine_chondroitin",
        "trigger_type": "medication",
        "trigger_id": "anticoagulant",
        "severity": "interaction",
        "message": "{name}: (особенно вместе с хондроитином) может усиливать эффект варфарина — повышен риск кровотечения.",
        "source": "AAFP — Glucosamine: https://www.aafp.org/pubs/afp/issues/2008/0815/p471.html",
    },
    {
        "rule_id": "vitamin_c_hemochromatosis",
        "ingredient_id": "vitamin_c",
        "trigger_type": "condition",
        "trigger_id": "hemochromatosis",
        "severity": "caution",
        "message": "{name}: высокие дозы усиливают усвоение железа и при гемохроматозе могут усугубить перегрузку железом.",
        "source": "NIH ODS — Vitamin C (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/VitaminC-HealthProfessional/",
    },
    {
        "rule_id": "vitamin_c_kidney",
        "ingredient_id": "vitamin_c",
        "trigger_type": "condition",
        "trigger_id": "kidney_disease",
        "severity": "caution",
        "message": "{name}: высокие дозы могут повышать риск образования оксалатных камней, особенно при заболеваниях почек.",
        "source": "NIH ODS — Vitamin C (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/VitaminC-HealthProfessional/",
    },
    {
        "rule_id": "calcium_levothyroxine",
        "ingredient_id": "calcium",
        "trigger_type": "medication",
        "trigger_id": "levothyroxine",
        "severity": "interaction",
        "message": "{name}: снижает всасывание левотироксина — разнесите приём минимум на 4 часа.",
        "source": "NIH ODS — Calcium (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Calcium-HealthProfessional/",
    },
    {
        "rule_id": "calcium_thiazide",
        "ingredient_id": "calcium",
        "trigger_type": "medication",
        "trigger_id": "thiazide",
        "severity": "caution",
        "message": "{name}: тиазидные диуретики снижают выведение кальция с мочой — на этом фоне повышен риск избытка кальция в крови, нужен контроль врача.",
        "source": "NIH ODS — Calcium (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Calcium-HealthProfessional/",
    },
    {
        "rule_id": "calcium_quinolone",
        "ingredient_id": "calcium",
        "trigger_type": "medication",
        "trigger_id": "quinolone",
        "severity": "interaction",
        "message": "{name}: снижает всасывание фторхинолоновых антибиотиков — разнесите приём минимум на 2 часа.",
        "source": "NIH ODS — Calcium (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Calcium-HealthProfessional/",
    },
    {
        "rule_id": "selenium_anticoagulant",
        "ingredient_id": "selenium",
        "trigger_type": "medication",
        "trigger_id": "anticoagulant",
        "severity": "interaction",
        "message": "{name}: может повышать риск кровотечения при приёме антикоагулянтов/антиагрегантов (варфарин, гепарин, аспирин).",
        "source": "NIH ODS — Selenium (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Selenium-HealthProfessional/",
    },
    {
        "rule_id": "iodine_antithyroid",
        "ingredient_id": "iodine",
        "trigger_type": "medication",
        "trigger_id": "antithyroid",
        "severity": "contraindication",
        "message": "{name}: высокие дозы вместе с антитиреоидными препаратами могут чрезмерно подавить выработку гормонов щитовидной железы — приём только по назначению врача.",
        "source": "NIH ODS — Iodine (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Iodine-HealthProfessional/",
    },
    {
        "rule_id": "iodine_ace_inhibitor",
        "ingredient_id": "iodine",
        "trigger_type": "medication",
        "trigger_id": "ace_inhibitor",
        "severity": "interaction",
        "message": "{name}: в форме йодида калия вместе с иАПФ может повышать уровень калия в крови до опасного значения.",
        "source": "NIH ODS — Iodine (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Iodine-HealthProfessional/",
    },
    {
        "rule_id": "iodine_potassium_sparing_diuretic",
        "ingredient_id": "iodine",
        "trigger_type": "medication",
        "trigger_id": "potassium_sparing_diuretic",
        "severity": "interaction",
        "message": "{name}: в форме йодида калия вместе с калийсберегающими диуретиками также может повышать калий до опасного уровня.",
        "source": "NIH ODS — Iodine (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Iodine-HealthProfessional/",
    },
    {
        "rule_id": "folate_methotrexate",
        "ingredient_id": "folate",
        "trigger_type": "medication",
        "trigger_id": "methotrexate",
        "severity": "interaction",
        "message": "{name}: может влиять на эффективность метотрексата при лечении онкологических и аутоиммунных заболеваний — приём согласуйте с лечащим врачом.",
        "source": "NIH ODS — Folate (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Folate-HealthProfessional/",
    },
    {
        "rule_id": "b6_levodopa",
        "ingredient_id": "vitamin_b6",
        "trigger_type": "medication",
        "trigger_id": "levodopa",
        "severity": "interaction",
        "message": "{name}: в дозе от 5 мг/сут и выше снижает эффективность леводопы без карбидопы — не сочетайте без консультации врача.",
        "source": "StatPearls — Vitamin B6 (Pyridoxine): https://www.ncbi.nlm.nih.gov/books/NBK557436/",
    },
    {
        "rule_id": "vitamin_e_anticoagulant",
        "ingredient_id": "vitamin_e",
        "trigger_type": "medication",
        "trigger_id": "anticoagulant",
        "severity": "interaction",
        "message": "{name}: высокие дозы (от 400 МЕ/сут) в сочетании с антикоагулянтами/антиагрегантами повышают риск кровотечения.",
        "source": "NIH ODS — Vitamin E (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/VitaminE-HealthProfessional/",
    },
    {
        "rule_id": "potassium_kidney",
        "ingredient_id": "potassium",
        "trigger_type": "condition",
        "trigger_id": "kidney_disease",
        "severity": "contraindication",
        "message": "{name}: при заболеваниях почек приём может привести к опасному повышению уровня калия в крови (гиперкалиемия) — только по назначению врача.",
        "source": "NIH ODS — Potassium (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Potassium-HealthProfessional/",
    },
    {
        "rule_id": "potassium_ace_inhibitor",
        "ingredient_id": "potassium",
        "trigger_type": "medication",
        "trigger_id": "ace_inhibitor",
        "severity": "interaction",
        "message": "{name}: иАПФ снижают выведение калия — вместе с добавкой калия риск опасной гиперкалиемии.",
        "source": "NIH ODS — Potassium (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Potassium-HealthProfessional/",
    },
    {
        "rule_id": "potassium_potassium_sparing_diuretic",
        "ingredient_id": "potassium",
        "trigger_type": "medication",
        "trigger_id": "potassium_sparing_diuretic",
        "severity": "interaction",
        "message": "{name}: калийсберегающие диуретики также повышают риск гиперкалиемии в сочетании с добавками калия.",
        "source": "NIH ODS — Potassium (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Potassium-HealthProfessional/",
    },
    {
        "rule_id": "melatonin_sedative",
        "ingredient_id": "melatonin",
        "trigger_type": "medication",
        "trigger_id": "sedative",
        "severity": "interaction",
        "message": "{name}: вместе с седативными/снотворными усиливает сонливость и риск чрезмерной седации.",
        "source": "NIH NCCIH — Melatonin: What You Need To Know: https://www.nccih.nih.gov/health/melatonin-what-you-need-to-know",
    },
    {
        "rule_id": "melatonin_anticoagulant",
        "ingredient_id": "melatonin",
        "trigger_type": "medication",
        "trigger_id": "anticoagulant",
        "severity": "interaction",
        "message": "{name}: может повышать риск кровотечения при приёме антикоагулянтов (варфарин и др.).",
        "source": "NIH NCCIH — Melatonin: What You Need To Know: https://www.nccih.nih.gov/health/melatonin-what-you-need-to-know",
    },
    {
        "rule_id": "melatonin_epilepsy",
        "ingredient_id": "melatonin",
        "trigger_type": "condition",
        "trigger_id": "epilepsy",
        "severity": "caution",
        "message": "{name}: при эпилепсии приём возможен только под наблюдением врача.",
        "source": "NIH NCCIH — Melatonin: What You Need To Know: https://www.nccih.nih.gov/health/melatonin-what-you-need-to-know",
    },
    {
        "rule_id": "coq10_anticoagulant",
        "ingredient_id": "coq10",
        "trigger_type": "medication",
        "trigger_id": "anticoagulant",
        "severity": "interaction",
        "message": "{name}: структурно похож на витамин K2 и может ослаблять эффект варфарина — при совместном приёме нужен более частый контроль МНО.",
        "source": "Drugs.com Interaction Checker — CoQ10 + Warfarin: https://www.drugs.com/drug-interactions/coq10-with-warfarin-2273-12874-2311-0.html",
    },
    {
        "rule_id": "ashwagandha_levothyroxine",
        "ingredient_id": "ashwagandha",
        "trigger_type": "medication",
        "trigger_id": "levothyroxine",
        "severity": "interaction",
        "message": "{name}: может повышать уровень собственных гормонов щитовидной железы — вместе с левотироксином нужен контроль врача, возможна коррекция дозы препарата.",
        "source": "Merck Manual Professional Edition — Ashwagandha: https://www.merckmanuals.com/professional/special-subjects/dietary-supplements/ashwagandha",
    },
    {
        "rule_id": "ashwagandha_sedative",
        "ingredient_id": "ashwagandha",
        "trigger_type": "medication",
        "trigger_id": "sedative",
        "severity": "interaction",
        "message": "{name}: усиливает седативный эффект снотворных и противотревожных препаратов — не сочетайте без консультации врача.",
        "source": "Merck Manual Professional Edition — Ashwagandha: https://www.merckmanuals.com/professional/special-subjects/dietary-supplements/ashwagandha",
    },
    {
        "rule_id": "ala_antidiabetic",
        "ingredient_id": "alpha_lipoic_acid",
        "trigger_type": "medication",
        "trigger_id": "antidiabetic",
        "severity": "interaction",
        "message": "{name}: усиливает действие инсулина и сахароснижающих препаратов — риск гипогликемии, требуется контроль сахара крови.",
        "source": "Drugs.com — Alpha-lipoic acid Interactions: https://www.drugs.com/drug-interactions/alpha-lipoic-acid.html",
    },
    {
        "rule_id": "l_carnitine_anticoagulant",
        "ingredient_id": "l_carnitine",
        "trigger_type": "medication",
        "trigger_id": "anticoagulant",
        "severity": "interaction",
        "message": "{name}: может усиливать эффект варфарина — повышен риск кровотечения, требуется более частый контроль МНО.",
        "source": "Drugs.com — L-Carnitine + Warfarin: https://www.drugs.com/drug-interactions/l-carnitine-with-warfarin-1454-13156-2311-0.html",
    },
    {
        "rule_id": "l_carnitine_levothyroxine",
        "ingredient_id": "l_carnitine",
        "trigger_type": "medication",
        "trigger_id": "levothyroxine",
        "severity": "caution",
        "message": "{name}: в высоких дозах может ослаблять действие гормонов щитовидной железы — при приёме левотироксина нужен контроль врача.",
        "source": "PubMed — Effects of L-carnitine on thyroid hormone metabolism: https://pubmed.ncbi.nlm.nih.gov/16175496/",
    },
    {
        "rule_id": "creatine_kidney",
        "ingredient_id": "creatine",
        "trigger_type": "condition",
        "trigger_id": "kidney_disease",
        "severity": "contraindication",
        "message": "{name}: при заболеваниях почек не рекомендуется — повышает нагрузку на почки и может исказить показатели креатинина в анализах.",
        "source": "PMC — Effect of creatine supplementation on kidney function: https://pmc.ncbi.nlm.nih.gov/articles/PMC12590749/",
    },
    {
        "rule_id": "curcumin_anticoagulant",
        "ingredient_id": "curcumin",
        "trigger_type": "medication",
        "trigger_id": "anticoagulant",
        "severity": "interaction",
        "message": "{name}: обладает мягким антикоагулянтным эффектом — вместе с варфарином/аспирином/клопидогрелем повышает риск кровотечения.",
        "source": "MedicineNet — Who Should Not Use Turmeric: https://www.medicinenet.com/who_should_not_use_turmeric/article.htm",
    },
    {
        "rule_id": "curcumin_gallstones",
        "ingredient_id": "curcumin",
        "trigger_type": "condition",
        "trigger_id": "gallstones",
        "severity": "contraindication",
        "message": "{name}: усиливает выработку желчи — противопоказан при желчнокаменной болезни и обструкции желчных путей.",
        "source": "MedicineNet — Who Should Not Use Turmeric: https://www.medicinenet.com/who_should_not_use_turmeric/article.htm",
    },
    {
        "rule_id": "curcumin_antidiabetic",
        "ingredient_id": "curcumin",
        "trigger_type": "medication",
        "trigger_id": "antidiabetic",
        "severity": "interaction",
        "message": "{name}: может усиливать действие сахароснижающих препаратов — риск гипогликемии.",
        "source": "MedicineNet — Who Should Not Use Turmeric: https://www.medicinenet.com/who_should_not_use_turmeric/article.htm",
    },
    {
        "rule_id": "sjw_ssri",
        "ingredient_id": "st_johns_wort",
        "trigger_type": "medication",
        "trigger_id": "ssri",
        "severity": "contraindication",
        "message": "{name}: вместе с антидепрессантами СИОЗС/СИОЗСН может вызвать опасный серотониновый синдром — не сочетайте без консультации врача.",
        "source": "PMC — The Effects of St. John's Wort and its Interactions with SSRIs: https://pmc.ncbi.nlm.nih.gov/articles/PMC12420457/",
    },
    {
        "rule_id": "sjw_anticoagulant",
        "ingredient_id": "st_johns_wort",
        "trigger_type": "medication",
        "trigger_id": "anticoagulant",
        "severity": "interaction",
        "message": "{name}: ускоряет распад варфарина в печени — может ослабить эффект антикоагулянта.",
        "source": "The Conversation — St John's wort: six drug interactions you should know about: https://theconversation.com/st-johns-wort-six-drug-interactions-you-should-know-about-245409",
    },
    {
        "rule_id": "sjw_hormonal_contraceptive",
        "ingredient_id": "st_johns_wort",
        "trigger_type": "medication",
        "trigger_id": "hormonal_contraceptive",
        "severity": "interaction",
        "message": "{name}: снижает эффективность гормональных контрацептивов — описаны случаи прорывных кровотечений и незапланированной беременности.",
        "source": "The Conversation — St John's wort: six drug interactions you should know about: https://theconversation.com/st-johns-wort-six-drug-interactions-you-should-know-about-245409",
    },
    {
        "rule_id": "ginkgo_anticoagulant",
        "ingredient_id": "ginkgo_biloba",
        "trigger_type": "medication",
        "trigger_id": "anticoagulant",
        "severity": "interaction",
        "message": "{name}: повышает риск кровотечения при приёме антикоагулянтов/антиагрегантов и НПВС.",
        "source": "StatPearls — Ginkgo Biloba: https://www.ncbi.nlm.nih.gov/books/NBK541024/",
    },
    {
        "rule_id": "biotin_anticonvulsant",
        "ingredient_id": "biotin",
        "trigger_type": "medication",
        "trigger_id": "anticonvulsant",
        "severity": "caution",
        "message": "{name}: длительный приём противосудорожных препаратов (карбамазепин, фенитоин, вальпроаты, фенобарбитал) снижает уровень биотина в организме.",
        "source": "NIH ODS — Biotin (Health Professional Fact Sheet): https://ods.od.nih.gov/factsheets/Biotin-HealthProfessional/",
    },
    {
        "rule_id": "valerian_sedative",
        "ingredient_id": "valerian",
        "trigger_type": "medication",
        "trigger_id": "sedative",
        "severity": "interaction",
        "message": "{name}: усиливает эффект седативных/снотворных препаратов и алкоголя — не сочетайте.",
        "source": "NIH NCCIH — Valerian: Usefulness and Safety: https://www.nccih.nih.gov/health/valerian",
    },
    {
        "rule_id": "5htp_ssri",
        "ingredient_id": "5htp",
        "trigger_type": "medication",
        "trigger_id": "ssri",
        "severity": "contraindication",
        "message": "{name}: вместе с антидепрессантами СИОЗС/СИОЗСН повышает риск серотонинового синдрома — не сочетайте без консультации врача.",
        "source": "Memorial Sloan Kettering Cancer Center — 5-HTP: https://www.mskcc.org/cancer-care/integrative-medicine/herbs/5-htp-01",
    },
]


# ── Matching / public API ───────────────────────────────────────────────────
# Same generous-grounding/conservative-safety split as data.bad_safety.

def _indication_term_matches(term: str, haystack: str) -> bool:
    return term in haystack


def list_general_supplements() -> dict:
    return {
        key: {"name": d["label"], "goal": d["goal"], "notes": d["notes"]}
        for key, d in GENERAL_SUPPLEMENTS.items()
    }


def mentions_a_general_supplement_by_name(text: str | None) -> bool:
    """Does the text name one of the 27 supplements directly (e.g. "стоит ли
    пить омега-3")? Used to force tool-calling for informational questions,
    same reasoning as mentions_a_product_by_name in data.bad_safety — a
    prompt instruction alone doesn't reliably trigger the tool call."""
    return resolve_general_supplement_key(text) is not None


def resolve_general_supplement_key(text: str | None) -> str | None:
    """Map free text (the model's own `general_supplement_suggestion` label,
    or a user's message) back to a known key, by matching against each
    entry's Russian label. Returns None for anything outside the 27 known
    substances — that's fine, general_supplement_suggestion stays free text
    for the genuinely novel case, it just won't get grounding/safety-checked."""
    if not text:
        return None
    haystack = _normalize(text)
    for key, entry in GENERAL_SUPPLEMENTS.items():
        if _normalize(entry["label"]) in haystack:
            return key
    return None


def is_general_supplement_grounded(key: str, complaint_text: str) -> bool:
    """Does the user's own complaint plausibly mention one of this
    supplement's real indications? True (pass-through) for unknown keys."""
    entry = GENERAL_SUPPLEMENTS.get(key)
    if not entry:
        return True
    haystack = _normalize(complaint_text)
    return any(_indication_term_matches(term, haystack) for term in entry["indication_terms"])


def check_general_supplement_safety(key: str, profile: dict | None) -> list[SafetyWarning]:
    """Mirrors data.bad_safety.check_bad_safety but against the general
    (non-catalog) knowledge base — same CONDITIONS/ALLERGENS/MEDICATIONS,
    same matching, just a different rule list and a different ingredient
    namespace (no overlap with BAD_DETAILS keys)."""
    if not profile:
        return []

    entry = GENERAL_SUPPLEMENTS.get(key)
    if not entry:
        return []

    name = entry["label"]
    ingredient_ids = entry.get("ingredient_ids", [])
    warnings: list[SafetyWarning] = []

    chronic_text = _normalize(profile.get("chronic_diseases") or "")
    allergies_text = _normalize(profile.get("allergies") or "")
    meds_text = _normalize(profile.get("medications") or "")
    pregnancy = profile.get("pregnancy") or "no"

    if pregnancy in ("pregnant", "lactating") and not entry.get("pregnancy_safe", False):
        warnings.append(SafetyWarning(
            kind="pregnancy", bad_key=key, rule_id=None,
            message=(
                f"{name}: не подтверждена безопасность при беременности/лактации — "
                "перед приёмом проконсультируйтесь с врачом."
            ),
        ))

    for cond_id, cond in CONDITIONS.items():
        if cond.get("general_caution") and _entry_matches(cond, chronic_text):
            warnings.append(SafetyWarning(
                kind="general_caution", bad_key=key, rule_id=f"general:{cond_id}",
                message=(
                    f"{name}: в вашем профиле указано «{cond['label']}» — это существенная "
                    "особенность здоровья, перед приёмом любых БАД проконсультируйтесь с врачом."
                ),
            ))

    for rule in GENERAL_INTERACTION_RULES:
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
                kind=rule["severity"], bad_key=key, rule_id=rule["rule_id"],
                message=rule["message"].format(name=name),
                source=rule.get("source"),
            ))

    return warnings
