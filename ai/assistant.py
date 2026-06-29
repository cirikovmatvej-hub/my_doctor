import json
import logging
import re

from openai import AsyncOpenAI

from config import GROQ_API_KEY, MAX_QUESTIONS
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

═══════════════════════════════════════
ДЛЯ ТИПА RECOMMENDATION:

doctor_specialty — ОБЯЗАТЕЛЬНО, одно из:
  "therapist"    → общие симптомы, простуда, ЖКТ, неясная причина
  "surgeon"      → боли в животе (аппендицит, грыжа), травмы, хирургические проблемы
  "cardiologist" → сердцебиение, давление, отёки, нарушения ритма
  "neurologist"  → головные боли, головокружение, онемение, нарушения сна (неврологические)
  "gynecologist" → женское здоровье, менструальный цикл, гинекологические боли
  "pediatrician" → симптомы у детей

bad_recommendation — ТОЛЬКО при lifestyle-проблемах (не при острых медицинских состояниях):
  "magnesium"   → плохой сон, стресс, тревожность, раздражительность, мышечные судороги
  "collagen"    → проблемы с кожей, волосами, ногтями, суставами
  "vitamin_d3"  → слабость, частые болезни, низкий иммунитет, упадок сил, депрессивный фон

is_lifestyle — true если это проблема образа жизни/самочувствия, false если острая медицинская ситуация

═══════════════════════════════════════
ЖЁСТКИЕ ПРАВИЛА:
- НИКОГДА не ставь диагноз (используй формулировки "возможно", "могут указывать")
- Не назначай рецептурные препараты
- Не давай психиатрических советов — только направляй к специалисту
- Один вопрос за раз
- Простой русский язык, тёплый тон, сообщения до 3 абзацев

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
  "is_lifestyle": false | true
}}

Для type=question: doctor_specialty=null, bad_recommendation=null, is_lifestyle=false
Для type=emergency: doctor_specialty=null, bad_recommendation=null, is_lifestyle=false"""


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


async def analyze_symptoms(
    messages: list[dict],
    gender: str | None = None,
    age_range: str | None = None,
    profile: dict | None = None,
) -> dict:
    """Call Groq Llama and return a parsed response dict."""
    try:
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": _build_system(gender, age_range, profile)}] + messages,
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=800,
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        return {
            "type": "recommendation",
            "text": "Произошла техническая ошибка. Рекомендую обратиться к терапевту для очной консультации.",
            "doctor_specialty": "therapist",
            "bad_recommendation": None,
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

BAD-рекомендации (только при явных показаниях):
  magnesium   → дефицит магния, нарушения сна, стресс, мышечные спазмы
  vitamin_d3  → низкий витамин D, слабый иммунитет, хроническая усталость
  collagen    → проблемы с суставами, кожей, волосами, ногтями

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


_VISION_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
]


async def analyze_photo(
    image_b64: str,
    gender: str | None = None,
    age_range: str | None = None,
) -> dict:
    """Send a base64 image to the Groq vision model and return parsed response."""
    profile_note = ""
    if gender or age_range:
        parts = []
        if gender:
            parts.append(f"пол: {GENDER_RU.get(gender, gender)}")
        if age_range:
            parts.append(f"возраст: {AGE_RU.get(age_range, age_range)}")
        profile_note = f"\n\nДАННЫЕ ПАЦИЕНТА: {', '.join(parts)}"

    prompt = PHOTO_PROMPT + profile_note
    last_error = None

    for model in _VISION_MODELS:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                # NOTE: no response_format — vision models don't support JSON mode
                temperature=0.3,
                max_tokens=900,
            )
            raw = response.choices[0].message.content
            logging.info(f"Vision raw response ({model}): {raw[:200]}")

            result = _extract_json(raw)
            if result and "text" in result:
                return result

            # Model replied but without JSON — use the text as-is
            return {
                "text": raw.strip(),
                "doctor_specialty": "therapist",
                "bad_recommendation": None,
                "is_lifestyle": False,
            }

        except Exception as e:
            last_error = e
            logging.warning(f"Vision model {model} failed: {e}")
            continue

    logging.error(f"All vision models failed. Last error: {last_error}")
    return {
        "text": (
            "Не удалось обработать изображение 😔\n"
            "Убедитесь, что фото чёткое и хорошо освещённое, "
            "или опишите симптомы текстом — я обязательно помогу."
        ),
        "doctor_specialty": None,
        "bad_recommendation": None,
        "is_lifestyle": False,
    }


async def analyze_lab_text(
    text: str,
    gender: str | None = None,
    age_range: str | None = None,
) -> dict:
    """Analyze lab results extracted from PDF as plain text via the text model."""
    profile_note = ""
    if gender or age_range:
        parts = []
        if gender:
            parts.append(f"пол: {GENDER_RU.get(gender, gender)}")
        if age_range:
            parts.append(f"возраст: {AGE_RU.get(age_range, age_range)}")
        profile_note = f"\n\nДАННЫЕ ПАЦИЕНТА: {', '.join(parts)}"

    prompt = PHOTO_PROMPT + profile_note + "\n\nТЕКСТ ИЗ PDF-ДОКУМЕНТА С АНАЛИЗАМИ:\n" + text[:3000]

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
            "is_lifestyle": False,
        }
    except Exception as e:
        logging.error(f"Lab text analysis error: {e}")
        return {
            "text": "Не удалось проанализировать документ 😔\nОпишите симптомы текстом — я обязательно помогу.",
            "doctor_specialty": "therapist",
            "bad_recommendation": None,
            "is_lifestyle": False,
        }


def build_recommendation_message(ai_response: dict) -> str:
    """Assemble the final message: AI text + doctor link + optional BAD link."""
    parts = [ai_response["text"], ""]

    doctor_key = ai_response.get("doctor_specialty")
    if doctor_key and doctor_key in DOCTORS:
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

    return "\n".join(parts).strip()
