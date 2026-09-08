"""
Regression tests for the deterministic emergency backstop in ai/assistant.py:
before this, "type": "emergency" detection relied entirely on the LLM's own
judgment on every single message, with no code-level fallback for classic
red-flag phrasing (chest pain, stroke signs, suicidal ideation, etc.) — unlike
every other safety-critical field in this file (bad_recommendation grounding,
safety-check enforcement), which already has a deterministic backstop.
"""
import asyncio
from unittest.mock import AsyncMock, patch

from ai.assistant import _contains_emergency_symptoms, analyze_symptoms


def test_recognizes_classic_emergency_phrases():
    for text in (
        "у меня сильная боль в груди и тяжело дышать",
        "болит за грудиной уже час",
        "муж потерял сознание пять минут назад",
        "у соседки сильное кровотечение, не останавливается",
        "у отца перекосило лицо и заплетается язык",
        "не хочу больше жить, думаю о суициде",
    ):
        assert _contains_emergency_symptoms(text), text


def test_does_not_flag_ordinary_complaints():
    for text in (
        "болит голова второй день",
        "тошнит по утрам",
        "какой магний лучше выбрать",
        "болит живот после еды",
        "плохо сплю из-за стресса",
    ):
        assert not _contains_emergency_symptoms(text), text


def test_analyze_symptoms_short_circuits_to_emergency_without_calling_the_api():
    # Patching the client to raise proves the backstop fires before any
    # network call — critical for an actual emergency, where round-tripping
    # to Groq first would just add latency for no benefit (consultation.py
    # ignores the AI's own "text" for type=="emergency" and sends a fixed
    # canned message regardless).
    async def _boom(*args, **kwargs):
        raise AssertionError("API should not be called when the backstop fires")

    async def run():
        messages = [{"role": "user", "content": "болит в груди, задыхаюсь"}]
        with patch("ai.assistant.client.chat.completions.create", AsyncMock(side_effect=_boom)):
            return await analyze_symptoms(messages)

    result = asyncio.run(run())
    assert result["type"] == "emergency"
    assert result["doctor_specialty"] is None
    assert result["bad_recommendation"] is None
