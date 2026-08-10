import json
import logging
import re

from openai import AsyncOpenAI

from config import GROQ_API_KEY, MAX_QUESTIONS, SHOW_DOCTOR_RECOMMENDATIONS
from data.resources import DOCTORS, BADS

# Groq — бесплатный API, совместимый с OpenAI
client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = f"""Ты медицинский ассистент бота "Мой Доктор". Помогаешь пользователю разобраться с симптомами.

ТВОЯ РОЛЬ:
- Собирать симптомы через диалог, задавая уточняющие вопросы (строго по одному, максимум {MAX_QUESTIONS} штуки)
- После сбора данных — формировать рекомендации и подбирать врача
- При опасных симптомах — немедленно направлять в скорую

═══════════════════════════════════════
ТРИ ВОЗМОЖНЫХ ТИПА ОТВЕТА:

1. QUESTION — задаёшь уточняющий вопрос (если данных ещё недостаточно и лимит не исчерпан)
2. RECOMMENDATION — данных достаточно, выдаёшь рекомендации
3. EMERGENCY — обнаружены опасные симптомы

ЭКСТРЕННЫЕ СИМПТОМЫ (→ тип EMERGENCY):
боль в груди/за грудиной, удушье, потеря сознания, сильное кровотечение,
признаки инсульта (асимметрия лица, нарушение речи), суицидальные мысли

ПРАВИЛО ПРО ПЕРВОЕ СООБЩЕНИЕ: если пользователь только что в первый раз описал ЖАЛОБУ
НА САМОЧУВСТВИЕ (нет предыдущих твоих вопросов в диалоге) и это НЕ EMERGENCY — почти
всегда сначала задай тип QUESTION, а не RECOMMENDATION, даже если жалоба кажется простой
и знакомой. Одного слова или короткой фразы недостаточно ("диарея", "болит голова",
"тошнит") — уточни хотя бы одно из: как давно, насколько выражено/часто, есть ли
сопутствующие симптомы. Переходи к RECOMMENDATION с первого сообщения только если
пользователь сам уже дал развёрнутое описание, покрывающее это, или после этого явно
сказал, что больше добавить нечего.

ИСКЛЮЧЕНИЕ: если сообщение — не жалоба на самочувствие, а простой информационный
вопрос (например, "когда лучше принимать витамин D3", "можно ли пить магний натощак",
"сколько длится курс БАД") — НЕ задавай уточняющий вопрос о симптомах, это неуместно.
Сразу отвечай по существу в типе RECOMMENDATION, is_lifestyle=true, doctor_specialty
можно поставить "therapist" по умолчанию.
Если вопрос про конкретный БАД из нашего каталога (дозировка, время приёма, с едой или
натощак, длительность курса) — ОБЯЗАТЕЛЬНО вызови list_bads_catalog и ответь по данным
оттуда (поле notes), а не общими фразами о здоровом образе жизни. Например, про время
приёма D3 в notes уже есть конкретный ответ — используй его, а не пиши "соблюдайте
сбалансированную диету".

═══════════════════════════════════════
ДЛЯ ТИПА RECOMMENDATION:

doctor_specialty — ОБЯЗАТЕЛЬНО, одно из:
  "therapist"    → общие симптомы, простуда, ЖКТ, неясная причина
  "surgeon"      → боли в животе (аппендицит, грыжа), травмы, хирургические проблемы
  "cardiologist" → сердцебиение, давление, отёки, нарушения ритма
  "neurologist"  → головные боли, головокружение, онемение, нарушения сна (неврологические)
  "gynecologist" → женское здоровье, менструальный цикл, гинекологические боли
  "pediatrician" → симптомы у детей

bad_recommendation — ТОЛЬКО при lifestyle-проблемах (не при острых медицинских состояниях),
и ТОЛЬКО через инструменты (не по памяти):
  0. Если жалоба — это НЕСКОЛЬКО разных симптомов из разных систем организма сразу
     (например: вкус/запах + выпадение волос + кожные высыпания + плохое заживление
     ран + аппетит + частые простуды — всё вместе), особенно если это нарастает со
     временем — НЕ хватайся за БАД из-за случайного совпадения одного слова с одним
     из симптомов. Такая картина обычно требует очной диагностики. В этом случае
     bad_recommendation оставь null (ни один из НАШИХ 3 продуктов сюда не подходит),
     is_lifestyle=false, и прямо скажи в тексте, что с таким набором симптомов вместе
     лучше показаться врачу, а не пытаться закрыть это одной нашей добавкой.
     bad_recommendation подходит только для простой, изолированной lifestyle-жалобы
     (например, только плохой сон, или только сухая кожа) — не для сложной
     многосимптомной картины.
     Если сочетание симптомов узнаваемо указывает на что-то конкретное (например, эта
     комбинация — изменение вкуса/запаха, выпадение волос, плохое заживление ран, кожные
     высыпания — классически связана с дефицитом цинка) — НАЗОВИ это предположение в
     тексте осторожно, как гипотезу, а не диагноз ("похоже на..." / "такая картина
     часто связана с...", ни в коем случае не "у вас..."), И укажи конкретную добавку
     в general_supplement_suggestion (например, "цинк"), даже если её нет в нашем
     каталоге — general_supplement_suggestion как раз для этого. Не оставляй пользователя
     с одним лишь "обратитесь к врачу" без содержательной догадки, если она у тебя есть —
     это не диагноз, а полезный ориентир, который врачу тоже пригодится.
     ВАЖНО: в тексте для такого многосимптомного случая НЕ упоминай ни магний, ни
     коллаген, ни витамин D3 (наши 3 продукта) вообще, даже вскользь ("коллаген может
     помочь с..."), даже если bad_recommendation=null — пользователь читает это как
     рекомендацию независимо от того, что в структурированном поле. Раз bad_recommendation
     здесь null, значит ни один из наших продуктов не подходит — молчи о них и говори
     только о честной гипотезе (как цинк) или ничего не называй, если гипотезы нет.
  1. Вызови list_bads_catalog — узнай, какие БАД реально есть в каталоге и от чего они.
  2. Сравни жалобу пользователя ТОЛЬКО с полями goal/notes, которые вернул list_bads_catalog.
     НЕ придумывай дополнительных показаний и механизмов, которых там нет — например,
     если пользователь жалуется на вздутие живота/пищеварение, а в goal/notes магния
     об этом ни слова, значит магний НЕ подходит, даже если кажется, что "расслабление"
     могло бы теоретически помочь. Сомневаешься, подходит ли явно — считай, что не подходит.
  3. Если по показаниям (буквально из goal/notes) подходит один из них — вызови
     check_bad_safety(bad_key) для ЭТОГО пациента, чтобы проверить противопоказания и
     взаимодействия с его профилем.
  4. Если check_bad_safety вернул warnings с kind="contraindication" — НЕ указывай этот
     bad_recommendation, вместо этого упомяни риск в тексте ответа и направь к врачу.
     В этом случае НЕ переноси тот же продукт в general_supplement_suggestion — это поле
     только для добавок, которых НЕТ в нашем каталоге, а не для замены заблокированной
     рекомендации.
     Предупреждения с kind="caution"/"interaction"/"general_caution" не запрещают
     рекомендацию, но обязательно упомяни их простыми словами в тексте ответа.

general_supplement_suggestion — если для lifestyle-проблемы идеально подошла бы добавка,
которой НЕТ в нашем каталоге (например: железо, омега-3, витамин B12, пробиотики,
хондроитин+глюкозамин) — укажи её здесь простыми словами, без вызова инструментов
(они знают только о нашем каталоге). Никогда не указывай здесь название БАД из нашего
каталога (magnesium/collagen/vitamin_d3), даже если check_bad_safety его заблокировал.
ВАЖНО: НЕ пытайся подогнать проблему под наш каталог, если она ему на самом деле не
соответствует — честная рекомендация важнее продажи нашего продукта. Если general_supplement_suggestion
заполнен, bad_recommendation должен быть null, и наоборот.

is_lifestyle — true если это проблема образа жизни/самочувствия, false если острая медицинская ситуация

needs_followup — true, только если это РЕАЛЬНАЯ жалоба на самочувствие, за которой имеет
смысл проверить через несколько дней "как вы сейчас, помогли ли рекомендации". false для
информационных/бытовых вопросов без жалобы (когда/как принимать БАД, дозировка, натощак
или нет, длительность курса, общие вопросы про добавки) — там нечему "стать лучше", и
follow-up-сообщение будет выглядеть нелепо (пример: пользователь спросил "какой магний
лучше, хелат или цитрат", а через 3 дня бот спрашивает "как самочувствие?" — это неуместно).

═══════════════════════════════════════
ЖЁСТКИЕ ПРАВИЛА:
- НИКОГДА не ставь диагноз (используй формулировки "возможно", "могут указывать")
- Не назначай рецептурные препараты
- Не давай психиатрических советов — только направляй к специалисту
- Один вопрос за раз
- Простой русский язык, тёплый тон, сообщения до 3 абзацев
- Пиши ТОЛЬКО на русском — ни одного слова на английском (не "meantime", не "please" и
  т.п.), даже случайно затесавшегося посреди русского предложения
- Не преувеличивай эффект БАД — формулируй как "может помочь", "часто используется как поддержка",
  а не как гарантированное решение проблемы

ДЛЯ ТИПА RECOMMENDATION — текст должен содержать:
  Если is_lifestyle=false: конкретные советы "чего НЕ делать" до визита к врачу
  Если is_lifestyle=true: практические рекомендации по улучшению самочувствия

═══════════════════════════════════════
ФОРМАТ ОТВЕТА — строго JSON, никакого текста вне JSON:

{{
  "type": "question" | "recommendation" | "emergency",
  "text": "текст сообщения пользователю (без упоминания врача и БАДов — это добавится автоматически)",
  "doctor_specialty": null | "therapist" | "surgeon" | "cardiologist" | "neurologist" | "gynecologist" | "pediatrician",
  "bad_recommendation": null | "magnesium" | "collagen" | "vitamin_d3",
  "general_supplement_suggestion": null | "название добавки простыми словами",
  "is_lifestyle": false | true,
  "needs_followup": false | true
}}

Для type=question: doctor_specialty=null, bad_recommendation=null, general_supplement_suggestion=null, is_lifestyle=false, needs_followup=false
Для type=emergency: doctor_specialty=null, bad_recommendation=null, general_supplement_suggestion=null, is_lifestyle=false, needs_followup=false"""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

GENDER_RU = {"male": "мужской", "female": "женский"}
AGE_RU = {
    "under_18": "до 18 лет", "18_30": "18–30 лет",
    "31_45":    "31–45 лет", "46_60": "46–60 лет", "60_plus": "60+ лет",
}
SMOKING_RU = {
    "never": "не курит", "former": "бросил(а)",
    "light": "курит изредка", "heavy": "курит регулярно",
}
ALCOHOL_RU = {
    "never": "не употребляет", "rarely": "редко",
    "moderate": "умеренно",    "frequent": "часто",
}
ACTIVITY_RU = {
    "sedentary": "сидячий образ жизни", "light": "лёгкая активность",
    "moderate":  "умеренная активность", "high": "высокая активность",
}
PREGNANCY_RU = {
    "pregnant": "беременность", "lactating": "лактация", "no": "нет",
}


def _build_system(
    gender: str | None,
    age_range: str | None,
    profile: dict | None = None,
) -> str:
    """Build system prompt with full patient profile if available."""
    base_parts = []
    if gender:
        base_parts.append(f"пол: {GENDER_RU.get(gender, gender)}")
    if age_range:
        base_parts.append(f"возраст: {AGE_RU.get(age_range, age_range)}")

    if not base_parts and not profile:
        return SYSTEM_PROMPT

    def _v(d: dict, key: str) -> str:
        v = (d.get(key) or "").strip()
        return v if v and v not in ("нет", "не указано") else "нет"

    if profile and profile.get("onboarding_done"):
        member_name = profile.get("name")
        if member_name:
            header = (
                f"\n\nПОЛНЫЙ ПРОФИЛЬ ПАЦИЕНТА — {member_name} "
                f"(консультируем НЕ владельца аккаунта, а {member_name}; "
                "используй именно этот профиль):"
            )
        else:
            header = "\n\nПОЛНЫЙ ПРОФИЛЬ ПАЦИЕНТА (используй для точных, безопасных рекомендаций):"
        lines = [header]
        if base_parts:
            lines.append("  • " + ", ".join(base_parts))
        lines += [
            f"  • хронические болезни:  {_v(profile, 'chronic_diseases')}",
            f"  • аллергии:             {_v(profile, 'allergies')}",
            f"  • постоянные лекарства: {_v(profile, 'medications')}",
        ]
        if gender == "female":
            preg = PREGNANCY_RU.get(profile.get("pregnancy") or "", "нет")
            lines.append(f"  • беременность/лактация:{preg}")
        lines += [
            f"  • перенесённые операции:{_v(profile, 'past_surgeries')}",
            f"  • наследственность:     {_v(profile, 'hereditary_diseases')}",
            f"  • курение:              {SMOKING_RU.get(profile.get('smoking') or '', 'нет данных')}",
            f"  • алкоголь:             {ALCOHOL_RU.get(profile.get('alcohol') or '', 'нет данных')}",
            f"  • физическая активность:{ACTIVITY_RU.get(profile.get('physical_activity') or '', 'нет данных')}",
            f"  • рост/вес:             {_v(profile, 'height_weight')}",
        ]
        profile_note = "\n".join(lines)
    else:
        profile_note = (
            "\n\nДАННЫЕ ПАЦИЕНТА:\n  • " + ", ".join(base_parts)
            if base_parts else ""
        )

    return SYSTEM_PROMPT + profile_note


MAX_TOOL_ROUNDS = 3

_ENGLISH_WORD_RE = re.compile(r"\b[a-zA-Z]{3,}\b")


def _contains_stray_english(text: str) -> bool:
    """The 'пиши только на русском' prompt rule alone isn't reliably followed —
    this is a deterministic backstop, same pattern as bad_recommendation grounding."""
    return bool(_ENGLISH_WORD_RE.search(text or ""))


async def _run_tool_loop(
    chat_messages: list[dict],
    model: str,
    profile: dict | None,
    reasoning_format: str | None = None,
    max_tokens: int = 900,
) -> dict:
    """Shared tool-dispatch loop: lets the model call list_bads_catalog/
    check_bad_safety (ai/tools.py) instead of free-associating a supplement
    from its own training knowledge. check_bad_safety is executed against the
    *real* profile passed in here — the model only ever supplies a bad_key,
    never health data.

    `reasoning_format` is only needed for "thinking" models (the vision model)
    to keep <think> reasoning out of the JSON content — "parsed" is the value
    that's been verified to work with both tool-calling and JSON mode. Note
    reasoning tokens still count against max_tokens even when hidden from
    `content`, so thinking models need a bigger budget than plain text models.
    """
    from ai.tools import TOOL_SCHEMAS, execute_tool
    from data.bad_safety import mentions_a_product_by_name

    extra_body = {"reasoning_format": reasoning_format} if reasoning_format else None

    # Keyed by bad_key — captured as the model calls check_bad_safety, so the
    # final warnings can be attached to the response deterministically instead
    # of trusting the model to relay them in its free-text answer.
    safety_results: dict[str, dict] = {}

    # The model doesn't reliably call list_bads_catalog on prompt instruction
    # alone for informational questions ("когда лучше принимать d3?" — verified
    # live) — force a tool call on the first round when the user names one of
    # our products directly, instead of trusting it to decide to look it up.
    user_text = " ".join(
        m["content"] for m in chat_messages
        if m.get("role") == "user" and isinstance(m.get("content"), str)
    )
    force_first_tool_call = mentions_a_product_by_name(user_text)

    msg = None
    for round_num in range(MAX_TOOL_ROUNDS):
        kwargs = dict(
            model=model, messages=chat_messages,
            tools=TOOL_SCHEMAS,
            tool_choice="required" if (round_num == 0 and force_first_tool_call) else "auto",
            temperature=0.3, max_tokens=max_tokens,
        )
        if extra_body:
            kwargs["extra_body"] = extra_body
        response = await client.chat.completions.create(**kwargs)
        msg = response.choices[0].message
        if not msg.tool_calls:
            break

        chat_messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = execute_tool(tc.function.name, args, profile)
            if tc.function.name == "check_bad_safety" and "bad_key" in result:
                safety_results[result["bad_key"]] = result
            chat_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
    else:
        # Exhausted rounds while the model kept calling tools — force a final answer.
        chat_messages.append({
            "role": "user",
            "content": "Дай финальный ответ строго в формате JSON, как указано в инструкциях, без новых вызовов инструментов.",
        })
        kwargs = dict(
            model=model, messages=chat_messages,
            response_format={"type": "json_object"},
            temperature=0.3, max_tokens=max_tokens,
        )
        if extra_body:
            kwargs["extra_body"] = extra_body
        response = await client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

    parsed = _extract_json(msg.content or "")
    if parsed is None:
        # Thinking-model reasoning length varies run to run and can occasionally
        # burn through the whole budget before the final JSON is written out —
        # retry the same call once with double the budget before giving up.
        logging.warning("Empty/invalid JSON response, retrying with larger max_tokens")
        retry_kwargs = dict(kwargs)
        retry_kwargs["max_tokens"] = min(max_tokens * 2, 6000)
        response = await client.chat.completions.create(**retry_kwargs)
        msg = response.choices[0].message
        parsed = _extract_json(msg.content or "")

    if parsed is None:
        raise ValueError(f"Model response was not valid JSON: {msg.content!r}")

    async def _ask_for_rewrite(instruction: str) -> dict | None:
        """Ask the model to rewrite its last JSON answer with a corrective
        instruction — used when a deterministic check catches something prompt
        instructions alone didn't reliably prevent."""
        chat_messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
        chat_messages.append({"role": "user", "content": instruction})
        rewrite_kwargs = dict(
            model=model, messages=chat_messages,
            response_format={"type": "json_object"},
            temperature=0.3, max_tokens=max_tokens,
        )
        if extra_body:
            rewrite_kwargs["extra_body"] = extra_body
        response = await client.chat.completions.create(**rewrite_kwargs)
        return _extract_json(response.choices[0].message.content or "")

    bad_key = parsed.get("bad_recommendation")

    complaint_text = " ".join(
        m["content"] for m in chat_messages
        if m.get("role") == "user" and isinstance(m.get("content"), str)
    )

    if bad_key:
        from data.bad_safety import is_bad_recommendation_grounded
        if not is_bad_recommendation_grounded(bad_key, complaint_text):
            logging.warning(f"Ungrounded bad_recommendation={bad_key!r} for {complaint_text!r}, asking for a rewrite")
            # Dropping just the structured field isn't enough — the model's own
            # `text` usually still repeats the invented claim ("magnesium helps
            # digestion"). Ask it to rewrite rather than silently truncate.
            corrected = await _ask_for_rewrite(
                f"Проверка показала: '{bad_key}' на самом деле не входит в реальные "
                f"показания этого БАД (goal/notes из list_bads_catalog) для описанной "
                f"жалобы — не придумывай механизм, которого там нет. Перепиши ответ: "
                f"НЕ упоминай {bad_key} и не утверждай, что он поможет при этой жалобе "
                f"(ни в bad_recommendation, ни в тексте). Если для жалобы подходит другая "
                f"добавка не из нашего каталога — укажи её в general_supplement_suggestion, "
                f"иначе оставь оба поля null. Ответь тем же JSON-форматом, без вызова инструментов."
            )
            if corrected is not None:
                parsed = corrected
                bad_key = parsed.get("bad_recommendation")
                if bad_key and not is_bad_recommendation_grounded(bad_key, complaint_text):
                    logging.warning(f"Rewrite still ungrounded ({bad_key!r}) — dropping the field")
                    parsed["bad_recommendation"] = None
                    bad_key = None
            else:
                parsed["bad_recommendation"] = None
                bad_key = None

        # A complaint touching 2+ of our products' indication domains at once
        # (e.g. skin/hair terms AND immunity terms together) is a precise proxy
        # for "several distinct symptoms across body systems" — the kind of
        # picture where a single keyword match isn't enough grounds for a
        # confident BAD recommendation. (Raw word count was tried first and
        # rejected — it false-positived on long but single-topic complaints,
        # e.g. a detailed sleep/stress description.) The prompt rule alone
        # doesn't reliably catch this either (verified live — worked ~1/3 of
        # the time), so force a second-opinion pass instead of trusting it.
        from data.bad_safety import count_matched_indication_categories
        if bad_key and count_matched_indication_categories(complaint_text) >= 2:
            logging.warning(f"Complex multi-symptom complaint with bad_recommendation={bad_key!r}, double-checking")
            corrected = await _ask_for_rewrite(
                "Жалоба выше описывает НЕСКОЛЬКО разных симптомов сразу, а не одну "
                f"изолированную lifestyle-проблему. Перепроверь: точно ли '{bad_key}' — "
                "уместная рекомендация для ВСЕЙ этой картины, а не только для одного "
                "случайно совпавшего слова? Если другие симптомы (например, изменение "
                "вкуса/запаха, кожные изменения, плохое заживление ран) указывают на что-то, "
                "требующее очной диагностики, а не самостоятельного подбора БАД — оставь "
                "bad_recommendation и general_supplement_suggestion null, is_lifestyle=false, "
                "и направь к врачу. Ответь тем же JSON-форматом, без вызова инструментов."
            )
            if corrected is not None:
                parsed = corrected
                bad_key = parsed.get("bad_recommendation")

    # Even when bad_recommendation correctly ended up null for a complex
    # multi-symptom complaint, the model's free-text `text` sometimes still
    # name-drops one of our own products ("коллаген может помочь с...") as an
    # aside — the user reads that as a recommendation regardless of what the
    # structured field says. Verified live (worked ~5/6 of the time on prompt
    # instruction alone, but the 1/6 miss is exactly this confusing case).
    from data.bad_safety import count_matched_indication_categories, mentions_a_product_by_name
    if (
        not bad_key
        and count_matched_indication_categories(complaint_text) >= 2
        and mentions_a_product_by_name(parsed.get("text", ""))
    ):
        logging.warning(f"Text names a catalog product despite bad_recommendation=None, asking for a rewrite: {parsed.get('text')!r}")
        corrected = await _ask_for_rewrite(
            "В тексте твоего ответа упомянут один из НАШИХ продуктов (магний/коллаген/"
            "витамин D3), хотя bad_recommendation=null — то есть ни один из них на самом "
            "деле не подходит для этой многосимптомной картины. Перепиши текст БЕЗ "
            "упоминания этих продуктов, даже вскользь — оставь только честную гипотезу "
            "(если она есть, через general_supplement_suggestion) и направление к врачу. "
            "Ответь тем же JSON-форматом, без вызова инструментов."
        )
        if corrected is not None:
            parsed = corrected
            bad_key = parsed.get("bad_recommendation")

    if _contains_stray_english(parsed.get("text", "")):
        logging.warning(f"Stray English in response, asking for a rewrite: {parsed.get('text')!r}")
        corrected = await _ask_for_rewrite(
            "В твоём ответе есть слово(-а) на английском языке (например, случайно "
            "затесавшееся 'meantime'). Перепиши ВЕСЬ ответ полностью на русском, без "
            "единого английского слова. Ответь тем же JSON-форматом, без вызова инструментов."
        )
        if corrected is not None:
            parsed = corrected
            bad_key = parsed.get("bad_recommendation")

    safety = safety_results.get(bad_key) if bad_key else None
    if safety and safety["warnings"]:
        parsed["_grounded_safety_warnings"] = [w["message"] for w in safety["warnings"]]

    return parsed


async def analyze_symptoms(
    messages: list[dict],
    gender: str | None = None,
    age_range: str | None = None,
    profile: dict | None = None,
) -> dict:
    """Call Groq Llama and return a parsed response dict."""
    chat_messages = [
        {"role": "system", "content": _build_system(gender, age_range, profile)}
    ] + list(messages)

    try:
        return await _run_tool_loop(chat_messages, "llama-3.3-70b-versatile", profile)
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        return {
            "type": "recommendation",
            "text": "Произошла техническая ошибка. Рекомендую обратиться к терапевту для очной консультации.",
            "doctor_specialty": "therapist",
            "bad_recommendation": None,
            "general_supplement_suggestion": None,
            "is_lifestyle": False,
            "needs_followup": False,
        }


# ---------------------------------------------------------------------------
# Photo analysis
# ---------------------------------------------------------------------------

PHOTO_PROMPT = """Ты медицинский ассистент. Пользователь прислал фото медицинского документа.

ТВОЯ ЗАДАЧА:
1. Определи тип документа (анализ крови, ЭКГ, рецепт, снимок и т.д.)
2. Если это лабораторные анализы — найди отклонения от нормы и объясни простым языком
3. Дай практические рекомендации
4. Подбери нужного специалиста

ПРАВИЛА:
- Никогда не ставь диагноз — только "возможно", "может указывать"
- Простой язык без латинских терминов (или с расшифровкой в скобках)
- Пиши ТОЛЬКО на русском — ни одного английского слова, даже случайно затесавшегося
  посреди русского предложения
- Если фото нечёткое или не является медицинским документом — честно скажи об этом
- Ответ — 2–4 коротких абзаца
- Не преувеличивай эффект БАД — формулируй как "может помочь", а не как гарантированное решение

BAD-рекомендации (только при явных показаниях, и только если это реально один из НАШИХ БАД):
  magnesium   → дефицит магния, нарушения сна, стресс, мышечные спазмы
  vitamin_d3  → низкий витамин D, слабый иммунитет, хроническая усталость
  collagen    → проблемы с суставами, кожей, волосами, ногтями

Если по анализам идеально подошла бы добавка не из нашего каталога (железо, B12,
омега-3, пробиотики и т.д.) — укажи её в general_supplement_suggestion простыми
словами, а bad_recommendation оставь null. Не подгоняй результат под наш каталог.

ПРАВИЛО ПО ВРАЧУ — doctor_specialty ВСЕГДА обязателен, никогда не null:
  "therapist"    → общий анализ крови, биохимия, неясная причина
  "cardiologist" → давление, сердечный ритм, ЭКГ
  "surgeon"      → травмы, хирургические патологии
  "neurologist"  → неврологические показатели, МРТ/КТ головы
  "gynecologist" → женские гормоны, гинекологические показатели
  "pediatrician" → детские анализы

ФОРМАТ ОТВЕТА (строго JSON, без текста вне JSON):
{
  "text": "ответ пользователю — без упоминания врача и БАД, они добавятся автоматически",
  "doctor_specialty": "therapist" | "surgeon" | "cardiologist" | "neurologist" | "gynecologist" | "pediatrician",
  "bad_recommendation": null | "magnesium" | "collagen" | "vitamin_d3",
  "general_supplement_suggestion": null | "название добавки простыми словами",
  "is_lifestyle": false | true
}"""


def _extract_json(text: str) -> dict | None:
    """Extract JSON from model response even if wrapped in markdown code blocks."""
    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. Inside ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # 3. First {...} block in the text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


# Groq deprecated the old llama-4-scout vision model; qwen/qwen3.6-27b is the
# current vision-capable model and (unlike the old one) supports tool-calling
# and JSON mode. It's a "thinking" model — reasoning_format="parsed" keeps
# <think> reasoning out of the JSON content (verified: "hidden" breaks JSON
# mode entirely on this model, "parsed" works with both JSON mode and tools).
_VISION_MODEL = "qwen/qwen3.6-27b"
_VISION_REASONING_FORMAT = "parsed"


def _profile_note(gender: str | None, age_range: str | None) -> str:
    if not (gender or age_range):
        return ""
    parts = []
    if gender:
        parts.append(f"пол: {GENDER_RU.get(gender, gender)}")
    if age_range:
        parts.append(f"возраст: {AGE_RU.get(age_range, age_range)}")
    return f"\n\nДАННЫЕ ПАЦИЕНТА: {', '.join(parts)}"


async def analyze_photo(
    image_b64: str,
    gender: str | None = None,
    age_range: str | None = None,
) -> dict:
    """Send a base64 image to the Groq vision model and return parsed response.

    No tool-calling here (unlike analyze_symptoms) — qwen/qwen3.6-27b's free-tier
    daily token quota (200k) is easily exhausted by a multi-round tool loop, since
    its internal reasoning alone can burn 500-1600+ tokens per call. bad_recommendation
    is picked from the hardcoded PHOTO_PROMPT list here, same as before Phase 4.
    """
    prompt = PHOTO_PROMPT + _profile_note(gender, age_range)
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            {"type": "text", "text": prompt},
        ],
    }]

    max_tokens = 2500
    try:
        # Thinking-model reasoning tokens count against max_tokens even though
        # reasoning_format="parsed" hides them from `content` — reasoning length
        # varies run to run, so retry once with a bigger budget if the JSON came
        # back truncated/empty before giving up.
        for attempt_max_tokens in (max_tokens, min(max_tokens * 2, 5000)):
            response = await client.chat.completions.create(
                model=_VISION_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                extra_body={"reasoning_format": _VISION_REASONING_FORMAT},
                temperature=0.3,
                max_tokens=attempt_max_tokens,
            )
            raw = response.choices[0].message.content
            result = _extract_json(raw or "")
            if result and "text" in result:
                return result
            logging.warning(f"Vision response not valid JSON (max_tokens={attempt_max_tokens}): {raw!r}")

        raise ValueError("Vision model did not return valid JSON after retry")
    except Exception as e:
        logging.error(f"Vision model error: {e}")
        return {
            "text": (
                "Не удалось обработать изображение 😔\n"
                "Убедитесь, что фото чёткое и хорошо освещённое, "
                "или опишите симптомы текстом — я обязательно помогу."
            ),
            "doctor_specialty": None,
            "bad_recommendation": None,
            "general_supplement_suggestion": None,
            "is_lifestyle": False,
        }


async def analyze_lab_text(
    text: str,
    gender: str | None = None,
    age_range: str | None = None,
) -> dict:
    """Analyze lab results extracted from PDF as plain text via the text model."""
    prompt = (
        PHOTO_PROMPT + _profile_note(gender, age_range)
        + "\n\nТЕКСТ ИЗ PDF-ДОКУМЕНТА С АНАЛИЗАМИ:\n" + text[:3000]
    )

    try:
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=900,
        )
        raw = response.choices[0].message.content
        result = _extract_json(raw)
        if result and "text" in result:
            return result
        return {
            "text": raw.strip(),
            "doctor_specialty": "therapist",
            "bad_recommendation": None,
            "general_supplement_suggestion": None,
            "is_lifestyle": False,
        }
    except Exception as e:
        logging.error(f"Lab text analysis error: {e}")
        return {
            "text": "Не удалось проанализировать документ 😔\nОпишите симптомы текстом — я обязательно помогу.",
            "doctor_specialty": "therapist",
            "bad_recommendation": None,
            "general_supplement_suggestion": None,
            "is_lifestyle": False,
        }


RECOMMENDATION_DISCLAIMER = (
    "<i>⚠️ Это не диагноз и не медицинское заключение — бот даёт только общие "
    "рекомендации. За точным заключением обратитесь к врачу.</i>"
)


def build_recommendation_message(ai_response: dict) -> str:
    """Assemble the final message: AI text + doctor link + optional BAD link.

    The disclaimer is appended here in code, not left to the prompt — a prompt
    instruction alone wasn't reliably followed for other things this session
    (English-word leakage, tool-calling), and this one should never be skipped.
    """
    parts = [ai_response["text"], ""]

    doctor_key = ai_response.get("doctor_specialty")
    if SHOW_DOCTOR_RECOMMENDATIONS and doctor_key and doctor_key in DOCTORS:
        d = DOCTORS[doctor_key]
        parts += [
            "🏥 <b>Запись к врачу:</b>",
            f'👨‍⚕️ <a href="{d["url"]}">{d["name"]} — записаться онлайн</a>',
            "",
        ]

    bad_key = ai_response.get("bad_recommendation")
    if bad_key and bad_key in BADS:
        b = BADS[bad_key]
        parts += [
            "💊 <b>Рекомендуем поддерживающий БАД:</b>",
            f'✨ <a href="{b["url"]}">{b["name"]}</a> — {b["description"]}',
        ]
        grounded_warnings = ai_response.get("_grounded_safety_warnings")
        if grounded_warnings:
            parts += [""] + [f"⚠️ {w}" for w in grounded_warnings]

    general_suggestion = ai_response.get("general_supplement_suggestion")
    if general_suggestion:
        parts += [
            "💊 <b>Может помочь:</b>",
            f"{general_suggestion} — перед началом приёма в любом случае посоветуйтесь с врачом.",
        ]

    parts += ["", RECOMMENDATION_DISCLAIMER]

    return "\n".join(parts).strip()
