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

ПРАВИЛО ПРО ПЕРВОЕ СООБЩЕНИЕ: если пользователь только что в первый раз описал жалобу
(нет предыдущих твоих вопросов в диалоге) и это НЕ EMERGENCY — почти всегда сначала
задай тип QUESTION, а не RECOMMENDATION, даже если жалоба кажется простой и знакомой.
Одного слова или короткой фразы недостаточно ("диарея", "болит голова", "тошнит") —
уточни хотя бы одно из: как давно, насколько выражено/часто, есть ли сопутствующие
симптомы. Переходи к RECOMMENDATION с первого сообщения только если пользователь сам
уже дал развёрнутое описание, покрывающее это, или после этого явно сказал, что
больше добавить нечего.

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

═══════════════════════════════════════
ЖЁСТКИЕ ПРАВИЛА:
- НИКОГДА не ставь диагноз (используй формулировки "возможно", "могут указывать")
- Не назначай рецептурные препараты
- Не давай психиатрических советов — только направляй к специалисту
- Один вопрос за раз
- Простой русский язык, тёплый тон, сообщения до 3 абзацев
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
  "is_lifestyle": false | true
}}

Для type=question: doctor_specialty=null, bad_recommendation=null, general_supplement_suggestion=null, is_lifestyle=false
Для type=emergency: doctor_specialty=null, bad_recommendation=null, general_supplement_suggestion=null, is_lifestyle=false"""


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

    extra_body = {"reasoning_format": reasoning_format} if reasoning_format else None

    # Keyed by bad_key — captured as the model calls check_bad_safety, so the
    # final warnings can be attached to the response deterministically instead
    # of trusting the model to relay them in its free-text answer.
    safety_results: dict[str, dict] = {}

    msg = None
    for _ in range(MAX_TOOL_ROUNDS):
        kwargs = dict(
            model=model, messages=chat_messages,
            tools=TOOL_SCHEMAS, tool_choice="auto",
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

    bad_key = parsed.get("bad_recommendation")

    if bad_key:
        from data.bad_safety import is_bad_recommendation_grounded
        complaint_text = " ".join(
            m["content"] for m in chat_messages
            if m.get("role") == "user" and isinstance(m.get("content"), str)
        )
        if not is_bad_recommendation_grounded(bad_key, complaint_text):
            logging.warning(f"Ungrounded bad_recommendation={bad_key!r} for {complaint_text!r}, asking for a rewrite")
            # Dropping just the structured field isn't enough — the model's own
            # `text` usually still repeats the invented claim ("magnesium helps
            # digestion"). Ask it to rewrite rather than silently truncate.
            chat_messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)})
            chat_messages.append({
                "role": "user",
                "content": (
                    f"Проверка показала: '{bad_key}' на самом деле не входит в реальные "
                    f"показания этого БАД (goal/notes из list_bads_catalog) для описанной "
                    f"жалобы — не придумывай механизм, которого там нет. Перепиши ответ: "
                    f"НЕ упоминай {bad_key} и не утверждай, что он поможет при этой жалобе "
                    f"(ни в bad_recommendation, ни в тексте). Если для жалобы подходит другая "
                    f"добавка не из нашего каталога — укажи её в general_supplement_suggestion, "
                    f"иначе оставь оба поля null. Ответь тем же JSON-форматом, без вызова инструментов."
                ),
            })
            correction_kwargs = dict(
                model=model, messages=chat_messages,
                response_format={"type": "json_object"},
                temperature=0.3, max_tokens=max_tokens,
            )
            if extra_body:
                correction_kwargs["extra_body"] = extra_body
            response = await client.chat.completions.create(**correction_kwargs)
            corrected = _extract_json(response.choices[0].message.content or "")
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


def build_recommendation_message(ai_response: dict) -> str:
    """Assemble the final message: AI text + doctor link + optional BAD link."""
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

    return "\n".join(parts).strip()
